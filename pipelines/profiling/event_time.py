"""Explicit, safe event-time parsing (Phase 1A section 11, Phase 1C section 9).

Two rules drive this module:

1. **The filename is never the event date.**  The known sample ships with a
   filename date that disagrees with its telemetry, so business dates are only
   ever derived from parsed content.
2. **Day-first is declared, never inferred.**  ``07-08-2026`` is genuinely
   ambiguous.  Rather than let a parser guess, candidate formats are configured
   in order and the one that actually parses the data is selected and recorded.

Source timestamps carry no timezone, so a configured source timezone is applied
and the result is stored as UTC-aware.  The *business date*, however, is
computed in the source timezone - a charger's day is its own local day.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import polars as pl

from backend.app.models.enums import FileDateSpan

__all__ = [
    "TimestampAnalysis",
    "analyse_event_time",
    "extract_filename_date",
    "resolve_timezone",
]


@dataclass(frozen=True, slots=True)
class TimestampAnalysis:
    """Everything the pipeline knows about a file's event-time column."""

    column: str
    #: The strptime format that actually worked, or None if none did.
    chosen_format: str | None
    total_values: int
    null_count: int
    parsed_count: int
    failed_count: int
    unique_count: int

    #: UTC-aware bounds of the telemetry.
    event_time_min: dt.datetime | None
    event_time_max: dt.datetime | None

    median_interval_seconds: float | None
    p95_interval_seconds: float | None
    min_interval_seconds: float | None
    max_interval_seconds: float | None

    #: Local business date -> number of unique timestamps falling on it.
    business_dates: dict[dt.date, int] = field(default_factory=dict)
    dominant_business_date: dt.date | None = None
    date_span: FileDateSpan = FileDateSpan.UNKNOWN

    #: Sorted unique UTC timestamps; the input to gap detection.
    unique_timestamps: tuple[dt.datetime, ...] = ()
    source_timezone: str = "UTC"

    @property
    def failure_ratio(self) -> float:
        """Share of non-null values that could not be parsed."""
        considered = self.total_values - self.null_count
        if considered <= 0:
            return 0.0
        return self.failed_count / considered

    @property
    def parsed_any(self) -> bool:
        return self.parsed_count > 0

    def is_within_tolerance(self, tolerance: float) -> bool:
        return self.parsed_any and self.failure_ratio <= tolerance


def resolve_timezone(name: str) -> ZoneInfo:
    """Resolve a configured timezone, falling back to UTC rather than crashing."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _interval_stats(timestamps: pl.Series) -> tuple[float | None, ...]:
    """Median / p95 / min / max seconds between consecutive unique timestamps.

    Computed over *unique* timestamps so that the 8-rows-per-timestamp grain and
    any replayed frames cannot distort cadence (Phase 1C section 10).
    """
    if timestamps.len() < 2:
        return (None, None, None, None)

    deltas = timestamps.sort().diff().drop_nulls().dt.total_microseconds() / 1_000_000
    positive = deltas.filter(deltas > 0)
    if positive.len() == 0:
        return (None, None, None, None)

    return (
        _as_seconds(positive.median()),
        _as_seconds(positive.quantile(0.95, interpolation="nearest")),
        _as_seconds(positive.min()),
        _as_seconds(positive.max()),
    )


def _as_seconds(value: object) -> float:
    """Narrow a Polars aggregate scalar to a float.

    Polars types aggregates as a broad union; anything non-numeric here would be
    a bug in the caller's dtype assumptions, so it degrades to 0.0 rather than
    raising inside profiling.
    """
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float | Decimal):
        return float(value)
    return 0.0


def _classify_span(dates: list[dt.date]) -> FileDateSpan:
    if not dates:
        return FileDateSpan.UNKNOWN
    if len(dates) == 1:
        return FileDateSpan.SINGLE_DAY
    ordered = sorted(dates)
    if len(ordered) == 2 and (ordered[1] - ordered[0]).days == 1:
        return FileDateSpan.CROSS_MIDNIGHT
    return FileDateSpan.MULTI_DAY


def analyse_event_time(
    values: pl.Series,
    *,
    column: str,
    formats: list[str],
    source_timezone: str = "UTC",
) -> TimestampAnalysis:
    """Parse an event-time column and derive the file's temporal shape.

    ``values`` is expected to be a Utf8 series - Phase 1A reads every column as
    text so nothing is coerced behind our back.
    """
    tzinfo = resolve_timezone(source_timezone)
    total = values.len()

    text = values.cast(pl.Utf8, strict=False).str.strip_chars()
    text = text.set(text.str.len_chars() == 0, None)  # empty string is absent, not a value
    null_count = int(text.null_count())
    considered = total - null_count

    best_format: str | None = None
    best_parsed: pl.Series | None = None
    best_success = -1

    for candidate in formats:
        parsed = text.str.strptime(pl.Datetime("us"), format=candidate, strict=False)
        success = int(parsed.len() - parsed.null_count())
        if success > best_success:
            best_success, best_format, best_parsed = success, candidate, parsed
        if considered and success == considered:
            break  # a perfect format cannot be improved upon

    if best_parsed is None or best_success <= 0:
        return TimestampAnalysis(
            column=column,
            chosen_format=None,
            total_values=total,
            null_count=null_count,
            parsed_count=0,
            failed_count=max(considered, 0),
            unique_count=0,
            event_time_min=None,
            event_time_max=None,
            median_interval_seconds=None,
            p95_interval_seconds=None,
            min_interval_seconds=None,
            max_interval_seconds=None,
            source_timezone=source_timezone,
        )

    valid = best_parsed.drop_nulls()

    # Business dates are local dates: the charger's own day boundary.
    local_dates = valid.dt.date()
    date_counts = (
        pl.DataFrame({"d": local_dates, "t": valid})
        .unique(subset=["t"])
        .group_by("d")
        .len()
        .sort("d")
    )
    business_dates = {row[0]: int(row[1]) for row in date_counts.iter_rows() if row[0] is not None}
    dominant = max(business_dates, key=lambda d: (business_dates[d], -d.toordinal()), default=None)

    # Localise to the source timezone, then normalise to UTC for storage.
    aware = valid.dt.replace_time_zone(source_timezone).dt.convert_time_zone("UTC")
    unique_sorted = aware.unique().sort()

    median_s, p95_s, min_s, max_s = _interval_stats(unique_sorted)

    return TimestampAnalysis(
        column=column,
        chosen_format=best_format,
        total_values=total,
        null_count=null_count,
        parsed_count=int(valid.len()),
        failed_count=max(considered - int(valid.len()), 0),
        unique_count=int(unique_sorted.len()),
        event_time_min=unique_sorted.item(0) if unique_sorted.len() else None,
        event_time_max=unique_sorted.item(-1) if unique_sorted.len() else None,
        median_interval_seconds=median_s,
        p95_interval_seconds=p95_s,
        min_interval_seconds=min_s,
        max_interval_seconds=max_s,
        business_dates=business_dates,
        dominant_business_date=dominant,
        date_span=_classify_span(list(business_dates)),
        unique_timestamps=tuple(unique_sorted.to_list()),
        source_timezone=str(tzinfo),
    )


# ---------------------------------------------------------------------------
# Filename dates - metadata only, never authoritative
# ---------------------------------------------------------------------------

_FILENAME_DATE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})(?!\d)", "ymd"),
    (r"(?<!\d)(\d{2})[-_](\d{2})[-_](\d{4})(?!\d)", "dmy"),
    (r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", "ymd"),
)


def extract_filename_date(filename: str) -> dt.date | None:
    """Best-effort date from a filename, for mismatch reporting only.

    The result is never used to set a business date.  It exists so the platform
    can *report* that the filename disagrees with the telemetry - which is
    exactly the situation in the known production sample.
    """
    for pattern, order in _FILENAME_DATE_PATTERNS:
        match = re.search(pattern, filename)
        if not match:
            continue
        a, b, c = (int(part) for part in match.groups())
        year, month, day = (a, b, c) if order == "ymd" else (c, b, a)
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return None
