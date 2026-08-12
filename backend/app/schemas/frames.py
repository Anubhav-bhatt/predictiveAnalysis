"""Phase 1D reconstruction response models (sections 45-48).

Two safety rules are enforced by construction:

* **No raw telemetry payload.** A frame response carries identity, structure,
  fingerprints and provenance - never the 449 source values. Bronze stays the only
  place those live, and an API that echoed them would become an uncontrolled export
  path (section 69).
* **No internal paths.** ``storage_reference`` never appears; files are identified
  by id and original filename only.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backend.app.models.enums import DuplicateClassification, FileStatus, FrameStatus

__all__ = [
    "CollisionGroup",
    "FrameDetail",
    "FrameDiff",
    "FrameRowRef",
    "FrameSourceRef",
    "FrameSummaryRow",
    "ReconstructionSummary",
]


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ReconstructionSummary(_Base):
    """Per-file reconstruction outcome (section 45)."""

    telemetry_file_id: UUID
    original_filename: str
    reconstruction_version: str | None = None

    raw_rows: int | None = None
    unique_timestamps: int
    expected_positions_per_frame: int

    frames_reconstructed: int
    canonical_frames: int
    complete_frames: int
    partial_frames: int
    severely_incomplete_frames: int
    malformed_frames: int
    ambiguous_frames: int

    full_replays: int
    partial_replays: int
    same_timestamp_distinct_frames: int
    collision_timestamps: int
    unassigned_rows: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def frame_completeness_percentage(self) -> float:
        """Share of frames that were structurally complete. A data measure."""
        if self.frames_reconstructed <= 0:
            return 0.0
        return round(100.0 * self.complete_frames / self.frames_reconstructed, 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def replay_rate(self) -> float:
        if self.frames_reconstructed <= 0:
            return 0.0
        replays = self.full_replays + self.partial_replays
        return round(100.0 * replays / self.frames_reconstructed, 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rows_per_unique_timestamp(self) -> float | None:
        """The raw-grain multiplier, made explicit.

        ~8 for the known topology. Surfaced so a consumer cannot mistake raw rows
        for observations.
        """
        if not self.raw_rows or self.unique_timestamps <= 0:
            return None
        return round(self.raw_rows / self.unique_timestamps, 3)


class FrameSummaryRow(_Base):
    """One frame in a list (section 46)."""

    id: UUID
    charger_id: str
    event_time: dt.datetime
    business_date: dt.date
    frame_sequence: int

    frame_status: FrameStatus
    duplicate_classification: DuplicateClassification
    frame_fingerprint: str
    replay_of_frame_id: UUID | None = None

    expected_position_count: int
    observed_position_count: int
    missing_position_count: int
    unexpected_position_count: int
    completeness_percentage: Decimal | None = None

    source_order_min: int | None = None
    source_order_max: int | None = None
    reconstruction_version: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_canonical(self) -> bool:
        """Whether Phase 1E consumes this frame by default."""
        return self.duplicate_classification in {
            DuplicateClassification.UNIQUE,
            DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
        }

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fingerprint_short(self) -> str:
        """First 12 hex chars - enough to compare by eye in a table."""
        return self.frame_fingerprint[:12]


class FrameSourceRef(_Base):
    """A file that contributed rows to a frame. No storage paths."""

    telemetry_file_id: UUID
    original_filename: str | None = None
    status: FileStatus | None = None
    received_at: dt.datetime | None = None
    first_source_row: int
    last_source_row: int
    row_count: int
    source_occurrence: int
    is_primary_source: bool


class FrameRowRef(_Base):
    """Provenance for one source row. Identity and fingerprint only."""

    telemetry_file_id: UUID
    source_row_number: int
    connector_id: str | None = None
    smr_id: str | None = None
    logical_position: str | None = None
    occurrence_index: int
    row_fingerprint: str
    unassigned: bool


class FrameDetail(_Base):
    """One frame with structure, provenance and diagnostics (section 47)."""

    frame: FrameSummaryRow
    missing_positions: list[str] = Field(default_factory=list)
    unexpected_positions: list[str] = Field(default_factory=list)
    observed_positions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    sources: list[FrameSourceRef] = Field(default_factory=list)
    rows: list[FrameRowRef] = Field(default_factory=list)

    #: Frames that replay this one, when it is canonical (section 52).
    replays: list[FrameSummaryRow] = Field(default_factory=list)
    #: Other frames sharing this event timestamp.
    siblings: list[FrameSummaryRow] = Field(default_factory=list)

    detail: dict[str, object] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def replay_count(self) -> int:
        return len(self.replays)


class CollisionGroup(_Base):
    """Every frame at one event timestamp (section 50)."""

    charger_id: str
    event_time: dt.datetime
    business_date: dt.date
    frame_count: int
    canonical_count: int
    frames: list[FrameSummaryRow] = Field(default_factory=list)


class FrameFieldDifference(_Base):
    """One logical position whose payload differs between two frames."""

    logical_position: str
    left_row_fingerprint: str | None = None
    right_row_fingerprint: str | None = None
    differs: bool


class FrameDiff(_Base):
    """Structural comparison of two frames (section 48).

    Compares canonical *fingerprints* per logical position, so it reports which
    positions changed without exposing the underlying telemetry values. Database
    metadata is never part of the comparison.
    """

    left: FrameSummaryRow
    right: FrameSummaryRow
    same_event_time: bool
    identical_payload: bool

    differing_positions: list[str] = Field(default_factory=list)
    matching_positions: list[str] = Field(default_factory=list)
    only_in_left: list[str] = Field(default_factory=list)
    only_in_right: list[str] = Field(default_factory=list)
    positions: list[FrameFieldDifference] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def differing_position_count(self) -> int:
        return len(self.differing_positions)
