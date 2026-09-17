"""Historical continuity domain service.

Coordinates unified time-series queries across multiple files and acquisition sources
without copying Silver data into separate redundant tables.
Authoritative ordering: event_time ASC, frame_sequence ASC.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.silver_telemetry import (
    SilverChargerTelemetry,
    SilverCommunicationObservation,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverLifecycleCounterObservation,
    SilverObservationProvenance,
    SilverRectifierTelemetry,
    SilverSmrTelemetry,
)
from backend.app.repositories.silver import SilverRepository
from backend.app.schemas.history import (
    ChargerContinuitySummaryDTO,
    ChargerHistoryResponse,
    ConfigurationSnapshotDTO,
    HistoricalGapDTO,
    HistoricalObservationDTO,
    PatternResearchEligibilityDTO,
    SamplingProfileDTO,
    SignalAvailabilityMatrixResponse,
    SignalHistoryResponse,
    SignalObservationDTO,
)
from pipelines.historical.counter_analyzer import CounterAnalysisReport, CounterAnalyzer
from pipelines.historical.eligibility_evaluator import (
    PatternResearchEligibilityEvaluator,
)
from pipelines.historical.gap_detector import GapDetector
from pipelines.historical.sampling_analyzer import SamplingAnalyzer
from pipelines.historical.topology_tracker import TopologyTracker

# Authoritative whitelist of permitted metrics for charger queries
CHARGER_METRIC_WHITELIST: frozenset[str] = frozenset(
    {
        "l1_n_voltage",
        "l2_n_voltage",
        "l3_n_voltage",
        "neutral_voltage",
        "line_1_input_current",
        "line_2_input_current",
        "line_3_input_current",
        "frequency",
        "power_factor",
        "active_power",
        "reactive_power",
        "apparent_power",
        "l1_l2_voltage",
        "l2_l3_voltage",
        "l3_l1_voltage",
        "cabinet_temperature",
        "ambient_temperature",
    }
)

CONNECTOR_METRIC_WHITELIST: frozenset[str] = frozenset(
    {
        "gun_temp_dc_positive",
        "gun_temp_dc_negative",
        "gun_voltage",
        "gun_insertion_cycle_count",
        "connector_status",
        "plug_status",
        "ccs_main_state",
        "ccs_sub_state",
    }
)

SMR_METRIC_WHITELIST: frozenset[str] = frozenset(
    {
        "smr_dc_dc_temperature",
        "smr_pfc_temperature",
        "smr_rectifierinternal_temp",
        "output_voltage",
        "output_current",
        "status",
    }
)

RECTIFIER_METRIC_WHITELIST: frozenset[str] = frozenset(
    {
        "rectifier_internal_temp",
        "rect_max_temperature",
        "all_rectifier_fail",
        "any_rect_fail",
        "no_of_active_rectifiers",
    }
)


class HistoricalContinuityService:
    """Provides bounded, provenance-backed historical telemetry queries."""

    def __init__(
        self,
        session: AsyncSession,
        silver_repo: SilverRepository,
        sampling_analyzer: SamplingAnalyzer | None = None,
        gap_detector: GapDetector | None = None,
        topology_tracker: TopologyTracker | None = None,
        counter_analyzer: CounterAnalyzer | None = None,
        eligibility_evaluator: PatternResearchEligibilityEvaluator | None = None,
    ) -> None:
        self._session = session
        self._silver_repo = silver_repo
        self._sampling_analyzer = sampling_analyzer or SamplingAnalyzer()
        self._gap_detector = gap_detector or GapDetector(sampling_analyzer=self._sampling_analyzer)
        self._topology_tracker = topology_tracker or TopologyTracker()
        self._counter_analyzer = counter_analyzer or CounterAnalyzer()
        self._eligibility_evaluator = eligibility_evaluator or PatternResearchEligibilityEvaluator()

    async def get_charger_history(
        self,
        charger_id: str,
        *,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        metrics: list[str] | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> ChargerHistoryResponse:
        """Query bounded cabinet-level telemetry strictly ordered by event_time, frame_sequence."""
        stmt = sa.select(SilverChargerTelemetry).where(
            SilverChargerTelemetry.charger_id == charger_id
        )

        if start_time is not None:
            stmt = stmt.where(SilverChargerTelemetry.event_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(SilverChargerTelemetry.event_time <= end_time)

        # Apply cursor pagination if present: format ISO_timestamp#sequence
        if cursor:
            try:
                c_time_str, c_seq_str = cursor.split("#", 1)
                c_time = dt.datetime.fromisoformat(c_time_str)
                c_seq = int(c_seq_str)
                stmt = stmt.where(
                    sa.or_(
                        SilverChargerTelemetry.event_time > c_time,
                        sa.and_(
                            SilverChargerTelemetry.event_time == c_time,
                            SilverChargerTelemetry.frame_sequence > c_seq,
                        ),
                    )
                )
            except (ValueError, TypeError):
                pass

        # Authoritative ordering: event_time ASC, frame_sequence ASC
        stmt = stmt.order_by(
            SilverChargerTelemetry.event_time.asc(),
            SilverChargerTelemetry.frame_sequence.asc(),
        ).limit(limit + 1)

        result = (await self._session.execute(stmt)).scalars().all()
        has_more = len(result) > limit
        records = result[:limit]

        # Filter metrics according to whitelist
        requested_metrics = (
            [m for m in metrics if m in CHARGER_METRIC_WHITELIST]
            if metrics
            else list(CHARGER_METRIC_WHITELIST)
        )

        observations: list[HistoricalObservationDTO] = []
        for r in records:
            metric_data: dict[str, Any] = {}
            for m in requested_metrics:
                if hasattr(r, m):
                    metric_data[m] = getattr(r, m)
            observations.append(
                HistoricalObservationDTO(
                    event_time=r.event_time,
                    frame_sequence=r.frame_sequence,
                    frame_id=r.frame_id,
                    metrics=metric_data,
                )
            )

        next_cursor: str | None = None
        if has_more and records:
            last_rec = records[-1]
            next_cursor = f"{last_rec.event_time.isoformat()}#{last_rec.frame_sequence}"

        return ChargerHistoryResponse(
            charger_id=charger_id,
            total_count=len(observations),
            observations=observations,
            next_cursor=next_cursor,
        )

    async def get_component_history(
        self,
        charger_id: str,
        component_type: str,
        component_id: int,
        *,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        metrics: list[str] | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> ChargerHistoryResponse:
        """Query bounded component-level telemetry ordered by event_time, frame_sequence."""
        comp = component_type.lower()
        model: Any
        id_col: Any
        if comp == "connector":
            model = SilverConnectorTelemetry
            id_col = SilverConnectorTelemetry.connector_id
            whitelist = CONNECTOR_METRIC_WHITELIST
        elif comp == "smr":
            model = SilverSmrTelemetry
            id_col = SilverSmrTelemetry.smr_id
            whitelist = SMR_METRIC_WHITELIST
        elif comp == "rectifier":
            model = SilverRectifierTelemetry
            id_col = SilverRectifierTelemetry.rectifier_id
            whitelist = RECTIFIER_METRIC_WHITELIST
        else:
            raise ValueError(f"Unsupported component_type: {component_type}")

        stmt = sa.select(model).where(
            model.charger_id == charger_id,
            id_col == component_id,
        )

        if start_time is not None:
            stmt = stmt.where(model.event_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(model.event_time <= end_time)

        if cursor:
            try:
                c_time_str, c_seq_str = cursor.split("#", 1)
                c_time = dt.datetime.fromisoformat(c_time_str)
                c_seq = int(c_seq_str)
                stmt = stmt.where(
                    sa.or_(
                        model.event_time > c_time,
                        sa.and_(
                            model.event_time == c_time,
                            model.frame_sequence > c_seq,
                        ),
                    )
                )
            except (ValueError, TypeError):
                pass

        stmt = stmt.order_by(model.event_time.asc(), model.frame_sequence.asc()).limit(limit + 1)
        result = (await self._session.execute(stmt)).scalars().all()
        has_more = len(result) > limit
        records = result[:limit]

        requested_metrics = [m for m in metrics if m in whitelist] if metrics else list(whitelist)

        observations: list[HistoricalObservationDTO] = []
        for r in records:
            metric_data: dict[str, Any] = {}
            for m in requested_metrics:
                if hasattr(r, m):
                    metric_data[m] = getattr(r, m)
            observations.append(
                HistoricalObservationDTO(
                    event_time=r.event_time,
                    frame_sequence=r.frame_sequence,
                    frame_id=r.frame_id,
                    metrics=metric_data,
                )
            )

        next_cursor: str | None = None
        if has_more and records:
            last_rec = records[-1]
            next_cursor = f"{last_rec.event_time.isoformat()}#{last_rec.frame_sequence}"

        return ChargerHistoryResponse(
            charger_id=charger_id,
            total_count=len(observations),
            observations=observations,
            next_cursor=next_cursor,
        )

    async def get_signal_history(
        self,
        charger_id: str,
        signal_name: str,
        *,
        component_type: str | None = None,
        component_id: int | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 5000,
    ) -> SignalHistoryResponse:
        """Query the raw normalized observations for a single canonical signal."""
        # Determine model from component_type or signal_name
        model: Any = SilverChargerTelemetry
        extra_filter: list[Any] = []

        comp = (component_type or "").lower()
        is_conn = (
            comp == "connector"
            or signal_name.startswith("gun_temp")
            or signal_name.startswith("connector")
        )
        if is_conn:
            model = SilverConnectorTelemetry
            if component_id is not None:
                extra_filter.append(SilverConnectorTelemetry.connector_id == component_id)
        elif comp == "smr" or signal_name.startswith("smr_") or signal_name.startswith("pfc_"):
            model = SilverSmrTelemetry
            if component_id is not None:
                extra_filter.append(SilverSmrTelemetry.smr_id == component_id)
        elif comp == "rectifier" or signal_name.startswith("rectifier_"):
            model = SilverRectifierTelemetry
            if component_id is not None:
                extra_filter.append(SilverRectifierTelemetry.rectifier_id == component_id)
        elif signal_name in ("rsrp", "rsrq", "rssi", "snr"):
            model = SilverCommunicationObservation
        elif signal_name.startswith("total_") or signal_name.endswith("_count"):
            model = SilverLifecycleCounterObservation

        # Check column existence
        if not hasattr(model, signal_name):
            # Fallback check on charger telemetry
            if hasattr(SilverChargerTelemetry, signal_name):
                model = SilverChargerTelemetry
                extra_filter = []
            else:
                return SignalHistoryResponse(
                    charger_id=charger_id,
                    component_type=component_type,
                    component_id=component_id,
                    signal_name=signal_name,
                    observation_count=0,
                    observations=[],
                )

        stmt = sa.select(model).where(model.charger_id == charger_id, *extra_filter)
        if start_time:
            stmt = stmt.where(model.event_time >= start_time)
        if end_time:
            stmt = stmt.where(model.event_time <= end_time)

        stmt = stmt.order_by(model.event_time.asc(), model.frame_sequence.asc()).limit(limit)
        records = (await self._session.execute(stmt)).scalars().all()

        # Query provenance to enrich with raw_value and masked_sentinel
        frame_ids = [r.frame_id for r in records]
        prov_map: dict[UUID, SilverObservationProvenance] = {}
        if frame_ids:
            prov_stmt = sa.select(SilverObservationProvenance).where(
                SilverObservationProvenance.frame_id.in_(frame_ids),
                SilverObservationProvenance.canonical_name == signal_name,
            )
            prov_records = (await self._session.execute(prov_stmt)).scalars().all()
            for p in prov_records:
                prov_map[p.frame_id] = p

        observations: list[SignalObservationDTO] = []
        for r in records:
            norm_val = getattr(r, signal_name, None)
            prov = prov_map.get(r.frame_id)
            raw_val_str = (
                prov.raw_value if prov else (str(norm_val) if norm_val is not None else None)
            )
            observations.append(
                SignalObservationDTO(
                    event_time=r.event_time,
                    frame_sequence=r.frame_sequence,
                    value=norm_val,
                    raw_value=raw_val_str,
                    masked_sentinel=prov.masked_sentinel if prov else False,
                )
            )

        return SignalHistoryResponse(
            charger_id=charger_id,
            component_type=component_type,
            component_id=component_id,
            signal_name=signal_name,
            observation_count=len(observations),
            observations=observations,
        )

    async def get_charger_continuity_summary(self, charger_id: str) -> ChargerContinuitySummaryDTO:
        """Derive multi-day descriptive continuity information for a charger."""
        # Query distinct timestamps and frame sequences
        time_stmt = (
            sa.select(
                SilverChargerTelemetry.event_time,
                SilverChargerTelemetry.frame_sequence,
            )
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.asc(),
                SilverChargerTelemetry.frame_sequence.asc(),
            )
        )
        time_rows = (await self._session.execute(time_stmt)).all()

        event_times = [r[0] for r in time_rows]
        sequences = [r[1] for r in time_rows]

        # Analyze sampling
        sampling_prof = self._sampling_analyzer.analyze(event_times, sequences)

        # Detect gaps
        gaps = self._gap_detector.detect_gaps(
            charger_id=charger_id,
            event_times=event_times,
            frame_sequences=sequences,
            sampling_profile=sampling_prof,
        )

        # Query observed connectors
        conn_stmt = (
            sa.select(sa.distinct(SilverConnectorTelemetry.connector_id))
            .where(SilverConnectorTelemetry.charger_id == charger_id)
            .order_by(SilverConnectorTelemetry.connector_id.asc())
        )
        connectors = list((await self._session.execute(conn_stmt)).scalars().all())

        # Query observed SMRs
        smr_stmt = (
            sa.select(sa.distinct(SilverSmrTelemetry.smr_id))
            .where(SilverSmrTelemetry.charger_id == charger_id)
            .order_by(SilverSmrTelemetry.smr_id.asc())
        )
        smrs = list((await self._session.execute(smr_stmt)).scalars().all())

        # Query observed rectifiers
        rect_stmt = (
            sa.select(sa.distinct(SilverRectifierTelemetry.rectifier_id))
            .where(SilverRectifierTelemetry.charger_id == charger_id)
            .order_by(SilverRectifierTelemetry.rectifier_id.asc())
        )
        rectifiers = list((await self._session.execute(rect_stmt)).scalars().all())

        # Query config versions count
        cfg_stmt = sa.select(
            sa.func.count(sa.distinct(SilverConfigurationSnapshot.config_hash))
        ).where(SilverConfigurationSnapshot.charger_id == charger_id)
        cfg_count = (await self._session.execute(cfg_stmt)).scalar() or 0

        # Calculate distinct active dates
        distinct_dates = {t.date() for t in event_times}
        active_days = len(distinct_dates)

        # Calculate age of latest observation
        latest_age: float | None = None
        if sampling_prof.last_event_time:
            now_utc = dt.datetime.now(dt.UTC)
            last_t = sampling_prof.last_event_time
            if last_t.tzinfo is None:
                last_t = last_t.replace(tzinfo=dt.UTC)
            latest_age = max(0.0, (now_utc - last_t).total_seconds())

        # Evaluate research eligibility
        eligibility = self._eligibility_evaluator.evaluate(
            charger_id=charger_id,
            profile=sampling_prof,
            gaps=gaps,
            signal_count=len(CHARGER_METRIC_WHITELIST) + len(SMR_METRIC_WHITELIST),
            active_days=active_days,
        )

        # Depth status
        if sampling_prof.observation_count == 0:
            depth_status = "NO_DATA"
        elif sampling_prof.observation_count == 1:
            depth_status = "SINGLE_OBSERVATION"
        else:
            depth_status = "MULTI_OBSERVATION"

        return ChargerContinuitySummaryDTO(
            charger_id=charger_id,
            first_seen=sampling_prof.first_event_time,
            last_seen=sampling_prof.last_event_time,
            observation_count=sampling_prof.observation_count,
            distinct_timestamps=sampling_prof.distinct_timestamps,
            observed_days=active_days,
            latest_observation_age_seconds=round(latest_age, 1) if latest_age is not None else None,
            connectors_observed=connectors,
            smrs_observed=smrs,
            rectifiers_observed=rectifiers,
            configuration_versions_count=cfg_count,
            sampling_profile=SamplingProfileDTO(
                observation_count=sampling_prof.observation_count,
                distinct_timestamps=sampling_prof.distinct_timestamps,
                first_event_time=sampling_prof.first_event_time,
                last_event_time=sampling_prof.last_event_time,
                coverage_duration_seconds=sampling_prof.coverage_duration_seconds,
                median_interval_seconds=sampling_prof.median_interval_seconds,
                p05_interval_seconds=sampling_prof.p05_interval_seconds,
                p95_interval_seconds=sampling_prof.p95_interval_seconds,
                min_interval_seconds=sampling_prof.min_interval_seconds,
                max_interval_seconds=sampling_prof.max_interval_seconds,
                expected_interval_seconds=sampling_prof.expected_interval_seconds,
                same_second_frame_count=sampling_prof.same_second_frame_count,
            ),
            gaps=[
                HistoricalGapDTO(
                    gap_start=g.gap_start,
                    gap_end=g.gap_end,
                    gap_duration_seconds=g.gap_duration_seconds,
                    previous_event_time=g.previous_event_time,
                    next_event_time=g.next_event_time,
                    expected_interval_seconds=g.expected_interval_seconds,
                    gap_multiple=g.gap_multiple,
                )
                for g in gaps
            ],
            pattern_eligibility=PatternResearchEligibilityDTO(
                charger_id=eligibility.charger_id,
                history_days=eligibility.history_days,
                observation_count=eligibility.observation_count,
                median_sampling_interval_seconds=eligibility.median_sampling_interval_seconds,
                largest_gap_seconds=eligibility.largest_gap_seconds,
                gap_count=eligibility.gap_count,
                signal_count=eligibility.signal_count,
                pattern_research_ready=eligibility.pattern_research_ready,
                reason=eligibility.reason,
            ),
            history_depth_status=depth_status,
        )

    async def get_configuration_timeline(self, charger_id: str) -> list[ConfigurationSnapshotDTO]:
        """Retrieve distinct configuration snapshot evolution ordered chronologically."""
        stmt = (
            sa.select(SilverConfigurationSnapshot)
            .where(SilverConfigurationSnapshot.charger_id == charger_id)
            .order_by(
                SilverConfigurationSnapshot.event_time.asc(),
                SilverConfigurationSnapshot.frame_sequence.asc(),
            )
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return [
            ConfigurationSnapshotDTO(
                event_time=r.event_time,
                frame_sequence=r.frame_sequence,
                config_hash=r.config_hash,
                raw_config_json=r.raw_config_json,
                charging_mode=r.charging_mode,
                charging_start_method=r.charging_start_method,
                charge_selected_mode=r.charge_selected_mode,
                ev_max_voltage_limit=r.ev_max_voltage_limit,
                ev_max_current_limit=r.ev_max_current_limit,
            )
            for r in records
        ]

    async def get_counter_history(
        self, charger_id: str, counter_name: str = "total_kwh_delivered"
    ) -> CounterAnalysisReport:
        """Inspect cumulative counter transitions without data repair."""
        stmt = (
            sa.select(SilverLifecycleCounterObservation)
            .where(SilverLifecycleCounterObservation.charger_id == charger_id)
            .order_by(
                SilverLifecycleCounterObservation.event_time.asc(),
                SilverLifecycleCounterObservation.frame_sequence.asc(),
            )
        )
        records = (await self._session.execute(stmt)).scalars().all()
        obs_dicts = [
            {
                "event_time": r.event_time,
                "frame_sequence": r.frame_sequence,
                "value": getattr(r, counter_name, None),
            }
            for r in records
        ]
        return self._counter_analyzer.analyze(charger_id, counter_name, obs_dicts)

    async def get_fleet_signal_availability_matrix(
        self, charger_ids: list[str] | None = None
    ) -> SignalAvailabilityMatrixResponse:
        """Build matrix of observed valid telemetry (not mere schema presence) across fleet."""
        # Key predictive signals to check
        signals = [
            "cabinet_temperature",
            "l1_n_voltage",
            "line_1_input_current",
            "frequency",
            "gun_temp_dc_positive",
            "gun_voltage",
            "smr_dc_dc_temperature",
            "rectifier_internal_temp",
            "rsrp",
            "ems_cumulative_energy",
        ]

        # Determine target chargers
        if not charger_ids:
            c_stmt = sa.select(sa.distinct(SilverChargerTelemetry.charger_id)).limit(50)
            charger_ids = list((await self._session.execute(c_stmt)).scalars().all())

        matrix: dict[str, dict[str, bool]] = {cid: {} for cid in charger_ids}

        for cid in charger_ids:
            # Cabinet signals
            ch_stmt = (
                sa.select(
                    SilverChargerTelemetry.cabinet_temperature,
                    SilverChargerTelemetry.l1_n_voltage,
                    SilverChargerTelemetry.line_1_input_current,
                    SilverChargerTelemetry.frequency,
                )
                .where(SilverChargerTelemetry.charger_id == cid)
                .limit(1)
            )
            ch_row = (await self._session.execute(ch_stmt)).first()

            matrix[cid]["cabinet_temperature"] = ch_row[0] is not None if ch_row else False
            matrix[cid]["l1_n_voltage"] = ch_row[1] is not None if ch_row else False
            matrix[cid]["line_1_input_current"] = ch_row[2] is not None if ch_row else False
            matrix[cid]["frequency"] = ch_row[3] is not None if ch_row else False

            # Connector signals
            conn_stmt = (
                sa.select(
                    SilverConnectorTelemetry.gun_temp_dc_positive,
                    SilverConnectorTelemetry.gun_voltage,
                )
                .where(SilverConnectorTelemetry.charger_id == cid)
                .limit(1)
            )
            conn_row = (await self._session.execute(conn_stmt)).first()
            matrix[cid]["gun_temp_dc_positive"] = conn_row[0] is not None if conn_row else False
            matrix[cid]["gun_voltage"] = conn_row[1] is not None if conn_row else False

            # SMR
            smr_stmt = (
                sa.select(SilverSmrTelemetry.smr_dc_dc_temperature)
                .where(SilverSmrTelemetry.charger_id == cid)
                .limit(1)
            )
            smr_row = (await self._session.execute(smr_stmt)).first()
            matrix[cid]["smr_dc_dc_temperature"] = smr_row[0] is not None if smr_row else False

            # Rectifier
            rect_stmt = (
                sa.select(SilverRectifierTelemetry.rectifier_internal_temp)
                .where(SilverRectifierTelemetry.charger_id == cid)
                .limit(1)
            )
            rect_row = (await self._session.execute(rect_stmt)).first()
            has_rect_temp = rect_row[0] is not None if rect_row else False
            matrix[cid]["rectifier_internal_temp"] = has_rect_temp

            # Communication (RSRP)
            comm_stmt = (
                sa.select(SilverCommunicationObservation.rsrp)
                .where(SilverCommunicationObservation.charger_id == cid)
                .limit(1)
            )
            comm_row = (await self._session.execute(comm_stmt)).first()
            matrix[cid]["rsrp"] = comm_row[0] is not None if comm_row else False

            # Counters
            cnt_stmt = (
                sa.select(SilverLifecycleCounterObservation.ems_cumulative_energy)
                .where(SilverLifecycleCounterObservation.charger_id == cid)
                .limit(1)
            )
            cnt_row = (await self._session.execute(cnt_stmt)).first()
            matrix[cid]["ems_cumulative_energy"] = cnt_row[0] is not None if cnt_row else False

        return SignalAvailabilityMatrixResponse(
            signals=signals,
            matrix=matrix,
        )
