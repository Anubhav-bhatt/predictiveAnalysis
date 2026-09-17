"""Event reconstruction domain service (Phase 8).

Orchestrates loading ordered Silver history, invoking pure event reconstructors,
managing windowed recomputation for late-arriving data, ensuring idempotency,
and constructing unified chronological operational timelines.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.discrete_events import (
    AlarmEvent,
    ChargingSessionEvent,
    FaultEvent,
)
from backend.app.models.enums import AlarmSeverity, EventConfidence, EventType
from backend.app.models.silver_telemetry import (
    SilverAlarmObservation,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverSessionObservation,
)
from backend.app.repositories.events import EventRepository
from backend.app.schemas.events import (
    EventReconstructionOutcome,
    UnifiedEventTimelineItem,
)
from backend.app.services.history_service import HistoricalContinuityService
from pipelines.events.alarm_reconstructor import (
    AlarmObservation,
    AlarmReconstructor,
    is_active_state,
)
from pipelines.events.config_change_detector import (
    ConfigSnapshotObservation,
    ConfigurationChangeDetector,
)
from pipelines.events.models import TelemetryGapInterval
from pipelines.events.session_reconstructor import (
    ConnectorObservation,
    SessionReconstructor,
)
from pipelines.events.state_transition_detector import (
    StateObservation,
    StateTransitionDetector,
)
from pipelines.historical.gap_detector import GapDetector
from pipelines.historical.sampling_analyzer import SamplingAnalyzer

logger = get_logger(__name__)

__all__ = ["EventReconstructionService"]


class EventReconstructionService:
    """Domain service for discrete operational event reconstruction and timeline delivery."""

    def __init__(
        self,
        session: AsyncSession,
        history_service: HistoricalContinuityService,
        version: str = "v1",
    ) -> None:
        self.session = session
        self.history_service = history_service
        self.version = version
        self.event_repo = EventRepository(session)
        self.session_reconstructor = SessionReconstructor(version=version)
        self.alarm_reconstructor = AlarmReconstructor(version=version)
        self.config_detector = ConfigurationChangeDetector(version=version)
        self.state_detector = StateTransitionDetector()

    async def reconstruct_charger_events(
        self,
        charger_id: str,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
    ) -> EventReconstructionOutcome:
        """Run complete discrete event reconstruction for a charger."""
        t_start = time.perf_counter()

        # 1. Fetch detected telemetry gaps for gap-aware duration semantics
        gaps: list[TelemetryGapInterval] = []
        try:
            summary = await self.history_service.get_charger_continuity_summary(charger_id)
            for g in summary.gaps:
                gaps.append(TelemetryGapInterval(start_time=g.gap_start, end_time=g.gap_end))
        except Exception as exc:
            logger.debug("Failed to retrieve historical gaps: %s", exc)

        # If summary had no gaps, check if gaps exist directly from connector telemetry
        if not gaps:
            conn_time_stmt = (
                sa.select(
                    SilverConnectorTelemetry.event_time,
                    SilverConnectorTelemetry.frame_sequence,
                )
                .where(SilverConnectorTelemetry.charger_id == charger_id)
                .order_by(
                    SilverConnectorTelemetry.event_time.asc(),
                    SilverConnectorTelemetry.frame_sequence.asc(),
                )
            )
            c_rows = (await self.session.execute(conn_time_stmt)).all()
            if len(c_rows) >= 2:
                detector = GapDetector()
                analyzer = SamplingAnalyzer()
                c_times = [r[0] for r in c_rows]
                c_seqs = [r[1] for r in c_rows]
                c_prof = analyzer.analyze(c_times, c_seqs)
                c_gaps = detector.detect_gaps(
                    charger_id=charger_id,
                    event_times=c_times,
                    frame_sequences=c_seqs,
                    sampling_profile=c_prof,
                )
                for cg in c_gaps:
                    gaps.append(TelemetryGapInterval(start_time=cg.gap_start, end_time=cg.gap_end))

        # 2. Reconstruct Charging Sessions
        sessions_to_save = []
        state_transitions_to_save = []

        # Find distinct connectors for this charger
        conn_stmt = (
            sa.select(SilverConnectorTelemetry.connector_id)
            .where(SilverConnectorTelemetry.charger_id == charger_id)
            .distinct()
        )
        connector_ids = (await self.session.execute(conn_stmt)).scalars().all() or [1]

        for conn_id in connector_ids:
            # Query connector telemetry ordered by time ASC, seq ASC
            c_stmt = sa.select(SilverConnectorTelemetry).where(
                SilverConnectorTelemetry.charger_id == charger_id,
                SilverConnectorTelemetry.connector_id == conn_id,
            )
            if start_time:
                c_stmt = c_stmt.where(SilverConnectorTelemetry.event_time >= start_time)
            if end_time:
                c_stmt = c_stmt.where(SilverConnectorTelemetry.event_time <= end_time)
            c_stmt = c_stmt.order_by(
                SilverConnectorTelemetry.event_time.asc(),
                SilverConnectorTelemetry.frame_sequence.asc(),
            )
            conn_rows = (await self.session.execute(c_stmt)).scalars().all()

            # Query session observations for this connector
            s_stmt = sa.select(SilverSessionObservation).where(
                SilverSessionObservation.charger_id == charger_id,
                SilverSessionObservation.connector_id == conn_id,
            )
            if start_time:
                s_stmt = s_stmt.where(SilverSessionObservation.event_time >= start_time)
            if end_time:
                s_stmt = s_stmt.where(SilverSessionObservation.event_time <= end_time)
            s_stmt = s_stmt.order_by(
                SilverSessionObservation.event_time.asc(),
                SilverSessionObservation.frame_sequence.asc(),
            )
            sess_rows = (await self.session.execute(s_stmt)).scalars().all()
            sess_map = {(s.event_time, s.frame_sequence): s for s in sess_rows}

            # Build ConnectorObservation list
            obs_list: list[ConnectorObservation] = []
            state_obs_list: list[StateObservation] = []

            for c in conn_rows:
                key = (c.event_time, c.frame_sequence)
                s = sess_map.get(key)
                obs_list.append(
                    ConnectorObservation(
                        event_time=c.event_time,
                        frame_sequence=c.frame_sequence,
                        frame_id=c.frame_id,
                        connector_status=c.connector_status,
                        plug_status=c.plug_status,
                        session_id=str(s.session_id) if s and s.session_id is not None else None,
                        begin_time=s.begin_time if s else None,
                        session_consumed_energy=s.session_consumed_energy if s else None,
                        session_output_voltage=s.session_output_voltage if s else None,
                        session_output_current=s.session_output_current if s else None,
                        start_soc=s.start_soc if s else None,
                        stop_soc=s.stop_soc if s else None,
                        stop_reason=s.stop_reason if s else None,
                    )
                )
                if c.connector_status:
                    state_obs_list.append(
                        StateObservation(
                            event_time=c.event_time,
                            frame_sequence=c.frame_sequence,
                            state_val=c.connector_status,
                            frame_id=c.frame_id,
                        )
                    )

            # Reconstruct sessions for this connector
            reconstructed_sessions = self.session_reconstructor.reconstruct(
                charger_id=charger_id,
                connector_id=conn_id,
                observations=obs_list,
                gaps=gaps,
            )
            sessions_to_save.extend(reconstructed_sessions)

            # State transitions
            transitions = self.state_detector.detect_transitions(
                charger_id=charger_id,
                component_type="connector",
                component_id=conn_id,
                state_field="connector_status",
                observations=state_obs_list,
            )
            state_transitions_to_save.extend(transitions)

        # 3. Reconstruct Alarms and Faults
        alarms_to_save = []
        faults_to_save = []

        a_stmt = sa.select(SilverAlarmObservation).where(
            SilverAlarmObservation.charger_id == charger_id
        )
        if start_time:
            a_stmt = a_stmt.where(SilverAlarmObservation.event_time >= start_time)
        if end_time:
            a_stmt = a_stmt.where(SilverAlarmObservation.event_time <= end_time)
        a_stmt = a_stmt.order_by(
            SilverAlarmObservation.event_time.asc(),
            SilverAlarmObservation.frame_sequence.asc(),
        )
        alarm_rows = (await self.session.execute(a_stmt)).scalars().all()

        alarm_fields = [
            ("smoke_alarm", "Smoke Alarm", AlarmSeverity.CRITICAL, False),
            ("emergency_stop_active", "Emergency Stop Active", AlarmSeverity.CRITICAL, False),
            ("grid_fail", "Grid Fail", AlarmSeverity.MAJOR, False),
            ("door_open", "Door Open", AlarmSeverity.MINOR, False),
            ("short_circuit", "Short Circuit", AlarmSeverity.CRITICAL, True),
            ("ground_fault_alarm", "Ground Fault Alarm", AlarmSeverity.CRITICAL, True),
            ("input_rcbo_tripped", "Input RCBO Tripped", AlarmSeverity.MAJOR, True),
            ("mccb_tripped", "MCCB Tripped", AlarmSeverity.MAJOR, True),
            ("mdl_fault", "MDL Fault", AlarmSeverity.CRITICAL, True),
            ("fan_fault", "Fan Fault", AlarmSeverity.MAJOR, True),
        ]

        for field_code, field_name, severity, is_fault in alarm_fields:
            field_obs: list[AlarmObservation] = []
            for r in alarm_rows:
                val = getattr(r, field_code, None)
                active = is_active_state(val)
                field_obs.append(
                    AlarmObservation(
                        event_time=r.event_time,
                        frame_sequence=r.frame_sequence,
                        frame_id=r.frame_id,
                        is_active=active,
                        state_str=str(val) if val is not None else None,
                    )
                )

            if is_fault:
                faults = self.alarm_reconstructor.reconstruct_faults(
                    charger_id=charger_id,
                    fault_code=field_code,
                    fault_name=field_name,
                    component_type="cabinet",
                    component_id=None,
                    observations=field_obs,
                    gaps=gaps,
                )
                faults_to_save.extend(faults)
            else:
                alarms = self.alarm_reconstructor.reconstruct_alarms(
                    charger_id=charger_id,
                    alarm_code=field_code,
                    alarm_name=field_name,
                    component_type="cabinet",
                    component_id=None,
                    observations=field_obs,
                    gaps=gaps,
                    severity=severity,
                )
                alarms_to_save.extend(alarms)

        # 4. Reconstruct Configuration Changes
        cfg_stmt = sa.select(SilverConfigurationSnapshot).where(
            SilverConfigurationSnapshot.charger_id == charger_id
        )
        if start_time:
            cfg_stmt = cfg_stmt.where(SilverConfigurationSnapshot.event_time >= start_time)
        if end_time:
            cfg_stmt = cfg_stmt.where(SilverConfigurationSnapshot.event_time <= end_time)
        cfg_stmt = cfg_stmt.order_by(SilverConfigurationSnapshot.event_time.asc())
        cfg_rows = (await self.session.execute(cfg_stmt)).scalars().all()

        cfg_obs = [
            ConfigSnapshotObservation(
                event_time=c.event_time,
                config_hash=c.config_hash,
                config_json=c.raw_config_json or {},
            )
            for c in cfg_rows
        ]
        config_changes_to_save = self.config_detector.detect_changes(charger_id, cfg_obs)

        # 5. Clear window and persist all reconstructed events (idempotent recomputation)
        await self.event_repo.clear_events_in_window(
            charger_id=charger_id,
            start_time=start_time,
            end_time=end_time,
            version=self.version,
        )

        await self.event_repo.save_sessions(sessions_to_save)
        await self.event_repo.save_alarms(alarms_to_save)
        await self.event_repo.save_faults(faults_to_save)
        await self.event_repo.save_state_transitions(state_transitions_to_save)
        await self.event_repo.save_config_changes(config_changes_to_save)

        await self.session.commit()

        duration_ms = (time.perf_counter() - t_start) * 1000.0

        return EventReconstructionOutcome(
            charger_id=charger_id,
            sessions_reconstructed=len(sessions_to_save),
            alarms_reconstructed=len(alarms_to_save),
            faults_reconstructed=len(faults_to_save),
            state_transitions_reconstructed=len(state_transitions_to_save),
            configuration_changes_reconstructed=len(config_changes_to_save),
            reconstruction_duration_ms=duration_ms,
        )

    async def get_sessions(
        self,
        charger_id: str,
        connector_id: int | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ChargingSessionEvent]:
        """Fetch charging sessions for a charger."""
        return await self.event_repo.get_sessions(
            charger_id=charger_id,
            connector_id=connector_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )

    async def get_alarms(
        self,
        charger_id: str,
        alarm_code: str | None = None,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[AlarmEvent]:
        """Fetch alarm events for a charger."""
        return await self.event_repo.get_alarms(
            charger_id=charger_id,
            alarm_code=alarm_code,
            is_open=is_open,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_faults(
        self,
        charger_id: str,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[FaultEvent]:
        """Fetch fault events for a charger."""
        return await self.event_repo.get_faults(
            charger_id=charger_id,
            is_open=is_open,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_unified_timeline(
        self,
        charger_id: str,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> list[UnifiedEventTimelineItem]:
        """Combine operational events into a chronological stream."""
        sessions = await self.event_repo.get_sessions(
            charger_id, start_time=start_time, end_time=end_time, limit=limit
        )
        alarms = await self.event_repo.get_alarms(
            charger_id, start_time=start_time, end_time=end_time, limit=limit
        )
        faults = await self.event_repo.get_faults(
            charger_id, start_time=start_time, end_time=end_time, limit=limit
        )
        configs = await self.event_repo.get_config_changes(
            charger_id, start_time=start_time, end_time=end_time, limit=limit
        )

        items: list[UnifiedEventTimelineItem] = []

        for s in sessions:
            energy_str = (
                f"{s.energy_delivered_kwh:.1f} kWh" if s.energy_delivered_kwh is not None else "N/A"
            )
            term_str = s.termination_class.value if s.termination_class else "N/A"
            items.append(
                UnifiedEventTimelineItem(
                    event_id=s.id,
                    event_type=EventType.CHARGING_SESSION,
                    event_time=s.start_time,
                    end_time=s.end_time,
                    title=f"Charging Session (Connector {s.connector_id})",
                    description=(
                        f"Energy: {energy_str} | Reason: {s.stop_reason or 'Normal'} "
                        f"| Term: {term_str}"
                    ),
                    component=f"connector_{s.connector_id}",
                    severity="INFO",
                    duration_seconds=s.duration_seconds,
                    is_open=s.end_time is None,
                    has_gap=s.has_gap,
                    confidence=s.confidence,
                    metadata={
                        "session_id": s.session_id,
                        "start_soc": s.start_soc,
                        "end_soc": s.end_soc,
                    },
                )
            )

        for a in alarms:
            end_st = a.end_state or "active"
            items.append(
                UnifiedEventTimelineItem(
                    event_id=a.id,
                    event_type=EventType.ALARM_EVENT,
                    event_time=a.start_time,
                    end_time=a.end_time,
                    title=f"Alarm: {a.alarm_name}",
                    description=(
                        f"Severity: {a.severity.value} | State: {a.start_state} -> {end_st}"
                    ),
                    component=a.component_type,
                    severity=a.severity.value,
                    duration_seconds=a.duration_seconds,
                    is_open=a.is_open,
                    has_gap=a.has_gap,
                    confidence=a.confidence,
                    metadata={"alarm_code": a.alarm_code},
                )
            )

        for f in faults:
            clr_st = f.clearing_reading or "active"
            items.append(
                UnifiedEventTimelineItem(
                    event_id=f.id,
                    event_type=EventType.FAULT_EVENT,
                    event_time=f.start_time,
                    end_time=f.end_time,
                    title=f"Fault Trip: {f.fault_name}",
                    description=f"Initial: {f.initial_reading} | Clearing: {clr_st}",
                    component=f.component_type,
                    severity="CRITICAL",
                    duration_seconds=f.duration_seconds,
                    is_open=f.is_open,
                    has_gap=f.has_gap,
                    confidence=f.confidence,
                    metadata={"fault_code": f.fault_code},
                )
            )

        for c in configs:
            items.append(
                UnifiedEventTimelineItem(
                    event_id=c.id,
                    event_type=EventType.CONFIGURATION_CHANGE,
                    event_time=c.change_time,
                    end_time=None,
                    title="Configuration Parameter Change",
                    description=f"Changed fields: {', '.join(c.changed_fields_json.keys())}",
                    component="configuration",
                    severity="INFO",
                    duration_seconds=0.0,
                    is_open=False,
                    has_gap=False,
                    confidence=EventConfidence.HIGH,
                    metadata={
                        "old_hash": c.old_config_hash[:8],
                        "new_hash": c.new_config_hash[:8],
                        "diff": c.changed_fields_json,
                    },
                )
            )

        # Sort all events chronologically
        items.sort(key=lambda x: x.event_time)
        return items[:limit]
