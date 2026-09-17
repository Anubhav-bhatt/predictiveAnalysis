"""Research Data Access Layer for time-series pattern discovery (Phase 9 preparation).

Provides programmatic retrieval of canonical Silver telemetry signals and reconstructed
operational events (sessions, alarms, faults, state transitions, config changes).
STRICT INVARIANT: Preserves original asynchronous observation timestamps across signals;
zero artificial grid-resampling, zero interpolation, zero imputation.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.models.discrete_events import (
    AlarmEvent,
    ChargingSessionEvent,
    ConfigurationChangeEvent,
    FaultEvent,
    StateTransitionEvent,
)
from backend.app.repositories.events import EventRepository
from backend.app.services.history_service import HistoricalContinuityService

__all__ = [
    "AlignedTelemetryWithEvents",
    "ResearchDataAccessLayer",
    "ResearchSignalObservation",
    "SignalTarget",
]


@dataclass(frozen=True, slots=True)
class ResearchSignalObservation:
    """Atomic research observation with exact event time."""

    event_time: dt.datetime
    frame_sequence: int
    value: Any
    raw_value: str | None
    masked_sentinel: bool


@dataclass(frozen=True, slots=True)
class SignalTarget:
    """Specification of a signal to retrieve."""

    signal_name: str
    component_type: str | None = None
    component_id: int | None = None


@dataclass(frozen=True, slots=True)
class AlignedTelemetryWithEvents:
    """A research observation point enriched with concurrently active operational events."""

    event_time: dt.datetime
    frame_sequence: int
    signal_values: dict[str, Any]
    active_session_id: str | None = None
    active_alarms: list[str] = None  # type: ignore[assignment]
    active_faults: list[str] = None  # type: ignore[assignment]


class ResearchDataAccessLayer:
    """Research data access for EDA, cohort studies, and Phase 9 pattern analysis."""

    def __init__(
        self,
        history_service: HistoricalContinuityService,
        event_repo: EventRepository | None = None,
    ) -> None:
        self._history_service = history_service
        self._event_repo = event_repo

    async def get_signal_history(
        self,
        charger_id: str,
        signal_name: str,
        *,
        component_type: str | None = None,
        component_id: int | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 10000,
    ) -> list[ResearchSignalObservation]:
        """Query canonical Silver observations for a single signal without resampling."""
        resp = await self._history_service.get_signal_history(
            charger_id=charger_id,
            signal_name=signal_name,
            component_type=component_type,
            component_id=component_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        return [
            ResearchSignalObservation(
                event_time=o.event_time,
                frame_sequence=o.frame_sequence,
                value=o.value,
                raw_value=o.raw_value,
                masked_sentinel=o.masked_sentinel,
            )
            for o in resp.observations
        ]

    async def get_multisignal_history(
        self,
        charger_id: str,
        signals: list[SignalTarget],
        *,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit_per_signal: int = 10000,
    ) -> dict[str, list[ResearchSignalObservation]]:
        """Retrieve multiple signals over a shared time range without forcing alignment."""
        results: dict[str, list[ResearchSignalObservation]] = {}

        for target in signals:
            key = (
                f"{target.component_type}:{target.component_id}:{target.signal_name}"
                if target.component_type and target.component_id is not None
                else target.signal_name
            )
            obs = await self.get_signal_history(
                charger_id=charger_id,
                signal_name=target.signal_name,
                component_type=target.component_type,
                component_id=target.component_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit_per_signal,
            )
            results[key] = obs

        return results

    async def get_session_events(
        self,
        charger_id: str,
        *,
        connector_id: int | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 1000,
    ) -> Sequence[ChargingSessionEvent]:
        """Retrieve reconstructed charging sessions for Phase 9 research."""
        if not self._event_repo:
            return []
        return await self._event_repo.get_sessions(
            charger_id=charger_id,
            connector_id=connector_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_alarm_events(
        self,
        charger_id: str,
        *,
        alarm_code: str | None = None,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 1000,
    ) -> Sequence[AlarmEvent]:
        """Retrieve reconstructed alarm intervals for Phase 9 research."""
        if not self._event_repo:
            return []
        return await self._event_repo.get_alarms(
            charger_id=charger_id,
            alarm_code=alarm_code,
            is_open=is_open,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_fault_events(
        self,
        charger_id: str,
        *,
        is_open: bool | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 1000,
    ) -> Sequence[FaultEvent]:
        """Retrieve reconstructed hardware protection faults for Phase 9 research."""
        if not self._event_repo:
            return []
        return await self._event_repo.get_faults(
            charger_id=charger_id,
            is_open=is_open,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_state_transitions(
        self,
        charger_id: str,
        *,
        state_field: str | None = None,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 1000,
    ) -> Sequence[StateTransitionEvent]:
        """Retrieve discrete state transition events for Phase 9 research."""
        if not self._event_repo:
            return []
        return await self._event_repo.get_state_transitions(
            charger_id=charger_id,
            state_field=state_field,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_configuration_changes(
        self,
        charger_id: str,
        *,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 100,
    ) -> Sequence[ConfigurationChangeEvent]:
        """Retrieve configuration parameter changes for Phase 9 research."""
        if not self._event_repo:
            return []
        return await self._event_repo.get_config_changes(
            charger_id=charger_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_telemetry_with_events(
        self,
        charger_id: str,
        signals: list[SignalTarget],
        *,
        start_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        limit: int = 5000,
    ) -> list[AlignedTelemetryWithEvents]:
        """Produce analytical join view aligning telemetry observations with active events.

        For each unique observation timestamp in the requested telemetry signals,
        checks if any charging session, alarm span, or fault span was concurrently active.
        Zero interpolation; values align only where telemetry was actually captured.
        """
        signal_data = await self.get_multisignal_history(
            charger_id=charger_id,
            signals=signals,
            start_time=start_time,
            end_time=end_time,
            limit_per_signal=limit,
        )

        sessions = await self.get_session_events(
            charger_id=charger_id, start_time=start_time, end_time=end_time
        )
        alarms = await self.get_alarm_events(
            charger_id=charger_id, start_time=start_time, end_time=end_time
        )
        faults = await self.get_fault_events(
            charger_id=charger_id, start_time=start_time, end_time=end_time
        )

        # Collect distinct timestamps
        points: dict[tuple[dt.datetime, int], dict[str, Any]] = {}
        for sig_key, obs_list in signal_data.items():
            for o in obs_list:
                k = (o.event_time, o.frame_sequence)
                if k not in points:
                    points[k] = {}
                points[k][sig_key] = o.value

        aligned: list[AlignedTelemetryWithEvents] = []
        for event_time, frame_seq in sorted(points.keys()):
            # Find active session
            active_sess = None
            for s in sessions:
                s_end = s.end_time or dt.datetime.max.replace(tzinfo=dt.UTC)
                if s.start_time <= event_time <= s_end:
                    active_sess = s.session_id
                    break

            # Find active alarms
            active_alms = [
                a.alarm_code
                for a in alarms
                if a.start_time
                <= event_time
                <= (a.end_time or dt.datetime.max.replace(tzinfo=dt.UTC))
            ]

            # Find active faults
            active_flts = [
                f.fault_code
                for f in faults
                if f.start_time
                <= event_time
                <= (f.end_time or dt.datetime.max.replace(tzinfo=dt.UTC))
            ]

            aligned.append(
                AlignedTelemetryWithEvents(
                    event_time=event_time,
                    frame_sequence=frame_seq,
                    signal_values=points[(event_time, frame_seq)],
                    active_session_id=active_sess,
                    active_alarms=active_alms,
                    active_faults=active_flts,
                )
            )

        return aligned[:limit]
