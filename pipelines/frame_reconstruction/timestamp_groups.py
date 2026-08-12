"""Timestamp grouping and occupancy analysis (Phase 1D section 7).

Groups keyed rows by ``(charger_id, event_time)`` and describes each group's
occupancy against the expected topology, which is what the frame builder needs to
decide how many frames a group can coherently contain.

Grouping is by **event time**, never by filename date or receipt time - the same
rule Phase 1C established for business dates.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from pipelines.frame_reconstruction.models import (
    LogicalPosition,
    RawRowRef,
    TimestampGroup,
)
from pipelines.frame_reconstruction.topology import FrameTopology

__all__ = ["GroupOccupancy", "build_timestamp_groups", "describe_occupancy"]


@dataclass(frozen=True, slots=True)
class GroupOccupancy:
    """How a timestamp group's rows sit against the expected topology."""

    raw_row_count: int
    expected_position_count: int
    observed_position_count: int
    missing_positions: tuple[LogicalPosition, ...]
    unexpected_positions: tuple[LogicalPosition, ...]
    #: position -> occurrence count.
    occurrences: Mapping[LogicalPosition, int]
    max_occurrence: int
    min_occurrence: int
    is_even: bool

    @property
    def implied_frame_count(self) -> int:
        """Upper bound on frames in this group.

        The deepest-occupied position sets the bound: if some position appears
        three times, at least three frames touched this timestamp, even when other
        positions appear fewer times.
        """
        return max(self.max_occurrence, 1)

    @property
    def looks_like_clean_multiframe(self) -> bool:
        """True when the group divides evenly into whole frames.

        Even occupancy across every expected position is the signal that a group
        contains N complete frames rather than one frame plus retransmitted
        fragments.
        """
        return self.is_even and self.max_occurrence > 1 and not self.missing_positions


def build_timestamp_groups(
    *,
    rows_by_timestamp: Mapping[tuple[str, dt.datetime], Sequence[RawRowRef]],
    unassigned_by_timestamp: Mapping[tuple[str, dt.datetime], Sequence[RawRowRef]],
    topology: FrameTopology,
) -> list[TimestampGroup]:
    """Assemble groups in chronological order.

    Timestamps that contain *only* unassigned rows still produce a group, so those
    rows remain visible and reportable instead of disappearing because no frame
    could be built for them.
    """
    keys = sorted(set(rows_by_timestamp) | set(unassigned_by_timestamp), key=lambda k: (k[1], k[0]))
    groups: list[TimestampGroup] = []

    for charger_id, event_time in keys:
        rows = tuple(rows_by_timestamp.get((charger_id, event_time), ()))
        unassigned = tuple(unassigned_by_timestamp.get((charger_id, event_time), ()))

        occurrences: dict[LogicalPosition, int] = {}
        for row in rows:
            occurrences[row.position] = occurrences.get(row.position, 0) + 1

        groups.append(
            TimestampGroup(
                charger_id=charger_id,
                event_time=event_time,
                rows=rows,
                expected_positions=topology.positions,
                occurrences=occurrences,
                unassigned_rows=unassigned,
            )
        )
    return groups


def describe_occupancy(group: TimestampGroup) -> GroupOccupancy:
    counts = list(group.occurrences.values())
    return GroupOccupancy(
        raw_row_count=group.raw_row_count,
        expected_position_count=len(group.expected_positions),
        observed_position_count=len(group.observed_positions),
        missing_positions=tuple(sorted(group.missing_positions)),
        unexpected_positions=tuple(sorted(group.unexpected_positions)),
        occurrences=dict(group.occurrences),
        max_occurrence=max(counts, default=0),
        min_occurrence=min(counts, default=0),
        is_even=group.is_evenly_occupied,
    )


def iter_groups_by_charger(
    groups: Sequence[TimestampGroup],
) -> Iterator[tuple[str, list[TimestampGroup]]]:
    """Yield (charger_id, chronological groups) so reconstruction stays per charger."""
    by_charger: dict[str, list[TimestampGroup]] = {}
    for group in groups:
        by_charger.setdefault(group.charger_id, []).append(group)
    for charger_id in sorted(by_charger):
        yield charger_id, sorted(by_charger[charger_id], key=lambda g: g.event_time)
