"""Event data repository (Phase 8).

Handles persistence, windowed recomputation, and queries for reconstructed discrete events:
charging sessions, alarm spans, protection faults, state transitions, and configuration changes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.discrete_events import (
    AlarmEvent,
    ChargingSessionEvent,
    ConfigurationChangeEvent,
    FaultEvent,
    StateTransitionEvent,
)
from pipelines.events.models import (
    ReconstructedAlarm,
    ReconstructedConfigChange,
    ReconstructedFault,
    ReconstructedSession,
    ReconstructedStateTransition,
)

__all__ = ["EventRepository"]


class EventRepository:
    """Async database repository for discrete operational events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def clear_events_in_window(
        self,
        charger_id: str,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        version: str = "v1",
    ) -> None:
        """Clear existing events in a temporal window before recomputing for late-arriving data."""
        # Sessions
        sess_stmt = sa.delete(ChargingSessionEvent).where(
            ChargingSessionEvent.charger_id == charger_id,
            ChargingSessionEvent.reconstruction_version == version,
        )
        if start_time:
            sess_stmt = sess_stmt.where(ChargingSessionEvent.start_time >= start_time)
        if end_time:
            sess_stmt = sess_stmt.where(ChargingSessionEvent.start_time <= end_time)
        await self.session.execute(sess_stmt)

        # Alarms
        alarm_stmt = sa.delete(AlarmEvent).where(
            AlarmEvent.charger_id == charger_id,
            AlarmEvent.reconstruction_version == version,
        )
        if start_time:
            alarm_stmt = alarm_stmt.where(AlarmEvent.start_time >= start_time)
        if end_time:
            alarm_stmt = alarm_stmt.where(AlarmEvent.start_time <= end_time)
        await self.session.execute(alarm_stmt)

        # Faults
        fault_stmt = sa.delete(FaultEvent).where(
            FaultEvent.charger_id == charger_id,
            FaultEvent.reconstruction_version == version,
        )
        if start_time:
            fault_stmt = fault_stmt.where(FaultEvent.start_time >= start_time)
        if end_time:
            fault_stmt = fault_stmt.where(FaultEvent.start_time <= end_time)
        await self.session.execute(fault_stmt)

        # State transitions
        trans_stmt = sa.delete(StateTransitionEvent).where(
            StateTransitionEvent.charger_id == charger_id
        )
        if start_time:
            trans_stmt = trans_stmt.where(StateTransitionEvent.transition_time >= start_time)
        if end_time:
            trans_stmt = trans_stmt.where(StateTransitionEvent.transition_time <= end_time)
        await self.session.execute(trans_stmt)

        # Config changes
        conf_stmt = sa.delete(ConfigurationChangeEvent).where(
            ConfigurationChangeEvent.charger_id == charger_id,
            ConfigurationChangeEvent.reconstruction_version == version,
        )
        if start_time:
            conf_stmt = conf_stmt.where(ConfigurationChangeEvent.change_time >= start_time)
        if end_time:
            conf_stmt = conf_stmt.where(ConfigurationChangeEvent.change_time <= end_time)
        await self.session.execute(conf_stmt)

    async def save_sessions(self, sessions: Sequence[ReconstructedSession]) -> None:
        """Persist reconstructed charging session events."""
        for s in sessions:
            event = ChargingSessionEvent(
                charger_id=s.charger_id,
                connector_id=s.connector_id,
                session_id=s.session_id,
                start_time=s.start_time,
                charging_start_time=s.charging_start_time,
                charging_end_time=s.charging_end_time,
                end_time=s.end_time,
                duration_seconds=s.duration_seconds,
                energy_delivered_kwh=s.energy_delivered_kwh,
                start_soc=s.start_soc,
                end_soc=s.end_soc,
                stop_reason=s.stop_reason,
                termination_class=s.termination_class,
                confidence=s.confidence,
                has_gap=s.has_gap,
                quality_flags=list(s.quality_flags) if s.quality_flags else None,
                evidence=s.evidence,
                reconstruction_version=s.reconstruction_version,
                source_first_frame_id=s.source_first_frame_id,
                source_last_frame_id=s.source_last_frame_id,
            )
            self.session.add(event)

    async def save_alarms(self, alarms: Sequence[ReconstructedAlarm]) -> None:
        """Persist reconstructed alarm interval events."""
        for a in alarms:
            event = AlarmEvent(
                charger_id=a.charger_id,
                alarm_code=a.alarm_code,
                alarm_name=a.alarm_name,
                component_type=a.component_type,
                component_id=a.component_id,
                severity=a.severity,
                start_time=a.start_time,
                end_time=a.end_time,
                duration_seconds=a.duration_seconds,
                is_open=a.is_open,
                start_state=a.start_state,
                end_state=a.end_state,
                confidence=a.confidence,
                has_gap=a.has_gap,
                quality_flags=list(a.quality_flags) if a.quality_flags else None,
                reconstruction_version=a.reconstruction_version,
                source_first_frame_id=a.source_first_frame_id,
                source_last_frame_id=a.source_last_frame_id,
            )
            self.session.add(event)

    async def save_faults(self, faults: Sequence[ReconstructedFault]) -> None:
        """Persist reconstructed fault events."""
        for f in faults:
            event = FaultEvent(
                charger_id=f.charger_id,
                fault_code=f.fault_code,
                fault_name=f.fault_name,
                component_type=f.component_type,
                component_id=f.component_id,
                start_time=f.start_time,
                end_time=f.end_time,
                duration_seconds=f.duration_seconds,
                is_open=f.is_open,
                initial_reading=f.initial_reading,
                clearing_reading=f.clearing_reading,
                confidence=f.confidence,
                has_gap=f.has_gap,
                quality_flags=list(f.quality_flags) if f.quality_flags else None,
                reconstruction_version=f.reconstruction_version,
                source_first_frame_id=f.source_first_frame_id,
                source_last_frame_id=f.source_last_frame_id,
            )
            self.session.add(event)

    async def save_state_transitions(
        self, transitions: Sequence[ReconstructedStateTransition]
    ) -> None:
        """Persist state transition events."""
        for t in transitions:
            event = StateTransitionEvent(
                charger_id=t.charger_id,
                component_type=t.component_type,
                component_id=t.component_id,
                state_field=t.state_field,
                from_state=t.from_state,
                to_state=t.to_state,
                transition_time=t.transition_time,
                frame_sequence=t.frame_sequence,
                frame_id=t.frame_id,
            )
            self.session.add(event)

    async def save_config_changes(self, changes: Sequence[ReconstructedConfigChange]) -> None:
        """Persist configuration change events."""
        for c in changes:
            event = ConfigurationChangeEvent(
                charger_id=c.charger_id,
                change_time=c.change_time,
                old_config_hash=c.old_config_hash,
                new_config_hash=c.new_config_hash,
                changed_fields_json=c.changed_fields_json,
                previous_config_json=c.previous_config_json,
                new_config_json=c.new_config_json,
                reconstruction_version=c.reconstruction_version,
            )
            self.session.add(event)

    async def get_sessions(
        self,
        charger_id: str,
        connector_id: int | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ChargingSessionEvent]:
        """Query charging session events ordered by start_time."""
        stmt = sa.select(ChargingSessionEvent).where(ChargingSessionEvent.charger_id == charger_id)
        if connector_id is not None:
            stmt = stmt.where(ChargingSessionEvent.connector_id == connector_id)
        if start_time is not None:
            stmt = stmt.where(ChargingSessionEvent.start_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(ChargingSessionEvent.start_time <= end_time)
        stmt = stmt.order_by(ChargingSessionEvent.start_time.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_alarms(
        self,
        charger_id: str,
        alarm_code: str | None = None,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[AlarmEvent]:
        """Query alarm events ordered by start_time."""
        stmt = sa.select(AlarmEvent).where(AlarmEvent.charger_id == charger_id)
        if alarm_code is not None:
            stmt = stmt.where(AlarmEvent.alarm_code == alarm_code)
        if is_open is not None:
            stmt = stmt.where(AlarmEvent.is_open == is_open)
        if start_time is not None:
            stmt = stmt.where(AlarmEvent.start_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(AlarmEvent.start_time <= end_time)
        stmt = stmt.order_by(AlarmEvent.start_time.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_faults(
        self,
        charger_id: str,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[FaultEvent]:
        """Query fault events ordered by start_time."""
        stmt = sa.select(FaultEvent).where(FaultEvent.charger_id == charger_id)
        if is_open is not None:
            stmt = stmt.where(FaultEvent.is_open == is_open)
        if start_time is not None:
            stmt = stmt.where(FaultEvent.start_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(FaultEvent.start_time <= end_time)
        stmt = stmt.order_by(FaultEvent.start_time.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_state_transitions(
        self,
        charger_id: str,
        state_field: str | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[StateTransitionEvent]:
        """Query discrete state transitions ordered by transition_time and sequence."""
        stmt = sa.select(StateTransitionEvent).where(StateTransitionEvent.charger_id == charger_id)
        if state_field is not None:
            stmt = stmt.where(StateTransitionEvent.state_field == state_field)
        if start_time is not None:
            stmt = stmt.where(StateTransitionEvent.transition_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(StateTransitionEvent.transition_time <= end_time)
        stmt = stmt.order_by(
            StateTransitionEvent.transition_time.asc(), StateTransitionEvent.frame_sequence.asc()
        ).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_config_changes(
        self,
        charger_id: str,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 50,
    ) -> Sequence[ConfigurationChangeEvent]:
        """Query configuration change events ordered by change_time."""
        stmt = sa.select(ConfigurationChangeEvent).where(
            ConfigurationChangeEvent.charger_id == charger_id
        )
        if start_time is not None:
            stmt = stmt.where(ConfigurationChangeEvent.change_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(ConfigurationChangeEvent.change_time <= end_time)
        stmt = stmt.order_by(ConfigurationChangeEvent.change_time.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
