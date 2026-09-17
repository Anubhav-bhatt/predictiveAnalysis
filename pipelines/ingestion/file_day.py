"""Split a profiled file into its actual telemetry business dates (section 8).

Phase 1C forbids the convenient assumption that one file equals one business
date.  Files genuinely cross midnight, and the known sample's *filename* date
disagrees with its telemetry.  So this module answers one narrow question:

    for each business date this file really contains, which unique event
    timestamps belong to it?

The answer is expressed as seconds from local midnight in the charger's source
timezone, which is what :class:`TelemetryFileDay` persists.  Everything Phase 1C
computes downstream - coverage, cadence, gaps - is rebuilt from those offsets, so
a late file never forces a re-read of the raw CSV.

Scope note, stated rather than hidden: the profiler reports connector and SMR
identities per *file*, not per date.  For the overwhelmingly common single-day
file the two are identical.  For a genuine multi-day file the same topology is
recorded against each date, which can only ever over-report a date's topology,
never under-report it.  Per-date topology needs a per-date profiling pass and is
deliberately left to a later phase rather than guessed at here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pipelines.profiling.event_time import resolve_timezone
from pipelines.profiling.profiler import FileProfile

__all__ = ["FileDayContribution", "build_file_days", "dominant_identifier"]


@dataclass(frozen=True, slots=True)
class FileDayContribution:
    """One file's telemetry for one business date, ready to persist."""

    charger_id: str
    business_date: dt.date
    source_timezone: str

    first_event_at: dt.datetime | None
    last_event_at: dt.datetime | None
    unique_timestamp_count: int
    row_count: int

    #: Seconds from local midnight, sorted ascending, unique.
    event_second_offsets: tuple[int, ...]

    connectors_seen: tuple[str, ...] = ()
    smrs_seen: tuple[str, ...] = ()

    duplicate_timestamp_count: int = 0
    logical_collision_count: int = 0
    exact_duplicate_row_count: int = 0

    detail: dict[str, object] = field(default_factory=dict)

    def timestamps_utc(self) -> list[dt.datetime]:
        tzinfo = resolve_timezone(self.source_timezone)
        midnight = dt.datetime.combine(self.business_date, dt.time.min, tzinfo=tzinfo)
        return [
            (midnight + dt.timedelta(seconds=offset)).astimezone(dt.UTC)
            for offset in self.event_second_offsets
        ]

    def as_row(self, *, telemetry_file_id: object) -> dict[str, object]:
        """Persistence payload for :class:`TelemetryFileDay`."""
        return {
            "telemetry_file_id": telemetry_file_id,
            "charger_id": self.charger_id,
            "business_date": self.business_date,
            "first_event_at": self.first_event_at,
            "last_event_at": self.last_event_at,
            "unique_timestamp_count": self.unique_timestamp_count,
            "row_count": self.row_count,
            "event_second_offsets": list(self.event_second_offsets),
            "connectors_seen": list(self.connectors_seen),
            "smrs_seen": list(self.smrs_seen),
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "logical_collision_count": self.logical_collision_count,
            "exact_duplicate_row_count": self.exact_duplicate_row_count,
            "source_timezone": self.source_timezone,
        }


def dominant_identifier(counts: Mapping[str, int]) -> str | None:
    """The most frequent identifier value, ties broken deterministically.

    A daily file is expected to carry exactly one charger id.  When it carries
    more, picking the dominant one keeps behaviour defined while the count itself
    is reported as a quality issue rather than silently accepted.
    """
    if not counts:
        return None
    return max(sorted(counts), key=lambda value: (counts[value], value))


def build_file_days(
    profile: FileProfile,
    *,
    charger_id: str,
    source_timezone: str,
) -> tuple[FileDayContribution, ...]:
    """Partition a profiled file's unique timestamps by local business date.

    Returns one contribution per date actually present.  An empty tuple means the
    file had no parsable timestamps at all, which the caller has already treated
    as a quarantine condition.
    """
    analysis = profile.timestamps
    stamps = analysis.unique_timestamps
    if not stamps:
        return ()

    tzinfo = resolve_timezone(source_timezone)

    # Group unique timestamps by the charger's *local* date. A UTC-based split
    # would put IST 05:00 on the previous day for the whole Indian fleet.
    by_date: dict[dt.date, list[dt.datetime]] = {}
    for stamp in stamps:
        aware = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=dt.UTC)
        local = aware.astimezone(tzinfo)
        by_date.setdefault(local.date(), []).append(aware)

    connectors = tuple(sorted(profile.connectors))
    smrs = tuple(sorted(profile.smrs))
    duplicates = profile.duplicates
    multi_day = len(by_date) > 1

    contributions: list[FileDayContribution] = []
    for business_date, day_stamps in sorted(by_date.items()):
        ordered = sorted(set(day_stamps))
        midnight = dt.datetime.combine(business_date, dt.time.min, tzinfo=tzinfo)
        offsets = tuple(int((s.astimezone(tzinfo) - midnight).total_seconds()) for s in ordered)

        share = len(ordered) / len(stamps) if stamps else 0.0
        contributions.append(
            FileDayContribution(
                charger_id=charger_id,
                business_date=business_date,
                source_timezone=source_timezone,
                first_event_at=ordered[0],
                last_event_at=ordered[-1],
                unique_timestamp_count=len(ordered),
                # Raw rows are not labelled per date by the profiler, so they are
                # apportioned by this date's share of unique timestamps. Row
                # counts are reporting context only - never a coverage input
                # (section 11) - so an approximation here is safe and is flagged.
                row_count=int(round(profile.row_count * share)),
                event_second_offsets=offsets,
                connectors_seen=connectors,
                smrs_seen=smrs,
                duplicate_timestamp_count=(
                    duplicates.duplicate_timestamp_count if not multi_day else 0
                ),
                logical_collision_count=(
                    duplicates.logical_collision_groups if not multi_day else 0
                ),
                exact_duplicate_row_count=(duplicates.exact_duplicate_rows if not multi_day else 0),
                detail={
                    "date_span": analysis.date_span.value,
                    "multi_day_file": multi_day,
                    "row_count_is_apportioned": multi_day,
                    "unique_timestamp_share": round(share, 6),
                },
            )
        )
    return tuple(contributions)


def total_unique_timestamps(contributions: Sequence[FileDayContribution]) -> int:
    """Sum of unique timestamps across dates - a consistency check helper."""
    return sum(c.unique_timestamp_count for c in contributions)
