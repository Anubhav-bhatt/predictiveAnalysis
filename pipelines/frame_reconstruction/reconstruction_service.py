"""Pure frame-reconstruction orchestration (Phase 1D section 43).

Runs the whole algorithm over an already-profiled file and returns frames plus
metrics. It performs **no IO and touches no database** - the caller supplies the
DataFrame and parsed event times, and persistence is the backend service's job.
That split is what lets every reconstruction rule be tested without a session.

Failure isolation (section 35): one malformed timestamp group is recorded and
skipped; it never aborts the other ~780 groups in a 16.5 MB charger-day.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import polars as pl

from backend.app.core.logging import get_logger
from pipelines.frame_reconstruction.canonical_serializer import CanonicalSerializer
from pipelines.frame_reconstruction.diagnostics import (
    FileReconstructionMetrics,
    build_file_metrics,
)
from pipelines.frame_reconstruction.frame_builder import build_frame_candidates
from pipelines.frame_reconstruction.logical_keys import LogicalKeyBuilder
from pipelines.frame_reconstruction.models import (
    RECONSTRUCTION_VERSION,
    DuplicateClassification,
    FrameStatus,
    LogicalPosition,
    RawRowRef,
    ReconstructedFrame,
    ReconstructionIssueType,
)
from pipelines.frame_reconstruction.replay_detector import classify_group
from pipelines.frame_reconstruction.timestamp_groups import build_timestamp_groups
from pipelines.frame_reconstruction.topology import (
    FrameTopology,
    FrameTopologyResolver,
    TopologyBasis,
)
from pipelines.profiling.column_roles import RoleResolution

__all__ = ["ReconstructionInput", "ReconstructionOutcome", "reconstruct"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReconstructionInput:
    """Everything the algorithm needs, already loaded by the caller."""

    frame: pl.DataFrame
    event_times: Sequence[dt.datetime | None]
    roles: RoleResolution
    serializer: CanonicalSerializer

    telemetry_file_id: object = None
    charger_id_fallback: str | None = None

    #: Declared topology for this charger, when the registry has it.
    charger_connector_count: int | None = None
    charger_smr_count: int | None = None

    default_connector_count: int | None = None
    default_smr_count: int | None = None

    severely_incomplete_below_pct: float = 50.0
    max_frames_per_timestamp: int = 64


@dataclass(slots=True)
class ReconstructionOutcome:
    """Frames, topology and metrics for one reconstruction pass."""

    frames: list[ReconstructedFrame]
    topology: FrameTopology
    metrics: FileReconstructionMetrics
    unassigned_rows: list[RawRowRef] = field(default_factory=list)
    #: Timestamp groups that raised while being reconstructed, with the reason.
    failed_groups: list[tuple[dt.datetime, str]] = field(default_factory=list)

    @property
    def canonical_frames(self) -> list[ReconstructedFrame]:
        """What Phase 1E should consume: unique + same-timestamp distinct."""
        return [frame for frame in self.frames if frame.is_canonical]

    @property
    def collision_timestamps(self) -> list[dt.datetime]:
        seen: dict[dt.datetime, int] = {}
        for frame in self.canonical_frames:
            seen[frame.event_time] = seen.get(frame.event_time, 0) + 1
        return sorted(stamp for stamp, count in seen.items() if count > 1)


def reconstruct(payload: ReconstructionInput) -> ReconstructionOutcome:
    """Run the full reconstruction pipeline."""
    started = time.perf_counter()

    # 1. logical identity + occurrence indexing, in source order
    keyed = LogicalKeyBuilder(
        roles=payload.roles,
        serializer=payload.serializer,
        charger_id_fallback=payload.charger_id_fallback,
    ).build(
        payload.frame,
        telemetry_file_id=payload.telemetry_file_id,
        event_times=payload.event_times,
    )

    # 2. expected frame shape, by documented precedence
    topology = FrameTopologyResolver(
        default_connector_count=payload.default_connector_count,
        default_smr_count=payload.default_smr_count,
    ).resolve(
        charger_connector_count=payload.charger_connector_count,
        charger_smr_count=payload.charger_smr_count,
        observed_connectors=keyed.observed_connectors,
        observed_smrs=keyed.observed_smrs,
        position_group_counts=keyed.position_group_counts,
        group_total=keyed.group_total,
    )

    # 3. group by (charger, event_time)
    groups = build_timestamp_groups(
        rows_by_timestamp=keyed.by_timestamp,
        unassigned_by_timestamp=keyed.unassigned_by_timestamp,
        topology=topology,
    )

    frames: list[ReconstructedFrame] = []
    failed: list[tuple[dt.datetime, str]] = []
    rows_assigned = 0

    for group in groups:
        try:
            candidates, occupancy = build_frame_candidates(
                group,
                severely_incomplete_below_pct=payload.severely_incomplete_below_pct,
                max_frames_per_timestamp=payload.max_frames_per_timestamp,
            )
            classified = classify_group(candidates, serializer=payload.serializer)

            for item in classified:
                candidate = item.candidate
                rows_assigned += len(candidate.rows_by_position)

                issues = list(item.issues)
                if topology.basis is TopologyBasis.UNRESOLVED:
                    issues.append(ReconstructionIssueType.INCONSISTENT_TOPOLOGY)

                frames.append(
                    ReconstructedFrame(
                        charger_id=group.charger_id,
                        event_time=group.event_time,
                        frame_sequence=candidate.sequence,
                        rows=candidate.rows,
                        frame_fingerprint=item.frame_fingerprint,
                        status=candidate.status,
                        duplicate_classification=item.classification,
                        expected_position_count=len(group.expected_positions),
                        observed_position_count=len(candidate.rows_by_position),
                        missing_position_count=len(candidate.missing_positions),
                        unexpected_position_count=len(candidate.unexpected_positions),
                        replay_of_sequence=item.replay_of_sequence,
                        missing_positions=candidate.missing_positions,
                        unexpected_positions=candidate.unexpected_positions,
                        issues=tuple(dict.fromkeys(issues)),
                        detail=_frame_detail(item, occupancy, topology),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - contained per section 35
            failed.append((group.event_time, str(exc)))
            logger.warning(
                "reconstruction.group_failed",
                charger_id=group.charger_id,
                event_time=group.event_time.isoformat(),
                error=str(exc),
            )

    unassigned = [row for rows in keyed.unassigned_by_timestamp.values() for row in rows] + list(
        keyed.undatable_rows
    )

    metrics = build_file_metrics(
        frames,
        telemetry_file_id=(str(payload.telemetry_file_id) if payload.telemetry_file_id else None),
        reconstruction_version=RECONSTRUCTION_VERSION,
        raw_rows=payload.frame.height,
        unique_timestamps=len({group.event_time for group in groups}),
        expected_positions_per_frame=topology.expected_position_count,
        topology_basis=topology.basis.value,
        rows_assigned=rows_assigned,
        rows_unassigned=len(unassigned),
        exact_duplicate_rows=keyed.exact_duplicate_row_count,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

    logger.info(
        "reconstruction.completed",
        telemetry_file_id=(str(payload.telemetry_file_id) if payload.telemetry_file_id else None),
        reconstruction_version=RECONSTRUCTION_VERSION,
        timestamp_group_count=len(groups),
        frame_count=metrics.frames_reconstructed,
        canonical_frame_count=metrics.canonical_frames,
        replay_count=metrics.full_frame_replays + metrics.partial_frame_replays,
        collision_count=metrics.collision_timestamps,
        partial_count=metrics.partial_frames,
        unassigned_row_count=metrics.rows_unassigned,
        failed_group_count=len(failed),
        duration_ms=metrics.duration_ms,
    )

    return ReconstructionOutcome(
        frames=frames,
        topology=topology,
        metrics=metrics,
        unassigned_rows=unassigned,
        failed_groups=failed,
    )


def _frame_detail(item: object, occupancy: object, topology: FrameTopology) -> Mapping[str, object]:
    """Diagnostic payload stored alongside each frame.

    Small and bounded on purpose: no raw telemetry values, so a frame row never
    becomes a second copy of Bronze.
    """
    from pipelines.frame_reconstruction.replay_detector import ClassifiedFrame
    from pipelines.frame_reconstruction.timestamp_groups import GroupOccupancy

    assert isinstance(item, ClassifiedFrame)
    assert isinstance(occupancy, GroupOccupancy)

    detail: dict[str, object] = {
        "topology_basis": topology.basis.value,
        "group_raw_rows": occupancy.raw_row_count,
        "group_max_occurrence": occupancy.max_occurrence,
        "group_even_occupancy": occupancy.is_even,
    }
    if item.differing_positions:
        detail["differing_positions"] = [str(p) for p in item.differing_positions]
    if item.note:
        detail["note"] = item.note
    if topology.note:
        detail["topology_note"] = topology.note
    return detail


def summarise(outcome: ReconstructionOutcome) -> dict[str, object]:
    """Flat summary for CLI/API use."""
    payload = outcome.metrics.as_dict()
    payload["topology"] = outcome.topology.describe()
    payload["collision_timestamps"] = [stamp.isoformat() for stamp in outcome.collision_timestamps]
    payload["failed_groups"] = len(outcome.failed_groups)
    return payload


def frames_by_position(frame: ReconstructedFrame) -> dict[LogicalPosition, RawRowRef]:
    return {row.position: row for row in frame.rows}


def status_counts(frames: Sequence[ReconstructedFrame]) -> dict[FrameStatus, int]:
    counts = dict.fromkeys(FrameStatus, 0)
    for frame in frames:
        counts[frame.status] += 1
    return counts


def classification_counts(
    frames: Sequence[ReconstructedFrame],
) -> dict[DuplicateClassification, int]:
    counts = dict.fromkeys(DuplicateClassification, 0)
    for frame in frames:
        counts[frame.duplicate_classification] += 1
    return counts
