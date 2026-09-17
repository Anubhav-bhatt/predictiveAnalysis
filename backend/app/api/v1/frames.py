"""Frame reconstruction diagnostics API (Phase 1D sections 45-48).

Read-only. Reconstruction itself is driven by the CLI/worker, not by an HTTP call,
so an expensive 16.5 MB re-read can never be triggered by a browser refresh.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.deps import FileRepoDep, FrameRepoDep, PageDep
from backend.app.models.enums import DuplicateClassification, FrameStatus
from backend.app.models.telemetry_frame import TelemetrySourceFrame
from backend.app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from backend.app.schemas.frames import (
    CollisionGroup,
    FrameDetail,
    FrameDiff,
    FrameFieldDifference,
    FrameRowRef,
    FrameSourceRef,
    FrameSummaryRow,
    ReconstructionSummary,
)

router = APIRouter(tags=["frames"])


def _parse_uuid(raw: str, field: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} is not a valid UUID",
        ) from exc


# ---------------------------------------------------------------------------
# Section 45 - per-file reconstruction summary
# ---------------------------------------------------------------------------


@router.get(
    "/ingestion/files/{file_id}/reconstruction",
    response_model=Envelope[ReconstructionSummary],
    summary="Frame reconstruction outcome for one telemetry file",
)
async def file_reconstruction(
    file_id: str,
    frames: FrameRepoDep,
    files: FileRepoDep,
    reconstruction_version: Annotated[str | None, Query()] = None,
) -> Envelope[ReconstructionSummary]:
    parsed = _parse_uuid(file_id, "file_id")
    telemetry_file = await files.get(parsed)
    if telemetry_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Telemetry file not found"
        )

    summary = await frames.file_summary(parsed, reconstruction_version=reconstruction_version)
    payload = ReconstructionSummary(
        telemetry_file_id=parsed,
        original_filename=telemetry_file.original_filename,
        reconstruction_version=reconstruction_version,
        raw_rows=telemetry_file.row_count,
        **summary,
    )
    return ok(payload)


# ---------------------------------------------------------------------------
# Section 46 - frame list for a charger
# ---------------------------------------------------------------------------


@router.get(
    "/chargers/{charger_id}/frames",
    response_model=PaginatedEnvelope[FrameSummaryRow],
    summary="Reconstructed frames for one charger",
)
async def charger_frames(
    charger_id: str,
    frames: FrameRepoDep,
    page: PageDep,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
    frame_status: FrameStatus | None = None,
    duplicate_classification: DuplicateClassification | None = None,
    canonical_only: Annotated[bool, Query()] = False,
) -> PaginatedEnvelope[FrameSummaryRow]:
    """Ordered by event time then sequence, so same-second frames stay in order."""
    if date_from and date_to and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'to' must not be earlier than 'from'",
        )
    result = await frames.list_for_charger(
        page,
        charger_id=charger_id,
        date_from=date_from,
        date_to=date_to,
        frame_status=frame_status,
        duplicate_classification=duplicate_classification,
        canonical_only=canonical_only,
    )
    rows = [FrameSummaryRow.model_validate(frame) for frame in result.items]
    return paginated(rows, result.meta())


@router.get(
    "/chargers/{charger_id}/frames/collisions",
    response_model=Envelope[list[CollisionGroup]],
    summary="Event timestamps carrying more than one canonical frame",
)
async def charger_collisions(
    charger_id: str,
    frames: FrameRepoDep,
    business_date: Annotated[dt.date, Query(alias="date")],
) -> Envelope[list[CollisionGroup]]:
    """Backs the collision explorer (section 50)."""
    collisions = await frames.collision_timestamps(charger_id, business_date)

    groups: list[CollisionGroup] = []
    for event_time, canonical_count in collisions:
        at_time = await frames.frames_at(charger_id, event_time)
        rows = [FrameSummaryRow.model_validate(frame) for frame in at_time]
        groups.append(
            CollisionGroup(
                charger_id=charger_id,
                event_time=event_time,
                business_date=business_date,
                frame_count=len(rows),
                canonical_count=canonical_count,
                frames=rows,
            )
        )
    return ok(groups, charger_id=charger_id, date=business_date.isoformat())


# ---------------------------------------------------------------------------
# Section 47 - frame detail
# ---------------------------------------------------------------------------


@router.get(
    "/frames/{frame_id}",
    response_model=Envelope[FrameDetail],
    summary="One frame with structure, provenance and diagnostics",
)
async def frame_detail(frame_id: str, frames: FrameRepoDep) -> Envelope[FrameDetail]:
    parsed = _parse_uuid(frame_id, "frame_id")
    frame = await frames.get(parsed)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found")

    detail = dict(frame.detail or {})
    replays = await frames.replay_sources(parsed)
    siblings = [
        sibling
        for sibling in await frames.frames_at(frame.charger_id, frame.event_time)
        if sibling.id != frame.id
    ]

    payload = FrameDetail(
        frame=FrameSummaryRow.model_validate(frame),
        missing_positions=_string_list(detail.get("missing_positions")),
        unexpected_positions=_string_list(detail.get("unexpected_positions")),
        observed_positions=sorted(
            row.logical_position for row in frame.frame_rows if row.logical_position is not None
        ),
        issues=_string_list(detail.get("issues")),
        sources=[
            FrameSourceRef(
                telemetry_file_id=source.telemetry_file_id,
                original_filename=(
                    source.telemetry_file.original_filename if source.telemetry_file else None
                ),
                status=source.telemetry_file.status if source.telemetry_file else None,
                received_at=(source.telemetry_file.received_at if source.telemetry_file else None),
                first_source_row=source.first_source_row,
                last_source_row=source.last_source_row,
                row_count=source.row_count,
                source_occurrence=source.source_occurrence,
                is_primary_source=source.is_primary_source,
            )
            for source in frame.sources
        ],
        rows=[FrameRowRef.model_validate(row) for row in frame.frame_rows],
        replays=[FrameSummaryRow.model_validate(replay) for replay in replays],
        siblings=[FrameSummaryRow.model_validate(sibling) for sibling in siblings],
        detail=detail,
    )
    return ok(payload)


# ---------------------------------------------------------------------------
# Section 48 - frame comparison
# ---------------------------------------------------------------------------


@router.get(
    "/frames/{frame_id}/diff/{other_frame_id}",
    response_model=Envelope[FrameDiff],
    summary="Compare two frames position by position",
)
async def frame_diff(
    frame_id: str, other_frame_id: str, frames: FrameRepoDep
) -> Envelope[FrameDiff]:
    """Which logical positions differ, computed from row fingerprints.

    Reports *where* two frames diverge without returning telemetry values. Field
    names are never hard-coded: the comparison is over whatever positions the
    frames actually contain.
    """
    left_id = _parse_uuid(frame_id, "frame_id")
    right_id = _parse_uuid(other_frame_id, "other_frame_id")

    left = await frames.get(left_id)
    right = await frames.get(right_id)
    if left is None or right is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="One or both frames not found"
        )
    if left.charger_id != right.charger_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Frames belong to different chargers and are not comparable",
        )

    left_rows = _by_position(left)
    right_rows = _by_position(right)
    shared = sorted(set(left_rows) & set(right_rows))

    differing = [p for p in shared if left_rows[p] != right_rows[p]]
    matching = [p for p in shared if left_rows[p] == right_rows[p]]

    payload = FrameDiff(
        left=FrameSummaryRow.model_validate(left),
        right=FrameSummaryRow.model_validate(right),
        same_event_time=left.event_time == right.event_time,
        identical_payload=left.frame_fingerprint == right.frame_fingerprint,
        differing_positions=differing,
        matching_positions=matching,
        only_in_left=sorted(set(left_rows) - set(right_rows)),
        only_in_right=sorted(set(right_rows) - set(left_rows)),
        positions=[
            FrameFieldDifference(
                logical_position=position,
                left_row_fingerprint=left_rows.get(position),
                right_row_fingerprint=right_rows.get(position),
                differs=left_rows.get(position) != right_rows.get(position),
            )
            for position in sorted(set(left_rows) | set(right_rows))
        ],
    )
    return ok(payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_position(frame: TelemetrySourceFrame) -> dict[str, str]:
    return {
        row.logical_position: row.row_fingerprint
        for row in frame.frame_rows
        if row.logical_position is not None and not row.unassigned
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


__all__ = ["router"]
