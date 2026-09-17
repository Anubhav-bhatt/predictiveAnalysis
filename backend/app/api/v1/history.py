"""Historical continuity and time-series research endpoints (Phase 7).

Provides unified time-series queries for chargers, physical components, and signals
across multiple files and days, with gap detection and empirical sampling analysis.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.deps import HistoricalServiceDep
from backend.app.schemas.common import Envelope, ok
from backend.app.schemas.history import (
    ChargerContinuitySummaryDTO,
    ChargerHistoryResponse,
    ConfigurationSnapshotDTO,
    HistoricalGapDTO,
    PatternResearchEligibilityDTO,
    SignalAvailabilityMatrixResponse,
    SignalHistoryResponse,
)

router = APIRouter(tags=["history"])


@router.get(
    "/chargers/{charger_id}/history",
    response_model=Envelope[ChargerHistoryResponse],
    summary="Get bounded historical telemetry for a charger",
)
async def get_charger_history(
    charger_id: str,
    service: HistoricalServiceDep,
    start_time: dt.datetime | None = Query(None, description="Start timestamp (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="End timestamp (inclusive, UTC)"),
    metrics: list[str] | None = Query(None, description="Authoritative metrics whitelist"),
    limit: int = Query(1000, ge=1, le=5000, description="Max observations to return"),
    cursor: str | None = Query(None, description="Keyset pagination cursor: ISO#sequence"),
) -> Envelope[ChargerHistoryResponse]:
    """Retrieve chronological cabinet and grid telemetry ordered by event_time, frame_sequence."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    resp = await service.get_charger_history(
        charger_id=charger_id,
        start_time=start_time,
        end_time=end_time,
        metrics=metrics,
        limit=limit,
        cursor=cursor,
    )
    return ok(resp)


@router.get(
    "/chargers/{charger_id}/components/{component_type}/{component_id}/history",
    response_model=Envelope[ChargerHistoryResponse],
    summary="Get bounded historical telemetry for a physical component",
)
async def get_component_history(
    charger_id: str,
    component_type: str,
    component_id: int,
    service: HistoricalServiceDep,
    start_time: dt.datetime | None = Query(None, description="Start timestamp (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="End timestamp (inclusive, UTC)"),
    metrics: list[str] | None = Query(None, description="Authoritative metrics whitelist"),
    limit: int = Query(1000, ge=1, le=5000, description="Max observations to return"),
    cursor: str | None = Query(None, description="Keyset pagination cursor: ISO#sequence"),
) -> Envelope[ChargerHistoryResponse]:
    """Retrieve chronological component telemetry (connector, SMR, rectifier)."""
    if component_type.lower() not in ("connector", "smr", "rectifier"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid component_type '{component_type}'. Must be connector, smr, or rectifier."
            ),
        )

    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    try:
        resp = await service.get_component_history(
            charger_id=charger_id,
            component_type=component_type,
            component_id=component_id,
            start_time=start_time,
            end_time=end_time,
            metrics=metrics,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ok(resp)


@router.get(
    "/chargers/{charger_id}/signals/{signal_name}/history",
    response_model=Envelope[SignalHistoryResponse],
    summary="Get raw observation stream for a canonical signal",
)
async def get_signal_history(
    charger_id: str,
    signal_name: str,
    service: HistoricalServiceDep,
    component_type: str | None = Query(
        None, description="Optional component scope: connector, smr, rectifier"
    ),
    component_id: int | None = Query(None, description="Optional component ID (e.g. 1, 2)"),
    start_time: dt.datetime | None = Query(None, description="Start timestamp (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="End timestamp (inclusive, UTC)"),
    limit: int = Query(5000, ge=1, le=10000, description="Max observations to return"),
) -> Envelope[SignalHistoryResponse]:
    """Retrieve raw normalized values and provenance flags for a single canonical signal."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    resp = await service.get_signal_history(
        charger_id=charger_id,
        signal_name=signal_name,
        component_type=component_type,
        component_id=component_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return ok(resp)


@router.get(
    "/chargers/{charger_id}/summary",
    response_model=Envelope[ChargerContinuitySummaryDTO],
    summary="Get multi-day continuity summary for a charger",
)
async def get_charger_summary(
    charger_id: str,
    service: HistoricalServiceDep,
) -> Envelope[ChargerContinuitySummaryDTO]:
    """Calculate descriptive multi-day continuity, sampling interval, and gap analysis."""
    summary = await service.get_charger_continuity_summary(charger_id)
    return ok(summary)


@router.get(
    "/chargers/{charger_id}/gaps",
    response_model=Envelope[list[HistoricalGapDTO]],
    summary="Get detected telemetry gaps for a charger",
)
async def get_charger_gaps(
    charger_id: str,
    service: HistoricalServiceDep,
) -> Envelope[list[HistoricalGapDTO]]:
    """Retrieve observed gaps relative to local sampling interval without data imputation."""
    summary = await service.get_charger_continuity_summary(charger_id)
    return ok(summary.gaps)


@router.get(
    "/chargers/{charger_id}/configuration-timeline",
    response_model=Envelope[list[ConfigurationSnapshotDTO]],
    summary="Get configuration version history for a charger",
)
async def get_configuration_timeline(
    charger_id: str,
    service: HistoricalServiceDep,
) -> Envelope[list[ConfigurationSnapshotDTO]]:
    """Retrieve chronological configuration snapshots and computed SHA-256 config hashes."""
    timeline = await service.get_configuration_timeline(charger_id)
    return ok(timeline)


@router.get(
    "/fleet/signal-matrix",
    response_model=Envelope[SignalAvailabilityMatrixResponse],
    summary="Get fleet-wide signal availability matrix",
)
async def get_signal_availability_matrix(
    service: HistoricalServiceDep,
    charger_ids: list[str] | None = Query(None, description="Optional list of charger IDs"),
) -> Envelope[SignalAvailabilityMatrixResponse]:
    """Expose observed valid telemetry availability (not merely schema presence) across fleet."""
    resp = await service.get_fleet_signal_availability_matrix(charger_ids=charger_ids)
    return ok(resp)


@router.get(
    "/chargers/{charger_id}/pattern-eligibility",
    response_model=Envelope[PatternResearchEligibilityDTO],
    summary="Get pattern research readiness assessment for a charger",
)
async def get_pattern_eligibility(
    charger_id: str,
    service: HistoricalServiceDep,
) -> Envelope[PatternResearchEligibilityDTO]:
    """Assess whether charger telemetry is eligible for temporal pattern discovery."""
    summary = await service.get_charger_continuity_summary(charger_id)
    return ok(summary.pattern_eligibility)
