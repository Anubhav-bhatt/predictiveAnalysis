"""Research orchestration service (Phase 9).

Coordinates Silver + Events queries → analytical dataset construction →
pattern scanning → result persistence. All scientific computation is
delegated to pure pipeline modules; this service handles IO orchestration.
"""

from __future__ import annotations

import time
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.enums import AnalyticalGrain
from backend.app.models.research_results import (
    AnalyticalDatasetRun,
    PatternCandidateRecord,
)
from backend.app.models.silver_telemetry import (
    SilverChargerTelemetry,
)
from backend.app.repositories.events import EventRepository
from backend.app.repositories.research import ResearchRepository
from backend.app.schemas.research import (
    AnalyticalDatasetSummaryDTO,
    CorrelationEntryDTO,
    CorrelationMatrixDTO,
    DataReadinessDTO,
    FleetEDASummaryDTO,
    PatternCandidateDTO,
    PatternScanOutcomeDTO,
    SignalStatisticsDTO,
)
from backend.app.services.history_service import HistoricalContinuityService
from pipelines.research.dataset_builder import ResearchDatasetBuilder
from pipelines.research.fleet_profiler import FleetProfiler
from pipelines.research.models import PatternCandidate, SignalStatistics
from pipelines.research.pattern_scanner import PatternScanner
from pipelines.research.signal_statistician import SignalStatistician

logger = get_logger(__name__)

__all__ = ["ResearchService"]

# Signals to include in charger-level statistical analysis
_CHARGER_STAT_SIGNALS: list[str] = [
    "l1_n_voltage",
    "l2_n_voltage",
    "l3_n_voltage",
    "line_1_input_current",
    "line_2_input_current",
    "line_3_input_current",
    "frequency",
    "power_factor",
    "active_power",
    "cabinet_temperature",
    "ambient_temperature",
]


class ResearchService:
    """Phase 9 research orchestration: EDA, datasets, patterns."""

    def __init__(
        self,
        session: AsyncSession,
        history_service: HistoricalContinuityService,
        event_repo: EventRepository,
        research_repo: ResearchRepository,
    ) -> None:
        self._session = session
        self._history = history_service
        self._event_repo = event_repo
        self._research_repo = research_repo
        self._statistician = SignalStatistician()
        self._profiler = FleetProfiler(statistician=self._statistician)
        self._dataset_builder = ResearchDatasetBuilder(statistician=self._statistician)
        self._scanner = PatternScanner()

    # ------------------------------------------------------------------ EDA

    async def get_fleet_eda_summary(self) -> FleetEDASummaryDTO:
        """Build fleet-wide EDA summary from Silver and event tables."""
        # Count chargers
        charger_stmt = sa.select(sa.func.count(sa.distinct(SilverChargerTelemetry.charger_id)))
        charger_result = await self._session.execute(charger_stmt)
        total_chargers = charger_result.scalar_one()

        # Total observations
        obs_stmt = sa.select(sa.func.count(SilverChargerTelemetry.id))
        obs_result = await self._session.execute(obs_stmt)
        total_observations = obs_result.scalar_one()

        # Temporal span
        span_stmt = sa.select(
            sa.func.min(SilverChargerTelemetry.event_time),
            sa.func.max(SilverChargerTelemetry.event_time),
        )
        span_result = await self._session.execute(span_stmt)
        span_row = span_result.one()
        span_start, span_end = span_row[0], span_row[1]

        # Count sessions/alarms/faults from event repo
        from backend.app.models.discrete_events import (
            AlarmEvent,
            ChargingSessionEvent,
            FaultEvent,
        )

        sess_count = (
            await self._session.execute(sa.select(sa.func.count(ChargingSessionEvent.id)))
        ).scalar_one()
        alarm_count = (
            await self._session.execute(sa.select(sa.func.count(AlarmEvent.id)))
        ).scalar_one()
        fault_count = (
            await self._session.execute(sa.select(sa.func.count(FaultEvent.id)))
        ).scalar_one()

        # Count gaps
        from backend.app.models.telemetry_gap import TelemetryGap

        gap_count = (
            await self._session.execute(sa.select(sa.func.count(TelemetryGap.id)))
        ).scalar_one()

        # Pattern candidate count
        pattern_count = await self._research_repo.get_fleet_pattern_count()

        # Signal count
        signal_count = len(_CHARGER_STAT_SIGNALS)

        return FleetEDASummaryDTO(
            total_chargers=total_chargers,
            total_observations=total_observations,
            total_sessions=sess_count,
            total_alarms=alarm_count,
            total_faults=fault_count,
            total_gaps=gap_count,
            temporal_span_start=span_start,
            temporal_span_end=span_end,
            fleet_missing_rate=0.0,
            signal_count=signal_count,
            pattern_candidate_count=pattern_count,
        )

    # ------------------------------------------------------------------ signal stats

    async def get_signal_statistics(
        self,
        charger_id: str,
    ) -> list[SignalStatisticsDTO]:
        """Compute descriptive statistics for charger-level signals."""
        stmt = (
            sa.select(SilverChargerTelemetry)
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.asc(),
                SilverChargerTelemetry.frame_sequence.asc(),
            )
            .limit(10000)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return []

        # Gather values per signal
        signal_values: dict[str, list[Any]] = {sig: [] for sig in _CHARGER_STAT_SIGNALS}
        for row in rows:
            for sig in _CHARGER_STAT_SIGNALS:
                val = getattr(row, sig, None)
                signal_values[sig].append(val)

        # Compute stats
        results: list[SignalStatisticsDTO] = []
        for sig_name, values in signal_values.items():
            stats = self._statistician.compute_statistics(sig_name, values)
            results.append(_stats_to_dto(stats))

        return results

    # ------------------------------------------------------------------ correlations

    async def get_signal_correlations(
        self,
        charger_id: str,
        *,
        signal_names: list[str] | None = None,
    ) -> CorrelationMatrixDTO:
        """Compute cross-signal correlation matrix for a charger."""
        signals = signal_names or _CHARGER_STAT_SIGNALS

        stmt = (
            sa.select(SilverChargerTelemetry)
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.asc(),
                SilverChargerTelemetry.frame_sequence.asc(),
            )
            .limit(10000)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return CorrelationMatrixDTO(signal_names=signals, entries=[])

        signal_values: dict[str, list[float | None]] = {sig: [] for sig in signals}
        for row in rows:
            for sig in signals:
                val = getattr(row, sig, None)
                signal_values[sig].append(val)

        matrix = self._statistician.compute_correlation_matrix(signal_values)

        return CorrelationMatrixDTO(
            signal_names=list(matrix.signal_names),
            entries=[
                CorrelationEntryDTO(
                    signal_a=e.signal_a,
                    signal_b=e.signal_b,
                    pearson_r=e.pearson_r,
                    spearman_rho=e.spearman_rho,
                    sample_count=e.sample_count,
                )
                for e in matrix.entries
            ],
        )

    # ------------------------------------------------------------------ pattern scanning

    async def scan_patterns(
        self,
        charger_id: str,
    ) -> PatternScanOutcomeDTO:
        """Run pattern scanning for a charger and persist results."""
        t0 = time.monotonic()

        # 1) Get signal statistics
        signal_stats_dtos = await self.get_signal_statistics(charger_id)
        signal_stats: list[SignalStatistics] = [
            SignalStatistics(
                signal_name=s.signal_name,
                count=s.count,
                non_null_count=s.non_null_count,
                null_count=s.null_count,
                sentinel_count=s.sentinel_count,
                zero_count=s.zero_count,
                negative_count=s.negative_count,
                mean=s.mean,
                std=s.std,
                min_val=s.min_val,
                max_val=s.max_val,
                p05=s.p05,
                p25=s.p25,
                p50=s.p50,
                p75=s.p75,
                p95=s.p95,
                skewness=s.skewness,
                kurtosis=s.kurtosis,
                distinct_count=s.distinct_count,
                missing_rate=s.missing_rate,
            )
            for s in signal_stats_dtos
        ]

        # 2) Get session features
        sessions = await self._event_repo.get_sessions(charger_id=charger_id, limit=500)
        session_features = [
            {
                "energy_delivered_kwh": s.energy_delivered_kwh,
                "duration_seconds": s.duration_seconds,
                "start_soc": s.start_soc,
                "end_soc": s.end_soc,
                "connector_id": s.connector_id,
                "stop_reason": s.stop_reason,
                "termination_class": (str(s.termination_class) if s.termination_class else None),
                "confidence": str(s.confidence) if s.confidence else None,
                "has_gap": s.has_gap,
            }
            for s in sessions
        ]

        # 3) Get alarm events
        alarms = await self._event_repo.get_alarms(charger_id=charger_id, limit=500)
        alarm_events = [
            {
                "alarm_code": a.alarm_code,
                "start_time": a.start_time.isoformat() if a.start_time else None,
                "end_time": a.end_time.isoformat() if a.end_time else None,
                "severity": str(a.severity) if a.severity else None,
                "is_open": a.is_open,
            }
            for a in alarms
        ]

        # 4) Run scanner
        scan_result = self._scanner.scan(
            charger_id,
            signal_stats=signal_stats,
            session_features=session_features,
            alarm_events=alarm_events,
        )

        # 5) Persist results (clear old, save new)
        await self._research_repo.clear_patterns_for_charger(charger_id)

        db_records: list[PatternCandidateRecord] = []
        for cand in scan_result.candidates:
            db_records.append(_candidate_to_record(cand))

        persisted = await self._research_repo.save_pattern_candidates(db_records)
        await self._session.commit()

        scan_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "pattern_scan_complete",
            charger_id=charger_id,
            candidates_found=len(scan_result.candidates),
            persisted=persisted,
            scan_duration_ms=f"{scan_ms:.2f}",
        )

        return PatternScanOutcomeDTO(
            charger_id=charger_id,
            candidates_found=len(scan_result.candidates),
            candidates_persisted=persisted,
            scan_duration_ms=scan_ms,
            signals_scanned=scan_result.signals_scanned,
            records_analyzed=scan_result.records_analyzed,
            scan_version=scan_result.scan_version,
        )

    # ------------------------------------------------------------------ dataset build

    async def build_dataset(
        self,
        charger_id: str,
        grain: AnalyticalGrain = AnalyticalGrain.CHARGER_TIME,
    ) -> AnalyticalDatasetSummaryDTO:
        """Build an analytical dataset for a charger at the specified grain."""
        t0 = time.monotonic()

        # Fetch Silver observations
        stmt = (
            sa.select(SilverChargerTelemetry)
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.asc(),
                SilverChargerTelemetry.frame_sequence.asc(),
            )
            .limit(10000)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        observations = []
        for row in rows:
            obs: dict[str, Any] = {"event_time": row.event_time}
            for sig in _CHARGER_STAT_SIGNALS:
                obs[sig] = getattr(row, sig, None)
            observations.append(obs)

        # Build dataset
        dataset = self._dataset_builder.build_charger_time_dataset(charger_id, observations)

        # Persist run metadata
        run = AnalyticalDatasetRun(
            grain=grain,
            charger_id=charger_id,
            record_count=dataset.metadata.record_count,
            signal_count=dataset.metadata.signal_count,
            observation_window_start=dataset.metadata.window_start,
            observation_window_end=dataset.metadata.window_end,
            gap_count=dataset.metadata.gap_count,
            missing_rate=dataset.metadata.missing_rate,
            dataset_version=dataset.metadata.dataset_version,
            duration_ms=dataset.metadata.build_duration_ms,
        )
        await self._research_repo.save_dataset_run(run)
        await self._session.commit()

        build_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "dataset_build_complete",
            charger_id=charger_id,
            grain=grain,
            records=dataset.metadata.record_count,
            duration_ms=f"{build_ms:.2f}",
        )

        return AnalyticalDatasetSummaryDTO(
            grain=str(grain),
            charger_id=charger_id,
            record_count=dataset.metadata.record_count,
            signal_count=dataset.metadata.signal_count,
            window_start=dataset.metadata.window_start,
            window_end=dataset.metadata.window_end,
            gap_count=dataset.metadata.gap_count,
            missing_rate=dataset.metadata.missing_rate,
            dataset_version=dataset.metadata.dataset_version,
            build_duration_ms=build_ms,
        )

    # ------------------------------------------------------------------ pattern queries

    async def get_pattern_candidates(
        self,
        charger_id: str,
        *,
        pattern_category: str | None = None,
        evidence_level: str | None = None,
        min_confidence: float | None = None,
        limit: int = 200,
    ) -> list[PatternCandidateDTO]:
        """Retrieve persisted pattern candidates for a charger."""
        cat = None
        if pattern_category:
            try:
                from backend.app.models.enums import PatternCategory as PC

                cat = PC(pattern_category)
            except ValueError:
                pass

        evl = None
        if evidence_level:
            try:
                from backend.app.models.enums import (
                    PatternEvidenceLevel as PEL,
                )

                evl = PEL(evidence_level)
            except ValueError:
                pass

        records = await self._research_repo.get_patterns(
            charger_id,
            pattern_category=cat,
            evidence_level=evl,
            min_confidence=min_confidence,
            limit=limit,
        )

        return [_record_to_dto(r) for r in records]

    # ------------------------------------------------------------------ data readiness

    async def get_data_readiness(self) -> DataReadinessDTO:
        """Assess dataset readiness for future ML phases."""
        eda = await self.get_fleet_eda_summary()

        blockers: list[str] = []
        recommendations: list[str] = []

        # Temporal depth assessment
        temporal_depth = "SINGLE_SNAPSHOT"
        span_days = 0.0
        if eda.temporal_span_start and eda.temporal_span_end:
            delta = eda.temporal_span_end - eda.temporal_span_start
            span_days = delta.total_seconds() / 86400.0
            if span_days > 7:
                temporal_depth = "MULTI_DAY"
            if span_days > 30:
                temporal_depth = "LONGITUDINAL"

        if temporal_depth == "SINGLE_SNAPSHOT":
            blockers.append(
                "Single fleet snapshot: temporal pattern analysis requires "
                "longitudinal data across multiple days/weeks."
            )
            recommendations.append(
                "Ingest additional daily telemetry snapshots to build temporal depth."
            )

        if eda.total_chargers < 10:
            recommendations.append(
                f"Only {eda.total_chargers} chargers available. Fleet-level "
                "statistical analysis benefits from larger populations."
            )

        if eda.total_sessions == 0:
            blockers.append("Zero charging sessions reconstructed.")
        if eda.total_alarms == 0:
            recommendations.append(
                "Zero alarm events. Pattern scanning for alarm clustering is limited."
            )

        # Signal coverage
        coverage_rate = 1.0 - eda.fleet_missing_rate

        # Overall readiness
        overall = "READY"
        if blockers:
            overall = "NOT_READY" if len(blockers) >= 2 else "PARTIAL"

        return DataReadinessDTO(
            overall_readiness=overall,
            temporal_depth=temporal_depth,
            charger_count=eda.total_chargers,
            observation_count=eda.total_observations,
            signal_coverage_rate=coverage_rate,
            temporal_span_days=span_days,
            gap_rate=eda.total_gaps / max(eda.total_observations, 1),
            session_count=eda.total_sessions,
            alarm_count=eda.total_alarms,
            pattern_candidate_count=eda.pattern_candidate_count,
            blockers=blockers,
            recommendations=recommendations,
        )


# ------------------------------------------------------------------ helpers


def _stats_to_dto(stats: SignalStatistics) -> SignalStatisticsDTO:
    return SignalStatisticsDTO(
        signal_name=stats.signal_name,
        count=stats.count,
        non_null_count=stats.non_null_count,
        null_count=stats.null_count,
        sentinel_count=stats.sentinel_count,
        zero_count=stats.zero_count,
        negative_count=stats.negative_count,
        mean=stats.mean,
        std=stats.std,
        min_val=stats.min_val,
        max_val=stats.max_val,
        p05=stats.p05,
        p25=stats.p25,
        p50=stats.p50,
        p75=stats.p75,
        p95=stats.p95,
        skewness=stats.skewness,
        kurtosis=stats.kurtosis,
        distinct_count=stats.distinct_count,
        missing_rate=stats.missing_rate,
    )


def _candidate_to_record(cand: PatternCandidate) -> PatternCandidateRecord:
    return PatternCandidateRecord(
        charger_id=cand.charger_id,
        pattern_category=cand.pattern_category,
        evidence_level=cand.evidence_level,
        title=cand.title,
        description=cand.description,
        confidence_score=cand.confidence_score,
        affected_signals=list(cand.affected_signals),
        affected_components=list(cand.affected_components),
        observation_window_start=cand.observation_window_start,
        observation_window_end=cand.observation_window_end,
        supporting_evidence=[
            {
                "metric_name": e.metric_name,
                "observed_value": e.observed_value,
                "reference_value": e.reference_value,
                "threshold": e.threshold,
                "description": e.description,
            }
            for e in cand.supporting_evidence
        ],
        analytical_grain=cand.analytical_grain,
        dataset_version="v1",
        scan_version=cand.scan_version,
    )


def _record_to_dto(r: PatternCandidateRecord) -> PatternCandidateDTO:
    evidence = r.supporting_evidence
    ev_list: list[dict[str, Any]] = []
    if isinstance(evidence, list):
        ev_list = [e for e in evidence if isinstance(e, dict)]
    elif isinstance(evidence, dict):
        ev_list = [evidence]

    return PatternCandidateDTO(
        id=str(r.id),
        charger_id=r.charger_id,
        pattern_category=str(r.pattern_category),
        evidence_level=str(r.evidence_level),
        title=r.title,
        description=r.description,
        confidence_score=r.confidence_score,
        affected_signals=r.affected_signals or [],
        affected_components=r.affected_components or [],
        observation_window_start=r.observation_window_start,
        observation_window_end=r.observation_window_end,
        supporting_evidence=ev_list,
        analytical_grain=(str(r.analytical_grain) if r.analytical_grain else None),
        scan_version=r.scan_version,
        created_at=r.created_at,
    )
