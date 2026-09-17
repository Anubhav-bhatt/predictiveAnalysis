"""Reconstruction metrics (Phase 1D sections 38, 39).

Two scopes, deliberately separate:

*File scope* answers "what did reconstruction make of this file?".
*Charger-day scope* answers "what do we now know about this charger's day?" and
complements - never replaces - the Phase 1C coverage numbers.

Naming discipline: ``frame_completeness_percentage`` is a **data** measure. Nothing
here is a charger health score, and nothing should be renamed to imply otherwise.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from pipelines.frame_reconstruction.models import (
    DuplicateClassification,
    FrameStatus,
    ReconstructedFrame,
)

__all__ = ["ChargerDayFrameMetrics", "FileReconstructionMetrics", "build_file_metrics"]


@dataclass(slots=True)
class FileReconstructionMetrics:
    """Per-file reconstruction outcome."""

    telemetry_file_id: str | None = None
    reconstruction_version: str = ""

    raw_rows: int = 0
    unique_timestamps: int = 0
    expected_positions_per_frame: int = 0
    topology_basis: str = ""

    frames_reconstructed: int = 0
    complete_frames: int = 0
    partial_frames: int = 0
    severely_incomplete_frames: int = 0
    malformed_frames: int = 0
    ambiguous_frames: int = 0

    canonical_frames: int = 0
    full_frame_replays: int = 0
    partial_frame_replays: int = 0
    same_timestamp_distinct_frames: int = 0
    exact_duplicate_rows: int = 0

    collision_timestamps: int = 0
    rows_assigned: int = 0
    rows_unassigned: int = 0

    duration_ms: int = 0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def frame_completeness_percentage(self) -> float:
        """Share of reconstructed frames that were structurally complete."""
        if self.frames_reconstructed <= 0:
            return 0.0
        return round(100.0 * self.complete_frames / self.frames_reconstructed, 3)

    @property
    def replay_rate(self) -> float:
        """Share of frames that added no new observation."""
        if self.frames_reconstructed <= 0:
            return 0.0
        replays = self.full_frame_replays + self.partial_frame_replays
        return round(100.0 * replays / self.frames_reconstructed, 3)

    def render(self) -> str:
        """Operator-facing CLI summary (section 42)."""
        return "\n".join(
            [
                f"Raw rows                       {self.raw_rows:>10,}",
                f"Unique timestamps              {self.unique_timestamps:>10,}",
                f"Expected positions/frame       {self.expected_positions_per_frame:>10}"
                f"   ({self.topology_basis})",
                "",
                f"Frames reconstructed           {self.frames_reconstructed:>10,}",
                f"  complete                     {self.complete_frames:>10,}",
                f"  partial                      {self.partial_frames:>10,}",
                f"  severely incomplete          {self.severely_incomplete_frames:>10,}",
                f"  malformed                    {self.malformed_frames:>10,}",
                f"  ambiguous                    {self.ambiguous_frames:>10,}",
                "",
                f"Canonical frames               {self.canonical_frames:>10,}",
                f"Full frame replays             {self.full_frame_replays:>10,}",
                f"Partial frame replays          {self.partial_frame_replays:>10,}",
                f"Same-timestamp distinct        {self.same_timestamp_distinct_frames:>10,}",
                f"Collision timestamps           {self.collision_timestamps:>10,}",
                f"Exact duplicate rows           {self.exact_duplicate_rows:>10,}",
                "",
                f"Rows assigned                  {self.rows_assigned:>10,}",
                f"Rows unassigned                {self.rows_unassigned:>10,}",
                "",
                f"Frame completeness             {self.frame_completeness_percentage:>9.2f}%",
                f"Replay rate                    {self.replay_rate:>9.2f}%",
                f"Duration                       {self.duration_ms:>10,} ms",
            ]
        )


@dataclass(slots=True)
class ChargerDayFrameMetrics:
    """Frame-level view of one charger-day, complementing Phase 1C coverage."""

    charger_id: str
    business_date: dt.date

    canonical_frame_count: int = 0
    replay_frame_count: int = 0
    collision_timestamp_count: int = 0
    partial_frame_count: int = 0
    ambiguous_frame_count: int = 0
    unassigned_row_count: int = 0
    frames_total: int = 0

    issues: list[str] = field(default_factory=list)

    @property
    def frame_completeness_percentage(self) -> float:
        """Data-quality measure. Explicitly not a charger health score."""
        if self.frames_total <= 0:
            return 0.0
        complete = self.frames_total - self.partial_frame_count - self.ambiguous_frame_count
        return round(100.0 * max(complete, 0) / self.frames_total, 3)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["business_date"] = self.business_date.isoformat()
        payload["frame_completeness_percentage"] = self.frame_completeness_percentage
        return payload


def build_file_metrics(
    frames: Sequence[ReconstructedFrame],
    *,
    telemetry_file_id: str | None,
    reconstruction_version: str,
    raw_rows: int,
    unique_timestamps: int,
    expected_positions_per_frame: int,
    topology_basis: str,
    rows_assigned: int,
    rows_unassigned: int,
    exact_duplicate_rows: int,
    duration_ms: int,
) -> FileReconstructionMetrics:
    """Aggregate frames into the per-file metric set."""
    metrics = FileReconstructionMetrics(
        telemetry_file_id=telemetry_file_id,
        reconstruction_version=reconstruction_version,
        raw_rows=raw_rows,
        unique_timestamps=unique_timestamps,
        expected_positions_per_frame=expected_positions_per_frame,
        topology_basis=topology_basis,
        frames_reconstructed=len(frames),
        rows_assigned=rows_assigned,
        rows_unassigned=rows_unassigned,
        exact_duplicate_rows=exact_duplicate_rows,
        duration_ms=duration_ms,
    )

    status_field = {
        FrameStatus.COMPLETE: "complete_frames",
        FrameStatus.PARTIAL: "partial_frames",
        FrameStatus.SEVERELY_INCOMPLETE: "severely_incomplete_frames",
        FrameStatus.MALFORMED: "malformed_frames",
        FrameStatus.AMBIGUOUS: "ambiguous_frames",
    }
    classification_field = {
        DuplicateClassification.FULL_FRAME_REPLAY: "full_frame_replays",
        DuplicateClassification.PARTIAL_FRAME_REPLAY: "partial_frame_replays",
        DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME: ("same_timestamp_distinct_frames"),
    }

    collision_timestamps: set[dt.datetime] = set()
    for frame in frames:
        setattr(
            metrics,
            status_field[frame.status],
            getattr(metrics, status_field[frame.status]) + 1,
        )
        target = classification_field.get(frame.duplicate_classification)
        if target:
            setattr(metrics, target, getattr(metrics, target) + 1)
        if frame.is_canonical:
            metrics.canonical_frames += 1
        if frame.duplicate_classification is (
            DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME
        ):
            collision_timestamps.add(frame.event_time)

    metrics.collision_timestamps = len(collision_timestamps)
    return metrics
