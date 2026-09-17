"""Discrete operational event reconstruction endpoints (Phase 8).

Exposes reconstructed charging sessions, alarm intervals, fault spans,
configuration change events, and a unified chronological timeline for chargers.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.deps import EventRepoDep, EventServiceDep
from backend.app.schemas.common import Envelope, ok
from backend.app.schemas.events import (
    AlarmEventRead,
    AlarmEventsResponse,
    ChargingSessionEventRead,
    ChargingSessionsResponse,
    EventReconstructionOutcome,
    EventTimelineResponse,
)

router = APIRouter(tags=["events"])


@router.post(
    "/chargers/{charger_id}/reconstruct-events",
    response_model=Envelope[EventReconstructionOutcome],
    summary="Reconstruct discrete events from Silver telemetry history",
)
async def reconstruct_charger_events(
    charger_id: str,
    service: EventServiceDep,
    start_time: dt.datetime | None = Query(None, description="Window start time (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="Window end time (inclusive, UTC)"),
) -> Envelope[EventReconstructionOutcome]:
    """Execute deterministic event reconstruction algorithms over normalized Silver history.

    Reconstructs charging sessions, contiguous alarm intervals, hardware fault trips,
    operational state transitions, and configuration parameter changes with gap awareness
    and idempotent windowed recomputation.
    """
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    try:
        outcome = await service.reconstruct_charger_events(
            charger_id=charger_id,
            start_time=start_time,
            end_time=end_time,
        )
        return ok(outcome)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Event reconstruction failed: {exc}",
        ) from exc


@router.get(
    "/chargers/{charger_id}/event-timeline",
    response_model=Envelope[EventTimelineResponse],
    summary="Get unified chronological operational event stream for a charger",
)
async def get_charger_event_timeline(
    charger_id: str,
    service: EventServiceDep,
    start_time: dt.datetime | None = Query(None, description="Window start time (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="Window end time (inclusive, UTC)"),
    limit: int = Query(100, ge=1, le=500, description="Max timeline events to return"),
) -> Envelope[EventTimelineResponse]:
    """Retrieve unified chronological operational events (sessions, alarms, faults, etc)."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    items = await service.get_unified_timeline(
        charger_id=charger_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return ok(EventTimelineResponse(charger_id=charger_id, total_count=len(items), events=items))


@router.get(
    "/chargers/{charger_id}/events",
    response_model=Envelope[EventTimelineResponse],
    summary="Alias for charger event timeline",
)
async def get_charger_events(
    charger_id: str,
    service: EventServiceDep,
    start_time: dt.datetime | None = Query(None, description="Window start time (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="Window end time (inclusive, UTC)"),
    limit: int = Query(100, ge=1, le=500, description="Max timeline events to return"),
) -> Envelope[EventTimelineResponse]:
    """Retrieve unified chronological operational events."""
    return await get_charger_event_timeline(
        charger_id=charger_id,
        service=service,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@router.get(
    "/chargers/{charger_id}/sessions",
    response_model=Envelope[ChargingSessionsResponse],
    summary="Get reconstructed charging sessions for a charger",
)
async def get_charger_sessions(
    charger_id: str,
    repo: EventRepoDep,
    connector_id: int | None = Query(None, description="Filter by physical connector ID"),
    start_time: dt.datetime | None = Query(None, description="Window start time (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="Window end time (inclusive, UTC)"),
    limit: int = Query(100, ge=1, le=500, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> Envelope[ChargingSessionsResponse]:
    """Retrieve reconstructed charging sessions with energy, duration, and stop reason."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    sessions = await repo.get_sessions(
        charger_id=charger_id,
        connector_id=connector_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    dtos = [ChargingSessionEventRead.model_validate(s) for s in sessions]
    return ok(ChargingSessionsResponse(charger_id=charger_id, total_count=len(dtos), sessions=dtos))


@router.get(
    "/chargers/{charger_id}/alarms",
    response_model=Envelope[AlarmEventsResponse],
    summary="Get reconstructed alarm interval events for a charger",
)
async def get_charger_alarms(
    charger_id: str,
    repo: EventRepoDep,
    alarm_code: str | None = Query(None, description="Filter by alarm code"),
    is_open: bool | None = Query(None, description="Filter by open/active state"),
    start_time: dt.datetime | None = Query(None, description="Window start time (inclusive, UTC)"),
    end_time: dt.datetime | None = Query(None, description="Window end time (inclusive, UTC)"),
    limit: int = Query(100, ge=1, le=500, description="Max alarms to return"),
) -> Envelope[AlarmEventsResponse]:
    """Retrieve reconstructed contiguous alarm intervals with duration and state transitions."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must not be greater than end_time",
        )

    alarms = await repo.get_alarms(
        charger_id=charger_id,
        alarm_code=alarm_code,
        is_open=is_open,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    dtos = [AlarmEventRead.model_validate(a) for a in alarms]
    return ok(AlarmEventsResponse(charger_id=charger_id, total_count=len(dtos), alarms=dtos))
