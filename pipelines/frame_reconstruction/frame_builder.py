"""Frame candidate construction (Phase 1D sections 9, 10, 11).

Given a timestamp group, decide how many source frames it contains and which rows
belong to each.

The algorithm is occurrence-slicing: frame *k* takes occurrence *k* of every logical
position. For the clean multi-frame case - every position present exactly N times -
that yields N complete frames, which is what a genuine retransmission of a whole
frame looks like.

Two guards keep it honest:

**Occurrence count alone is not proof of a frame boundary** (section 9). Even
occupancy is treated as coherent; uneven occupancy is not silently forced into
whole frames.

**Missing observations are never manufactured** (section 10). When
``C1/S1..S4`` appear twice but ``C2/S1..S4`` appear once, the result is one
COMPLETE frame plus one PARTIAL frame holding only the positions that genuinely
occurred a second time - not two complete frames with four invented rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipelines.frame_reconstruction.models import (
    FrameStatus,
    LogicalPosition,
    RawRowRef,
    TimestampGroup,
)
from pipelines.frame_reconstruction.timestamp_groups import GroupOccupancy, describe_occupancy

__all__ = ["FrameCandidate", "build_frame_candidates"]


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    """One frame's rows, before fingerprinting and duplicate classification."""

    sequence: int
    #: position -> the row occupying it in this frame.
    rows_by_position: Mapping[LogicalPosition, RawRowRef]
    expected_positions: frozenset[LogicalPosition]
    status: FrameStatus
    #: True when this candidate holds fewer positions than the frame before it,
    #: i.e. it looks like a fragment rather than a whole retransmission.
    is_fragment: bool = False
    note: str | None = None

    @property
    def rows(self) -> tuple[RawRowRef, ...]:
        return tuple(sorted(self.rows_by_position.values(), key=lambda row: row.source_row_number))

    @property
    def observed_positions(self) -> frozenset[LogicalPosition]:
        return frozenset(self.rows_by_position)

    @property
    def missing_positions(self) -> tuple[LogicalPosition, ...]:
        return tuple(sorted(self.expected_positions - self.observed_positions))

    @property
    def unexpected_positions(self) -> tuple[LogicalPosition, ...]:
        return tuple(sorted(self.observed_positions - self.expected_positions))


def _classify_status(
    *,
    observed: int,
    expected: int,
    unexpected: int,
    severely_incomplete_below_pct: float,
) -> FrameStatus:
    """Structural verdict for one candidate.

    Unexpected positions dominate: a frame containing a position the topology does
    not know about is MALFORMED regardless of how complete it otherwise looks,
    because its shape contradicts the declared configuration (section 21).
    """
    if unexpected > 0:
        return FrameStatus.MALFORMED
    if expected <= 0:
        # Topology unresolved - completeness is unknowable, so do not assert it.
        return FrameStatus.AMBIGUOUS
    if observed >= expected:
        return FrameStatus.COMPLETE
    share = 100.0 * observed / expected
    if share < severely_incomplete_below_pct:
        return FrameStatus.SEVERELY_INCOMPLETE
    return FrameStatus.PARTIAL


def build_frame_candidates(
    group: TimestampGroup,
    *,
    severely_incomplete_below_pct: float = 50.0,
    max_frames_per_timestamp: int = 64,
) -> tuple[list[FrameCandidate], GroupOccupancy]:
    """Slice a timestamp group into frame candidates.

    ``max_frames_per_timestamp`` is a safety valve: a corrupt file claiming
    thousands of occurrences at one timestamp must not be able to generate
    unbounded frames. Groups exceeding it are marked AMBIGUOUS rather than
    expanded.
    """
    occupancy = describe_occupancy(group)

    if not group.rows:
        # Nothing assignable here - the group exists only to carry its unassigned
        # rows forward for reporting.
        return [], occupancy

    # Bucket rows by position, each bucket already in source order because the key
    # builder assigned occurrence_index in that order.
    buckets: dict[LogicalPosition, list[RawRowRef]] = {}
    for row in sorted(group.rows, key=lambda r: (r.occurrence_index, r.source_row_number)):
        buckets.setdefault(row.position, []).append(row)

    frame_count = occupancy.implied_frame_count

    if frame_count > max_frames_per_timestamp:
        merged = {position: rows[0] for position, rows in buckets.items()}
        return (
            [
                FrameCandidate(
                    sequence=0,
                    rows_by_position=merged,
                    expected_positions=group.expected_positions,
                    status=FrameStatus.AMBIGUOUS,
                    note=(
                        f"{frame_count} occurrences at one event timestamp exceeds the "
                        f"configured maximum of {max_frames_per_timestamp}; frame "
                        f"boundaries cannot be determined safely"
                    ),
                )
            ],
            occupancy,
        )

    candidates: list[FrameCandidate] = []
    previous_size: int | None = None

    for sequence in range(frame_count):
        rows_by_position = {
            position: rows[sequence] for position, rows in buckets.items() if sequence < len(rows)
        }
        if not rows_by_position:
            continue

        observed = len(rows_by_position)
        unexpected = len(frozenset(rows_by_position) - group.expected_positions)
        status = _classify_status(
            observed=observed,
            expected=len(group.expected_positions),
            unexpected=unexpected,
            severely_incomplete_below_pct=severely_incomplete_below_pct,
        )

        # A later candidate smaller than its predecessor is a fragment: the source
        # repeated part of a frame, not all of it. Recorded so the replay detector
        # can distinguish a partial retransmission from a genuinely short frame.
        is_fragment = previous_size is not None and observed < previous_size
        note: str | None = None
        if is_fragment:
            note = (
                f"holds {observed} of the {previous_size} positions present in the "
                f"preceding frame at this timestamp; treated as a fragment rather "
                f"than a whole frame"
            )
        elif not occupancy.is_even and sequence == 0 and frame_count > 1:
            note = "occurrence counts are uneven across positions at this timestamp"

        candidates.append(
            FrameCandidate(
                sequence=sequence,
                rows_by_position=rows_by_position,
                expected_positions=group.expected_positions,
                status=status,
                is_fragment=is_fragment,
                note=note,
            )
        )
        previous_size = max(previous_size or 0, observed) if sequence == 0 else previous_size
        if sequence == 0:
            previous_size = observed

    return candidates, occupancy


def total_rows_assigned(candidates: Sequence[FrameCandidate]) -> int:
    return sum(len(candidate.rows_by_position) for candidate in candidates)
