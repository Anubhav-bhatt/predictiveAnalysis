"""Daily fleet data-operations endpoints (Phase 1C section 30).

Every number returned here is computed from persisted reconciliation output. No
endpoint recomputes coverage on the fly, and none fabricates a value when the
underlying field is absent - it returns null, so the UI can render "-" honestly
rather than an invented zero (section 33).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.deps import (
    FleetRepoDep,
    MetricsServiceDep,
    PageDep,
    QualityRepoDep,
    RunRepoDep,
)
from backend.app.models.enums import (
    ArrivalStatus,
    CompletenessStatus,
    FileStatus,
)
from backend.app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from backend.app.schemas.fleet import (
    ChargerCoverageRow,
    DailyOperationsSummary,
    DailyProcessingStage,
    IngestionRunDetail,
    IngestionRunRow,
    LateFileRow,
    MissingChargerRow,
)

router = APIRouter(prefix="/data-operations", tags=["data-operations"])

DateQuery = Annotated[dt.date, Query(description="Telemetry business date (YYYY-MM-DD).")]


@router.get(
    "/daily",
    response_model=Envelope[DailyOperationsSummary],
    summary="Fleet delivery summary for one business date",
)
async def daily_summary(
    date: DateQuery,
    metrics: MetricsServiceDep,
    runs: RunRepoDep,
) -> Envelope[DailyOperationsSummary]:
    daily = await metrics.daily(date)
    stages = await _stages_for(date, runs, daily.expected_chargers)

    payload = DailyOperationsSummary(
        business_date=date,
        expected=daily.expected_chargers,
        received=daily.received_chargers,
        complete=daily.complete,
        partial=daily.partial,
        severely_incomplete=daily.severely_incomplete,
        no_data=daily.no_data,
        late=daily.late,
        missing=daily.missing,
        unexpected=daily.unexpected,
        failed=daily.files_failed,
        quarantined=daily.files_quarantined,
        duplicate=daily.files_duplicate,
        fleet_coverage_percentage=daily.fleet_coverage_percentage,
        average_coverage_percentage=daily.average_coverage_percentage,
        p50_coverage_percentage=daily.p50_coverage_percentage,
        p95_coverage_percentage=daily.p95_coverage_percentage,
        p95_largest_gap_seconds=daily.p95_largest_gap_seconds,
        fleet_delivery_rate=daily.fleet_delivery_rate,
        fleet_complete_day_rate=daily.fleet_complete_day_rate,
        fleet_missing_rate=daily.fleet_missing_rate,
        fleet_partial_rate=daily.fleet_partial_rate,
        late_arrival_rate=daily.late_arrival_rate,
        total_gap_count=daily.total_gap_count,
        largest_gap_seconds=daily.largest_gap_seconds,
        daily_rule_counts=daily.daily_rule_counts,
        stages=stages,
    )
    return ok(payload, business_date=date.isoformat())


async def _stages_for(
    business_date: dt.date, runs: RunRepoDep, expected: int
) -> list[DailyProcessingStage]:
    """Derive pipeline stage status from the date's runs (section 32).

    Stages are reported from persisted run counters rather than a live progress
    feed, and only as far as the evidence supports: with no run for the date the
    honest answer is PENDING, not a green tick.
    """
    date_runs = await runs.list_for_date(business_date)
    if not date_runs:
        return [
            DailyProcessingStage(stage=name, status="PENDING")
            for name in (
                "Discovery",
                "Registration",
                "Profiling",
                "Schema validation",
                "Quality analysis",
                "Coverage reconciliation",
            )
        ]

    latest = date_runs[0]
    analysed = latest.files_ready + latest.files_partial

    def state(done: bool, *, warn: bool = False) -> str:
        if warn:
            return "COMPLETED_WITH_WARNINGS"
        return "COMPLETED" if done else "PENDING"

    had_problems = bool(latest.files_failed or latest.files_quarantined)
    reconciled = latest.status.is_terminal

    return [
        DailyProcessingStage(
            stage="Discovery",
            status=state(latest.files_discovered > 0),
            count=latest.files_discovered,
        ),
        DailyProcessingStage(
            stage="Registration",
            status=state(latest.files_registered > 0),
            count=latest.files_registered,
        ),
        DailyProcessingStage(
            stage="Profiling", status=state(analysed > 0, warn=had_problems), count=analysed
        ),
        DailyProcessingStage(stage="Schema validation", status=state(analysed > 0), count=analysed),
        DailyProcessingStage(stage="Quality analysis", status=state(analysed > 0), count=analysed),
        DailyProcessingStage(
            stage="Coverage reconciliation",
            status=state(reconciled),
            count=expected or None,
            detail=latest.status.value,
        ),
    ]


@router.get(
    "/daily/{date}/chargers",
    response_model=PaginatedEnvelope[ChargerCoverageRow],
    summary="Charger-days for one business date, filterable",
)
async def daily_chargers(
    date: dt.date,
    fleet: FleetRepoDep,
    page: PageDep,
    arrival_status: ArrivalStatus | None = None,
    completeness_status: CompletenessStatus | None = None,
    processing_status: FileStatus | None = None,
    site: str | None = None,
    charger: str | None = None,
) -> PaginatedEnvelope[ChargerCoverageRow]:
    """Worst coverage first (section 34), so the operator sees the problems."""
    result = await fleet.list_coverage(
        page,
        business_date=date,
        arrival_status=arrival_status,
        completeness_status=completeness_status,
        processing_status=processing_status,
        charger_id=charger,
        site_code=site,
    )
    rows = [_coverage_row(item) for item in result.items]
    return paginated(rows, result.meta())


@router.get(
    "/daily/{date}/missing",
    response_model=PaginatedEnvelope[MissingChargerRow],
    summary="Chargers expected but absent on a business date",
)
async def missing_chargers(
    date: dt.date,
    fleet: FleetRepoDep,
    page: PageDep,
    site: str | None = None,
) -> PaginatedEnvelope[MissingChargerRow]:
    """Section 33.

    ``last_successful_*`` and ``previous_day_*`` come from two grouped queries
    over the whole page rather than a lookup per charger (section 40). Fields with
    no underlying record stay null - nothing here is fabricated.
    """
    result = await fleet.list_coverage(
        page, business_date=date, arrival_status=ArrivalStatus.MISSING, site_code=site
    )
    charger_ids = [row.charger_id for row in result.items]

    last_success = await fleet.last_successful_days(date, charger_ids)
    previous = await fleet.coverage_percentage_on(date - dt.timedelta(days=1), charger_ids)

    rows: list[MissingChargerRow] = []
    for item in result.items:
        success = last_success.get(item.charger_id)
        rows.append(
            MissingChargerRow(
                charger_id=item.charger_id,
                business_date=item.business_date,
                site_code=item.charger.site_code if item.charger else None,
                ocpp_id=item.charger.ocpp_id if item.charger else None,
                expected_since=item.charger.telemetry_start_date if item.charger else None,
                last_successful_date=success[0] if success else None,
                last_successful_coverage_percentage=success[1] if success else None,
                previous_day_coverage_percentage=previous.get(item.charger_id),
                last_seen_at=item.last_event_at,
            )
        )
    return paginated(rows, result.meta())


@router.get(
    "/daily/{date}/late",
    response_model=PaginatedEnvelope[LateFileRow],
    summary="Charger-days whose telemetry arrived after the configured cutoff",
)
async def late_arrivals(
    date: dt.date,
    fleet: FleetRepoDep,
    page: PageDep,
) -> PaginatedEnvelope[LateFileRow]:
    result = await fleet.list_coverage(page, business_date=date, arrival_status=ArrivalStatus.LATE)
    rows = [
        LateFileRow(
            charger_id=item.charger_id,
            business_date=item.business_date,
            site_code=item.charger.site_code if item.charger else None,
            received_at=item.first_received_at,
            late_by_seconds=item.late_by_seconds,
            coverage_percentage=item.coverage_percentage,
            completeness_status=item.completeness_status,
            arrival_status=item.arrival_status,
        )
        for item in result.items
    ]
    return paginated(rows, result.meta())


@router.get(
    "/daily/{date}/findings",
    response_model=Envelope[dict[str, int]],
    summary="Charger-day rule findings for a business date, counted by rule",
)
async def daily_findings(date: dt.date, quality: QualityRepoDep) -> Envelope[dict[str, int]]:
    counts = await quality.charger_day_rule_counts(date)
    return ok(counts, business_date=date.isoformat())


@router.get(
    "/runs",
    response_model=PaginatedEnvelope[IngestionRunRow],
    summary="Fleet ingestion runs, newest first",
)
async def list_runs(runs: RunRepoDep, page: PageDep) -> PaginatedEnvelope[IngestionRunRow]:
    result = await runs.list(page)
    return paginated([IngestionRunRow.model_validate(item) for item in result.items], result.meta())


@router.get(
    "/runs/{run_id}",
    response_model=Envelope[IngestionRunDetail],
    summary="One fleet ingestion run",
)
async def get_run(run_id: str, runs: RunRepoDep) -> Envelope[IngestionRunDetail]:
    from uuid import UUID

    try:
        parsed = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="run_id is not a valid UUID"
        ) from exc

    run = await runs.get(parsed)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    return ok(IngestionRunDetail.model_validate(run))


@router.get(
    "/metrics",
    response_model=Envelope[dict[str, float]],
    summary="Internal operational counters for a business date (section 48)",
)
async def operational_counters(
    date: DateQuery, metrics: MetricsServiceDep
) -> Envelope[dict[str, float]]:
    counters = await metrics.counters(date)
    return ok({key: float(value) for key, value in counters.items()})


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _coverage_row(item: object) -> ChargerCoverageRow:
    """Map a ChargerDayCoverage row, pulling registry context off the relationship."""
    row = ChargerCoverageRow.model_validate(item)
    charger = getattr(item, "charger", None)
    if charger is not None:
        row = row.model_copy(update={"site_code": charger.site_code, "ocpp_id": charger.ocpp_id})
    return row


__all__ = ["router"]
