"""Charger-day coverage, cadence and gap evaluation (Phase 1C sections 10-20).

The single most important rule in this module (section 11):

    **Coverage is computed from unique event timestamps, never from raw rows.**

The raw grain is 2 connectors x 4 SMRs = 8 rows per timestamp, and replayed
frames add more rows without adding a single new observation.  Dividing raw rows
by expected raw rows would let a duplicated file report >100% coverage while
actually being half empty.  So every coverage number here derives from the set of
distinct timestamps.

Three coverage dimensions are reported because they answer different questions
(section 12):

``sample_coverage``
    How many of the expected observations exist.  This is the headline number -
    it is the one that cannot be inflated by duplication.

``span_coverage``
    How much of the day lies between the first and last observation.  A file
    running 00:01 to 23:59 has ~100% span coverage even if the middle is empty,
    which is precisely why span alone is not trusted.

``gap_adjusted_coverage``
    Span minus the time lost inside detected gaps.  The reconciliation of the
    two views above.

Multiple files can contribute to one charger-day (section 19); their timestamp
sets are unioned, and timestamps seen in more than one file are counted as
overlap (section 20) rather than silently deduplicated away.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from backend.app.core.config import FleetSettings
from backend.app.models.enums import CompletenessStatus, GapSeverity

__all__ = [
    "CoverageEvaluation",
    "CoveragePolicy",
    "FileContribution",
    "GapCandidate",
    "evaluate_charger_day",
]


@dataclass(frozen=True, slots=True)
class CoveragePolicy:
    """All thresholds, resolved once.  Nothing below reads settings directly."""

    expected_interval_seconds: int
    day_seconds: int
    gap_threshold_multiplier: float
    gap_minor_seconds: int
    gap_moderate_seconds: int
    gap_major_seconds: int
    gap_critical_seconds: int
    complete_min_pct: float
    partial_min_pct: float
    late_grace_hours: int
    cadence_deviation_tolerance: float
    source_timezone: str = "UTC"

    @classmethod
    def from_settings(
        cls,
        settings: FleetSettings,
        *,
        expected_interval_seconds: int | None = None,
        source_timezone: str | None = None,
    ) -> CoveragePolicy:
        """Build a policy, honouring the charger-level cadence override.

        Precedence for cadence (section 10): charger > model > schema > global.
        The caller resolves the first three and passes the winner in.
        """
        return cls(
            expected_interval_seconds=(
                expected_interval_seconds or settings.default_sampling_interval_seconds
            ),
            day_seconds=settings.day_seconds,
            gap_threshold_multiplier=settings.gap_threshold_multiplier,
            gap_minor_seconds=settings.gap_minor_seconds,
            gap_moderate_seconds=settings.gap_moderate_seconds,
            gap_major_seconds=settings.gap_major_seconds,
            gap_critical_seconds=settings.gap_critical_seconds,
            complete_min_pct=settings.completeness_complete_min_pct,
            partial_min_pct=settings.completeness_partial_min_pct,
            late_grace_hours=settings.late_arrival_grace_hours,
            cadence_deviation_tolerance=settings.cadence_deviation_tolerance,
            source_timezone=source_timezone or settings.default_source_timezone,
        )

    @property
    def gap_threshold_seconds(self) -> float:
        return self.expected_interval_seconds * self.gap_threshold_multiplier

    def classify_gap(self, duration_seconds: float) -> GapSeverity:
        if duration_seconds >= self.gap_critical_seconds:
            return GapSeverity.CRITICAL
        if duration_seconds >= self.gap_major_seconds:
            return GapSeverity.MAJOR
        if duration_seconds >= self.gap_moderate_seconds:
            return GapSeverity.MODERATE
        return GapSeverity.MINOR

    def classify_completeness(self, coverage_pct: float, *, has_data: bool) -> CompletenessStatus:
        if not has_data:
            return CompletenessStatus.NO_DATA
        if coverage_pct >= self.complete_min_pct:
            return CompletenessStatus.COMPLETE
        if coverage_pct >= self.partial_min_pct:
            return CompletenessStatus.PARTIAL
        return CompletenessStatus.SEVERELY_INCOMPLETE


@dataclass(frozen=True, slots=True)
class FileContribution:
    """One file's contribution to a charger-day."""

    telemetry_file_id: UUID | None
    timestamps: Sequence[dt.datetime]
    received_at: dt.datetime | None = None
    connectors: frozenset[str] = frozenset()
    smrs: frozenset[str] = frozenset()
    quality_score: Decimal | None = None
    exact_duplicate_rows: int = 0
    logical_collision_groups: int = 0
    duplicate_timestamp_count: int = 0


@dataclass(frozen=True, slots=True)
class GapCandidate:
    """An inter-sample interval long enough to count as missing telemetry."""

    start_event_at: dt.datetime
    end_event_at: dt.datetime
    duration_seconds: int
    expected_interval_seconds: int
    estimated_missing_samples: int
    severity: GapSeverity


@dataclass(frozen=True, slots=True)
class CoverageEvaluation:
    """Complete, explainable coverage assessment for one charger-day."""

    charger_id: str
    business_date: dt.date

    file_count: int
    primary_telemetry_file_id: UUID | None

    first_event_at: dt.datetime | None
    last_event_at: dt.datetime | None
    unique_timestamp_count: int
    expected_timestamp_count: int

    expected_sampling_interval_seconds: int
    observed_median_interval_seconds: float | None
    observed_p95_interval_seconds: float | None
    observed_min_interval_seconds: float | None
    observed_max_interval_seconds: float | None

    coverage_seconds: int
    expected_coverage_seconds: int
    span_coverage_percentage: float
    sample_coverage_percentage: float
    gap_adjusted_coverage_percentage: float
    coverage_percentage: float

    gaps: tuple[GapCandidate, ...]
    gap_count: int
    largest_gap_seconds: int
    total_gap_seconds: int

    #: Time before the first and after the last observation. Reported
    #: separately because these are *not* inter-sample gaps.
    leading_missing_seconds: int
    trailing_missing_seconds: int

    connectors_detected: frozenset[str]
    smrs_detected: frozenset[str]

    duplicate_timestamp_count: int
    logical_collision_count: int
    overlapping_timestamp_count: int
    duplicate_file_count: int

    completeness_status: CompletenessStatus
    cadence_is_abnormal: bool
    first_received_at: dt.datetime | None
    quality_score: Decimal | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return self.unique_timestamp_count > 0


def _day_bounds(business_date: dt.date, timezone: str) -> tuple[dt.datetime, dt.datetime]:
    """UTC bounds of a local business date."""
    from pipelines.profiling.event_time import resolve_timezone

    tzinfo = resolve_timezone(timezone)
    start_local = dt.datetime.combine(business_date, dt.time.min, tzinfo=tzinfo)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.UTC), end_local.astimezone(dt.UTC)


def _interval_stats(
    timestamps: Sequence[dt.datetime],
) -> tuple[float | None, float | None, float | None, float | None]:
    if len(timestamps) < 2:
        return (None, None, None, None)
    deltas = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
    ]
    positive = [d for d in deltas if d > 0]
    if not positive:
        return (None, None, None, None)
    ordered = sorted(positive)
    p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return (
        statistics.median(positive),
        ordered[p95_index],
        ordered[0],
        ordered[-1],
    )


def _detect_gaps(
    timestamps: Sequence[dt.datetime], policy: CoveragePolicy
) -> tuple[GapCandidate, ...]:
    """Inter-sample gaps only.

    Missing telemetry before the first or after the last observation is not a
    gap between samples; it is reported as leading/trailing missing time so the
    two conditions stay distinguishable.
    """
    if len(timestamps) < 2:
        return ()

    threshold = policy.gap_threshold_seconds
    interval = policy.expected_interval_seconds
    gaps: list[GapCandidate] = []

    for earlier, later in zip(timestamps, timestamps[1:], strict=False):
        duration = (later - earlier).total_seconds()
        if duration <= threshold:
            continue
        missing = max(0, int(duration // interval) - 1) if interval > 0 else 0
        gaps.append(
            GapCandidate(
                start_event_at=earlier,
                end_event_at=later,
                duration_seconds=int(duration),
                expected_interval_seconds=interval,
                estimated_missing_samples=missing,
                severity=policy.classify_gap(duration),
            )
        )
    return tuple(gaps)


def evaluate_charger_day(
    *,
    charger_id: str,
    business_date: dt.date,
    contributions: Iterable[FileContribution],
    policy: CoveragePolicy,
) -> CoverageEvaluation:
    """Assess one charger's telemetry delivery for one business date."""
    items = list(contributions)
    day_start, day_end = _day_bounds(business_date, policy.source_timezone)

    # Union of unique timestamps across every contributing file, restricted to
    # this business date. Overlap is counted, not discarded (section 20).
    seen: dict[dt.datetime, int] = {}
    connectors: set[str] = set()
    smrs: set[str] = set()
    duplicate_ts = 0
    collisions = 0
    duplicate_files = 0
    received_times: list[dt.datetime] = []
    scores: list[Decimal] = []

    for item in items:
        connectors |= set(item.connectors)
        smrs |= set(item.smrs)
        duplicate_ts += item.duplicate_timestamp_count
        collisions += item.logical_collision_groups
        if item.exact_duplicate_rows > 0:
            duplicate_files += 1
        if item.received_at is not None:
            received_times.append(item.received_at)
        if item.quality_score is not None:
            scores.append(item.quality_score)

        for stamp in {t for t in item.timestamps if day_start <= t < day_end}:
            seen[stamp] = seen.get(stamp, 0) + 1

    overlapping = sum(1 for count in seen.values() if count > 1)
    timestamps = sorted(seen)

    expected_count = max(1, policy.day_seconds // max(policy.expected_interval_seconds, 1))
    unique_count = len(timestamps)

    first_event = timestamps[0] if timestamps else None
    last_event = timestamps[-1] if timestamps else None

    span_seconds = (
        int((last_event - first_event).total_seconds())
        if first_event is not None and last_event is not None
        else 0
    )
    gaps = _detect_gaps(timestamps, policy)
    total_gap = sum(g.duration_seconds for g in gaps)
    largest_gap = max((g.duration_seconds for g in gaps), default=0)

    leading = int((first_event - day_start).total_seconds()) if first_event else 0
    trailing = int((day_end - last_event).total_seconds()) if last_event else 0

    # Sample coverage is the headline: unique observations against expected.
    sample_coverage = min(100.0, 100.0 * unique_count / expected_count) if expected_count else 0.0
    span_coverage = min(100.0, 100.0 * span_seconds / policy.day_seconds)
    gap_adjusted = min(100.0, max(0.0, 100.0 * (span_seconds - total_gap) / policy.day_seconds))

    median_s, p95_s, min_s, max_s = _interval_stats(timestamps)

    tolerance = policy.cadence_deviation_tolerance
    expected_interval = policy.expected_interval_seconds
    cadence_abnormal = bool(
        median_s is not None
        and expected_interval > 0
        and (
            median_s < expected_interval * (1 - tolerance)
            or median_s > expected_interval * (1 + tolerance)
        )
    )

    return CoverageEvaluation(
        charger_id=charger_id,
        business_date=business_date,
        file_count=len(items),
        primary_telemetry_file_id=_primary_file(items),
        first_event_at=first_event,
        last_event_at=last_event,
        unique_timestamp_count=unique_count,
        expected_timestamp_count=expected_count,
        expected_sampling_interval_seconds=expected_interval,
        observed_median_interval_seconds=median_s,
        observed_p95_interval_seconds=p95_s,
        observed_min_interval_seconds=min_s,
        observed_max_interval_seconds=max_s,
        coverage_seconds=span_seconds,
        expected_coverage_seconds=policy.day_seconds,
        span_coverage_percentage=round(span_coverage, 3),
        sample_coverage_percentage=round(sample_coverage, 3),
        gap_adjusted_coverage_percentage=round(gap_adjusted, 3),
        coverage_percentage=round(sample_coverage, 3),
        gaps=gaps,
        gap_count=len(gaps),
        largest_gap_seconds=largest_gap,
        total_gap_seconds=total_gap,
        leading_missing_seconds=max(0, leading),
        trailing_missing_seconds=max(0, trailing),
        connectors_detected=frozenset(connectors),
        smrs_detected=frozenset(smrs),
        duplicate_timestamp_count=duplicate_ts,
        logical_collision_count=collisions,
        overlapping_timestamp_count=overlapping,
        duplicate_file_count=duplicate_files,
        completeness_status=policy.classify_completeness(
            sample_coverage, has_data=unique_count > 0
        ),
        cadence_is_abnormal=cadence_abnormal,
        first_received_at=min(received_times) if received_times else None,
        quality_score=(
            Decimal(sum(scores) / len(scores)).quantize(Decimal("0.01")) if scores else None
        ),
        detail={
            "day_start_utc": day_start.isoformat(),
            "day_end_utc": day_end.isoformat(),
            "source_timezone": policy.source_timezone,
            "gap_threshold_seconds": policy.gap_threshold_seconds,
        },
    )


def _primary_file(items: Sequence[FileContribution]) -> UUID | None:
    """The file contributing the most distinct timestamps to the day."""
    best: FileContribution | None = None
    for item in items:
        if item.telemetry_file_id is None:
            continue
        if best is None or len(set(item.timestamps)) > len(set(best.timestamps)):
            best = item
    return best.telemetry_file_id if best else None


def is_late(
    *,
    business_date: dt.date,
    first_received_at: dt.datetime | None,
    policy: CoveragePolicy,
) -> tuple[bool, int | None]:
    """Late arrival test (section 17).

    Lateness is measured from *receipt* time against the business date's cutoff,
    never from when the platform happened to process the file.
    """
    if first_received_at is None:
        return (False, None)
    _, day_end = _day_bounds(business_date, policy.source_timezone)
    cutoff = day_end + dt.timedelta(hours=policy.late_grace_hours)
    if first_received_at <= cutoff:
        return (False, 0)
    return (True, int((first_received_at - cutoff).total_seconds()))
