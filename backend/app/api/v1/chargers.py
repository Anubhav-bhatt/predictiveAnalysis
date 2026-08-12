"""Charger-scoped Phase 1C endpoints (section 30).

Coverage history and telemetry gaps for a single charger - the data behind the
charger detail page's Coverage tab and its gap timeline (sections 37, 38).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.deps import FileRepoDep, FleetRepoDep, PageDep, QualityRepoDep, SettingsDep
from backend.app.models.enums import GapSeverity
from backend.app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from backend.app.schemas.fleet import (
    ChargerCoverageRow,
    ChargerDayDetail,
    ChargerDayFinding,
    ContributingFile,
    GapRow,
)

router = APIRouter(prefix="/chargers", tags=["chargers"])

FromQuery = Annotated[dt.date, Query(alias="from", description="Inclusive start date.")]
ToQuery = Annotated[dt.date, Query(alias="to", description="Inclusive end date.")]


def _validate_range(date_from: dt.date, date_to: dt.date, *, max_days: int) -> None:
    """Reject inverted and unbounded ranges before they reach the database."""
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'to' must not be earlier than 'from'",
        )
    span = (date_to - date_from).days + 1
    if span > max_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested {span} days; the configured maximum is {max_days}",
        )


@router.get(
    "/{charger_id}/coverage",
    response_model=Envelope[list[ChargerCoverageRow]],
    summary="Daily coverage history for one charger",
)
async def coverage_history(
    charger_id: str,
    fleet: FleetRepoDep,
    settings: SettingsDep,
    date_from: FromQuery,
    date_to: ToQuery,
) -> Envelope[list[ChargerCoverageRow]]:
    _validate_range(date_from, date_to, max_days=settings.api.max_coverage_history_days)
    rows = await fleet.coverage_history(charger_id, date_from, date_to)
    return ok(
        [ChargerCoverageRow.model_validate(row) for row in rows],
        charger_id=charger_id,
        **{"from": date_from.isoformat(), "to": date_to.isoformat()},
        day_count=len(rows),
    )


@router.get(
    "/{charger_id}/gaps",
    response_model=PaginatedEnvelope[GapRow],
    summary="Telemetry gaps for one charger",
)
async def charger_gaps(
    charger_id: str,
    fleet: FleetRepoDep,
    page: PageDep,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
    severity: GapSeverity | None = None,
) -> PaginatedEnvelope[GapRow]:
    result = await fleet.list_gaps(
        page,
        charger_id=charger_id,
        date_from=date_from,
        date_to=date_to,
        severity=severity,
    )
    return paginated([GapRow.model_validate(row) for row in result.items], result.meta())


@router.get(
    "/{charger_id}/coverage/{business_date}",
    response_model=Envelope[ChargerDayDetail],
    summary="One charger-day with its gaps, findings and contributing files",
)
async def charger_day_detail(
    charger_id: str,
    business_date: dt.date,
    fleet: FleetRepoDep,
    files: FileRepoDep,
    quality: QualityRepoDep,
) -> Envelope[ChargerDayDetail]:
    """Backs the gap timeline (section 38) and the multi-file view (section 19)."""
    coverage = await fleet.get_coverage(charger_id, business_date)
    if coverage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No coverage record for {charger_id} on {business_date.isoformat()}",
        )

    gaps = await fleet.gaps_for_coverage(coverage.id)
    findings = await quality.charger_day_issues(coverage.id)
    file_days = await files.file_days_for_charger(charger_id, business_date, business_date)
    file_by_id = {
        f.id: f for f in await files.files_for_charger_day(charger_id, business_date)
    }

    contributing = [
        ContributingFile(
            telemetry_file_id=day.telemetry_file_id,
            original_filename=file_by_id[day.telemetry_file_id].original_filename,
            status=file_by_id[day.telemetry_file_id].status,
            received_at=file_by_id[day.telemetry_file_id].received_at,
            business_date=day.business_date,
            filename_date=file_by_id[day.telemetry_file_id].filename_date,
            file_date_span=file_by_id[day.telemetry_file_id].file_date_span,
            row_count_for_date=day.row_count,
            unique_timestamp_count_for_date=day.unique_timestamp_count,
            first_event_at=day.first_event_at,
            last_event_at=day.last_event_at,
            quality_score=file_by_id[day.telemetry_file_id].quality_score,
        )
        for day in file_days
        if day.telemetry_file_id in file_by_id
    ]

    detail = ChargerDayDetail(
        coverage=ChargerCoverageRow.model_validate(coverage),
        gaps=[GapRow.model_validate(g) for g in gaps],
        findings=[ChargerDayFinding.model_validate(f) for f in findings],
        files=contributing,
    )
    return ok(detail)


__all__ = ["router"]
