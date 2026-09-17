"""Charging session reconstruction algorithm (Phase 8).

Pure-Python deterministic state machine that transforms continuous connector telemetry
and session observations into discrete, duration-bounded charging session events.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from backend.app.models.enums import (
    EventConfidence,
    EventQualityFlag,
    SessionState,
    TerminationClass,
)
from pipelines.events.models import ReconstructedSession, TelemetryGapInterval

__all__ = ["ConnectorObservation", "SessionReconstructor"]


@dataclass(frozen=True, slots=True)
class ConnectorObservation:
    """A single chronological observation for a physical connector."""

    event_time: dt.datetime
    frame_sequence: int
    frame_id: uuid.UUID
    connector_status: str | None = None
    plug_status: str | None = None
    session_id: str | None = None
    begin_time: dt.datetime | None = None
    session_consumed_energy: float | None = None
    session_output_voltage: float | None = None
    session_output_current: float | None = None
    start_soc: float | None = None
    stop_soc: float | None = None
    stop_reason: str | None = None
    reported_charging_time: float | None = None
    meter_energy: float | None = None


def map_connector_state(raw_status: str | None) -> SessionState:
    """Map vendor connector status string to canonical SessionState enum."""
    if raw_status is None:
        return SessionState.UNKNOWN
    clean = raw_status.strip().lower()
    if clean in ("available", "idle", "standby", "ready_for_use"):
        return SessionState.IDLE
    if clean in ("plugged", "connected"):
        return SessionState.PLUGGED
    if clean in ("preparing", "authenticating"):
        return SessionState.PREPARING
    if clean in ("authorized", "ready"):
        return SessionState.AUTHORIZED
    if clean in ("charging", "in_use", "delivering_energy"):
        return SessionState.CHARGING
    if clean in ("suspended", "paused", "ev_suspended", "evse_suspended"):
        return SessionState.SUSPENDED
    if clean in ("finishing", "stopping"):
        return SessionState.FINISHING
    if clean in ("completed", "charge finished", "stopped", "finished"):
        return SessionState.COMPLETED
    if clean in ("faulted", "error", "unavailable", "emergency"):
        return SessionState.FAULTED
    return SessionState.UNKNOWN


def classify_termination(stop_reason: str | None, final_state: SessionState) -> TerminationClass:
    """Classify why the session ended from stop reason or terminal state."""
    if stop_reason:
        s = stop_reason.lower()
        if any(w in s for w in ("remote", "remotestop")):
            return TerminationClass.REMOTE_STOPPED
        if any(w in s for w in ("emergency", "e-stop", "estop")):
            return TerminationClass.EMERGENCY_STOPPED
        if any(w in s for w in ("local", "user", "stop", "evdisconnected", "card", "app")):
            return TerminationClass.USER_STOPPED
        if any(
            w in s for w in ("fault", "error", "overcurrent", "overvoltage", "ground", "insulation")
        ):
            return TerminationClass.FAULT_STOPPED
        if any(w in s for w in ("commlost", "communication", "reboot", "timeout")):
            return TerminationClass.COMMUNICATION_LOST
        return TerminationClass.NORMAL

    if final_state in (SessionState.IDLE, SessionState.COMPLETED):
        return TerminationClass.NORMAL
    if final_state == SessionState.FAULTED:
        return TerminationClass.FAULT_STOPPED
    return TerminationClass.UNKNOWN


class SessionReconstructor:
    """Pure pipeline orchestrator for reconstructing charging session intervals."""

    def __init__(self, version: str = "v1") -> None:
        self.version = version

    def reconstruct(
        self,
        charger_id: str,
        connector_id: int,
        observations: Sequence[ConnectorObservation],
        gaps: Sequence[TelemetryGapInterval] = (),
    ) -> list[ReconstructedSession]:
        """Process chronological observations and return reconstructed session events."""
        if not observations:
            return []

        # Sort strictly by (event_time ASC, frame_sequence ASC)
        ordered = sorted(observations, key=lambda o: (o.event_time, o.frame_sequence))

        reconstructed: list[ReconstructedSession] = []

        # State tracking for an active session
        in_session = False
        current_session_id: str | None = None
        session_start_time: dt.datetime | None = None
        charging_start_time: dt.datetime | None = None
        charging_end_time: dt.datetime | None = None
        first_frame_id: uuid.UUID | None = None
        last_frame_id: uuid.UUID | None = None
        start_soc: float | None = None
        end_soc: float | None = None
        max_energy: float | None = None
        start_meter: float | None = None
        end_meter: float | None = None
        last_stop_reason: str | None = None
        last_reported_duration: float | None = None
        observed_states: list[SessionState] = []

        def close_active_session(
            session_end_time: dt.datetime,
            terminal_obs: ConnectorObservation,
        ) -> None:
            nonlocal in_session, current_session_id, session_start_time, charging_start_time
            nonlocal charging_end_time, first_frame_id, last_frame_id, start_soc, end_soc
            nonlocal max_energy, start_meter, end_meter, last_stop_reason, last_reported_duration
            nonlocal observed_states

            if session_start_time is None:
                in_session = False
                return

            duration_s = max((session_end_time - session_start_time).total_seconds(), 0.0)

            # Energy delivered: max consumed energy or meter delta
            energy_delivered = max_energy
            if energy_delivered is None and start_meter is not None and end_meter is not None:
                meter_delta = end_meter - start_meter
                if meter_delta >= 0:
                    energy_delivered = meter_delta

            # Termination class
            final_mapped_state = map_connector_state(terminal_obs.connector_status)
            term_class = classify_termination(last_stop_reason, final_mapped_state)

            # Gap analysis
            has_gap = any(g.overlaps(session_start_time, session_end_time) for g in gaps)

            # Quality flags & consistency
            q_flags: list[str] = []
            if has_gap:
                q_flags.append(EventQualityFlag.EVENT_HAS_GAP.value)
            if not current_session_id:
                q_flags.append(EventQualityFlag.SESSION_ID_MISSING.value)
            if not last_stop_reason:
                q_flags.append(EventQualityFlag.SESSION_BOUNDARY_INFERRED.value)

            # Energy consistency check
            if max_energy is not None and start_meter is not None and end_meter is not None:
                meter_delta = end_meter - start_meter
                if abs(meter_delta - max_energy) > 0.5:
                    q_flags.append(EventQualityFlag.SESSION_ENERGY_MISMATCH.value)

            # Duration consistency check
            if (
                last_reported_duration is not None
                and abs(duration_s - last_reported_duration) > 60.0
            ):
                q_flags.append(EventQualityFlag.SESSION_DURATION_MISMATCH.value)

            # Confidence determination
            if not has_gap and current_session_id and last_stop_reason and charging_start_time:
                confidence = EventConfidence.HIGH
            elif has_gap or not current_session_id:
                confidence = EventConfidence.LOW
            else:
                confidence = EventConfidence.MEDIUM

            evidence = {
                "observed_states": [s.value for s in observed_states],
                "stop_reason": last_stop_reason,
                "start_meter": start_meter,
                "end_meter": end_meter,
                "max_consumed_energy": max_energy,
                "reported_charging_time": last_reported_duration,
            }

            reconstructed.append(
                ReconstructedSession(
                    charger_id=charger_id,
                    connector_id=connector_id,
                    session_id=current_session_id,
                    start_time=session_start_time,
                    charging_start_time=charging_start_time,
                    charging_end_time=charging_end_time,
                    end_time=session_end_time,
                    duration_seconds=duration_s,
                    energy_delivered_kwh=energy_delivered,
                    start_soc=start_soc,
                    end_soc=end_soc,
                    stop_reason=last_stop_reason,
                    termination_class=term_class,
                    confidence=confidence,
                    has_gap=has_gap,
                    quality_flags=tuple(q_flags),
                    evidence=evidence,
                    reconstruction_version=self.version,
                    source_first_frame_id=first_frame_id,
                    source_last_frame_id=last_frame_id or terminal_obs.frame_id,
                )
            )

            # Reset session state
            in_session = False
            current_session_id = None
            session_start_time = None
            charging_start_time = None
            charging_end_time = None
            first_frame_id = None
            last_frame_id = None
            start_soc = None
            end_soc = None
            max_energy = None
            start_meter = None
            end_meter = None
            last_stop_reason = None
            last_reported_duration = None
            observed_states = []

        for obs in ordered:
            mapped_state = map_connector_state(obs.connector_status)

            # Detect session start indicators
            session_id_str = str(obs.session_id).strip() if obs.session_id is not None else None
            # Treat numeric strings like "0" or "0.0" as no-session
            if session_id_str in ("0", "0.0", "None", "nan"):
                session_id_str = None

            is_active_state = mapped_state in (
                SessionState.PREPARING,
                SessionState.AUTHORIZED,
                SessionState.CHARGING,
                SessionState.SUSPENDED,
                SessionState.FINISHING,
            )

            is_charging_delivery = (
                obs.session_output_current is not None and obs.session_output_current > 0.5
            )

            # Case A: Currently in a session, but session ID changed to a new non-null ID
            if (
                in_session
                and session_id_str
                and current_session_id
                and session_id_str != current_session_id
            ):
                close_active_session(obs.event_time, obs)

            # Case B: Not in a session, but active indicators arrive -> START
            if not in_session:
                if is_active_state or session_id_str or is_charging_delivery:
                    in_session = True
                    current_session_id = session_id_str
                    session_start_time = obs.begin_time or obs.event_time
                    first_frame_id = obs.frame_id
                    last_frame_id = obs.frame_id
                    start_soc = obs.start_soc
                    end_soc = obs.stop_soc or obs.start_soc
                    max_energy = obs.session_consumed_energy
                    start_meter = obs.meter_energy
                    end_meter = obs.meter_energy
                    last_stop_reason = obs.stop_reason
                    last_reported_duration = obs.reported_charging_time
                    observed_states = [mapped_state]

                    if mapped_state == SessionState.CHARGING or is_charging_delivery:
                        charging_start_time = obs.event_time
                        charging_end_time = obs.event_time

            # Case C: Already in a session -> ACCUMULATE & UPDATE
            else:
                last_frame_id = obs.frame_id
                observed_states.append(mapped_state)
                if not current_session_id and session_id_str:
                    current_session_id = session_id_str

                if (
                    mapped_state == SessionState.CHARGING or is_charging_delivery
                ) and charging_start_time is None:
                    charging_start_time = obs.event_time
                if mapped_state == SessionState.CHARGING or is_charging_delivery:
                    charging_end_time = obs.event_time

                if obs.start_soc is not None and start_soc is None:
                    start_soc = obs.start_soc
                if obs.stop_soc is not None:
                    end_soc = obs.stop_soc

                if obs.session_consumed_energy is not None and (
                    max_energy is None or obs.session_consumed_energy > max_energy
                ):
                    max_energy = obs.session_consumed_energy

                if obs.meter_energy is not None:
                    if start_meter is None:
                        start_meter = obs.meter_energy
                    end_meter = obs.meter_energy

                if obs.stop_reason is not None:
                    last_stop_reason = obs.stop_reason
                if obs.reported_charging_time is not None:
                    last_reported_duration = obs.reported_charging_time

                # Check for session completion triggers
                if mapped_state in (SessionState.IDLE, SessionState.COMPLETED) or (
                    last_stop_reason and not is_active_state and not is_charging_delivery
                ):
                    close_active_session(obs.event_time, obs)

        # If file ends while session was still open, close it at the last observation
        if in_session and ordered:
            close_active_session(ordered[-1].event_time, ordered[-1])

        return reconstructed
