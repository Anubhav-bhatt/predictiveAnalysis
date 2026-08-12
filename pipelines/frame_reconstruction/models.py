"""Phase 1D domain vocabulary and value objects.

The terminology here is load-bearing, because the whole phase exists to keep four
things apart that a naive reading of the source conflates:

``raw row``
    One row exactly as the source file represents it.

``logical position``
    Where a row sits inside a frame - for the known topology, a
    ``(connector_id, smr_id)`` pair such as ``C1/S3``.

``source frame``
    One coherent snapshot of a charger at one event timestamp: the full set of
    logical positions reported together.

``frame_sequence``
    Which frame this is, among several that share the *same* event timestamp.

The rule that motivates all of it:

    Two rows may share (event_time, connector, SMR) and still be genuinely
    different observations. ``drop_duplicates`` on that key would delete real
    telemetry, so this module never does it.

Everything here is a frozen value object with no database or IO dependency, so
the reconstruction algorithm is testable without a session or a file.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "DuplicateClassification",
    "FrameStatus",
    "LogicalPosition",
    "LogicalTelemetryKey",
    "RECONSTRUCTION_VERSION",
    "RawRowRef",
    "ReconstructedFrame",
    "ReconstructionIssueType",
    "TimestampGroup",
    "UNASSIGNED_POSITION",
]

#: Algorithm version stamped onto every persisted frame. Bump it when the
#: reconstruction logic changes semantically, so historical output stays
#: attributable to the code that produced it rather than being silently
#: reinterpreted (section 32).
RECONSTRUCTION_VERSION = "frame-reconstruction-v1"


class FrameStatus(StrEnum):
    """Structural verdict on a reconstructed frame (section 11).

    Structure only. Whether a frame duplicates another is a *separate* dimension -
    see :class:`DuplicateClassification` - because a frame can be both perfectly
    complete and a replay.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SEVERELY_INCOMPLETE = "SEVERELY_INCOMPLETE"
    #: Positions present that the topology does not expect, or internally
    #: contradictory identity fields.
    MALFORMED = "MALFORMED"
    #: Occurrence counts do not admit one coherent frame boundary.
    AMBIGUOUS = "AMBIGUOUS"


class DuplicateClassification(StrEnum):
    """How a frame relates to other frames at the same event timestamp (section 15)."""

    UNIQUE = "UNIQUE"
    #: Every row is byte-identical to a row already seen in this group.
    EXACT_ROW_DUPLICATE = "EXACT_ROW_DUPLICATE"
    #: Whole canonical payload equals an earlier frame's.
    FULL_FRAME_REPLAY = "FULL_FRAME_REPLAY"
    #: A subset of positions matches an earlier frame and nothing contradicts it.
    PARTIAL_FRAME_REPLAY = "PARTIAL_FRAME_REPLAY"
    #: Same timestamp, genuinely different telemetry. The case that must never be
    #: deduplicated away.
    SAME_TIMESTAMP_DISTINCT_FRAME = "SAME_TIMESTAMP_DISTINCT_FRAME"
    AMBIGUOUS = "AMBIGUOUS"


class ReconstructionIssueType(StrEnum):
    """Diagnostics persisted through the existing Phase 1 quality framework."""

    FRAME_INCOMPLETE = "FRAME_INCOMPLETE"
    FRAME_OVERCOMPLETE = "FRAME_OVERCOMPLETE"
    FRAME_MISSING_POSITION = "FRAME_MISSING_POSITION"
    FRAME_UNEXPECTED_POSITION = "FRAME_UNEXPECTED_POSITION"
    AMBIGUOUS_FRAME_BOUNDARY = "AMBIGUOUS_FRAME_BOUNDARY"
    FULL_FRAME_REPLAY = "FULL_FRAME_REPLAY"
    PARTIAL_FRAME_REPLAY = "PARTIAL_FRAME_REPLAY"
    SAME_TIMESTAMP_DISTINCT_FRAME = "SAME_TIMESTAMP_DISTINCT_FRAME"
    INCONSISTENT_TOPOLOGY = "INCONSISTENT_TOPOLOGY"
    ENTITY_ID_MISSING = "ENTITY_ID_MISSING"
    UNASSIGNED_RAW_ROW = "UNASSIGNED_RAW_ROW"


@dataclass(frozen=True, slots=True, order=True)
class LogicalPosition:
    """A row's entity slot inside a frame.

    Identifiers are strings, never ints: the source contract does not guarantee
    numeric connector or SMR ids, and a charger variant using ``GUN-A`` must not
    crash reconstruction.
    """

    connector_id: str
    smr_id: str

    def __str__(self) -> str:
        return f"C{self.connector_id}/S{self.smr_id}"

    @property
    def is_assigned(self) -> bool:
        return bool(self.connector_id) and bool(self.smr_id)


#: Sentinel for rows whose entity identity could not be determined. Such rows are
#: retained and reported, never dropped (section 22).
UNASSIGNED_POSITION = LogicalPosition(connector_id="", smr_id="")


@dataclass(frozen=True, slots=True)
class LogicalTelemetryKey:
    """Full logical identity of one raw row (section 5)."""

    charger_id: str
    event_time: dt.datetime
    position: LogicalPosition

    @property
    def is_assignable(self) -> bool:
        return bool(self.charger_id) and self.position.is_assigned


@dataclass(frozen=True, slots=True)
class RawRowRef:
    """Stable provenance for one raw row (section 4).

    ``source_row_number`` is the row's position in the original file, captured
    before any sort or filter. Nothing downstream relies on a DataFrame index,
    which would silently change meaning after a re-sort.
    """

    telemetry_file_id: object
    source_row_number: int
    position: LogicalPosition
    #: 0-based index of this row among rows sharing the same logical key, in
    #: source order (section 8).
    occurrence_index: int
    row_fingerprint: str
    #: True when the identity fields could not be resolved.
    unassigned: bool = False

    @property
    def is_assigned(self) -> bool:
        return not self.unassigned


@dataclass(frozen=True, slots=True)
class TimestampGroup:
    """Every raw row a charger reported at one event timestamp (section 7)."""

    charger_id: str
    event_time: dt.datetime
    rows: tuple[RawRowRef, ...]

    expected_positions: frozenset[LogicalPosition]
    #: position -> how many rows occupy it.
    occurrences: Mapping[LogicalPosition, int]
    unassigned_rows: tuple[RawRowRef, ...] = ()

    @property
    def raw_row_count(self) -> int:
        return len(self.rows) + len(self.unassigned_rows)

    @property
    def observed_positions(self) -> frozenset[LogicalPosition]:
        return frozenset(self.occurrences)

    @property
    def missing_positions(self) -> frozenset[LogicalPosition]:
        return self.expected_positions - self.observed_positions

    @property
    def unexpected_positions(self) -> frozenset[LogicalPosition]:
        return self.observed_positions - self.expected_positions

    @property
    def max_occurrence(self) -> int:
        """How many frames this group could contain at most."""
        return max(self.occurrences.values(), default=0)

    @property
    def is_evenly_occupied(self) -> bool:
        """True when every observed position appears the same number of times.

        Uneven occupancy is what distinguishes "two clean frames" from "one frame
        plus a partial retransmission" (section 10).
        """
        counts = set(self.occurrences.values())
        return len(counts) <= 1


@dataclass(frozen=True, slots=True)
class ReconstructedFrame:
    """One logical source frame, before persistence."""

    charger_id: str
    event_time: dt.datetime
    #: Deterministic ordinal among frames sharing this event timestamp. Combined
    #: with event_time this is the frame's identity - no fabricated sub-second
    #: timestamps are ever introduced (section 18).
    frame_sequence: int

    rows: tuple[RawRowRef, ...]
    frame_fingerprint: str
    status: FrameStatus
    duplicate_classification: DuplicateClassification

    expected_position_count: int
    observed_position_count: int
    missing_position_count: int
    unexpected_position_count: int

    #: Set when this frame replays another; refers to that frame's sequence
    #: within the same (charger, event_time) group.
    replay_of_sequence: int | None = None

    missing_positions: tuple[LogicalPosition, ...] = ()
    unexpected_positions: tuple[LogicalPosition, ...] = ()

    issues: tuple[ReconstructionIssueType, ...] = ()
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def completeness_percentage(self) -> float:
        if self.expected_position_count <= 0:
            return 0.0
        return round(
            100.0 * self.observed_position_count / self.expected_position_count, 3
        )

    @property
    def source_order_min(self) -> int:
        return min((row.source_row_number for row in self.rows), default=0)

    @property
    def source_order_max(self) -> int:
        return max((row.source_row_number for row in self.rows), default=0)

    @property
    def is_canonical(self) -> bool:
        """Whether Phase 1E should consume this frame by default.

        Replays are excluded - they add no observation - but same-timestamp
        distinct frames are emphatically included.
        """
        return self.duplicate_classification in {
            DuplicateClassification.UNIQUE,
            DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
        }

    @property
    def source_file_ids(self) -> tuple[object, ...]:
        seen: list[object] = []
        for row in self.rows:
            if row.telemetry_file_id not in seen:
                seen.append(row.telemetry_file_id)
        return tuple(seen)


def summarise_statuses(frames: Sequence[ReconstructedFrame]) -> dict[str, int]:
    """Count frames by status - used by CLI output and file metrics."""
    counts = dict.fromkeys((status.value for status in FrameStatus), 0)
    for frame in frames:
        counts[frame.status.value] += 1
    return counts


def summarise_classifications(frames: Sequence[ReconstructedFrame]) -> dict[str, int]:
    counts = dict.fromkeys((kind.value for kind in DuplicateClassification), 0)
    for frame in frames:
        counts[frame.duplicate_classification.value] += 1
    return counts
