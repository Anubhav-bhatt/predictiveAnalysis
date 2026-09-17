"""Phase 9 research and pattern discovery API endpoints.

Exposes fleet EDA summaries, per-charger signal statistics, cross-signal
correlations, pattern candidates, dataset construction, and data readiness
assessment.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.api.deps import ResearchServiceDep
from backend.app.schemas.common import Envelope, ok
from backend.app.schemas.research import (
    AnalyticalDatasetSummaryDTO,
    CorrelationMatrixDTO,
    DataReadinessDTO,
    FleetEDASummaryDTO,
    PatternCandidateDTO,
    PatternScanOutcomeDTO,
    SignalStatisticsDTO,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/fleet-eda")
async def fleet_eda_summary(
    svc: ResearchServiceDep,
) -> Envelope[FleetEDASummaryDTO]:
    """Fleet-wide exploratory data analysis summary statistics."""
    result = await svc.get_fleet_eda_summary()
    return ok(result)


@router.get("/data-readiness")
async def data_readiness(
    svc: ResearchServiceDep,
) -> Envelope[DataReadinessDTO]:
    """Assess data readiness for future ML phases."""
    result = await svc.get_data_readiness()
    return ok(result)


@router.get("/chargers/{charger_id}/signal-stats")
async def charger_signal_stats(
    charger_id: str,
    svc: ResearchServiceDep,
) -> Envelope[list[SignalStatisticsDTO]]:
    """Per-signal descriptive statistics for a charger."""
    result = await svc.get_signal_statistics(charger_id)
    return ok(result)


@router.get("/chargers/{charger_id}/correlations")
async def charger_correlations(
    charger_id: str,
    svc: ResearchServiceDep,
) -> Envelope[CorrelationMatrixDTO]:
    """Cross-signal correlation matrix for a charger."""
    result = await svc.get_signal_correlations(charger_id)
    return ok(result)


@router.get("/chargers/{charger_id}/patterns")
async def charger_patterns(
    charger_id: str,
    svc: ResearchServiceDep,
    pattern_category: str | None = Query(None, description="Filter by pattern category"),
    evidence_level: str | None = Query(None, description="Filter by evidence level"),
    min_confidence: float | None = Query(
        None, ge=0.0, le=1.0, description="Minimum confidence score"
    ),
    limit: int = Query(200, ge=1, le=1000),
) -> Envelope[list[PatternCandidateDTO]]:
    """Retrieve discovered pattern candidates for a charger."""
    result = await svc.get_pattern_candidates(
        charger_id,
        pattern_category=pattern_category,
        evidence_level=evidence_level,
        min_confidence=min_confidence,
        limit=limit,
    )
    return ok(result)


@router.post("/chargers/{charger_id}/scan-patterns")
async def scan_patterns(
    charger_id: str,
    svc: ResearchServiceDep,
) -> Envelope[PatternScanOutcomeDTO]:
    """Trigger pattern scanning for a charger."""
    result = await svc.scan_patterns(charger_id)
    return ok(result)


@router.post("/chargers/{charger_id}/build-dataset")
async def build_dataset(
    charger_id: str,
    svc: ResearchServiceDep,
    grain: str = Query("CHARGER_TIME", description="Analytical grain"),
) -> Envelope[AnalyticalDatasetSummaryDTO]:
    """Trigger analytical dataset construction for a charger."""
    from backend.app.models.enums import AnalyticalGrain

    try:
        grain_enum = AnalyticalGrain(grain)
    except ValueError:
        grain_enum = AnalyticalGrain.CHARGER_TIME

    result = await svc.build_dataset(charger_id, grain=grain_enum)
    return ok(result)
