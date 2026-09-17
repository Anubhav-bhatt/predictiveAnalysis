"""Alarm and hardware fault event reconstruction algorithm (Phase 8).

Transforms continuous boolean/enum alarm flags into duration-bounded intervals,
with support for open events, configurable debounce, and gap awareness.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.models.enums import (
    AlarmSeverity,
    EventConfidence,
    EventQualityFlag,
)
from pipelines.events.models import (
    ReconstructedAlarm,
    ReconstructedFault,
    TelemetryGapInterval,
)

__all__ = ["AlarmObservation", "AlarmReconstructor", "is_active_state"]


@dataclass(frozen=True, slots=True)
class AlarmObservation:
    """A point-in-time observation of an alarm or protection flag."""

    event_time: dt.datetime
    frame_sequence: int
    frame_id: uuid.UUID
    is_active: bool
    state_str: str | None = None


def is_active_state(raw_value: Any) -> bool:
    """Evaluate whether an alarm/fault reading is active vs normal.

    Distinguishes active states ('1', 'true', 'alarm', 'trip', 'active', 'fail')
    from normal states ('0', 'false', 'normal', 'not alarm', 'ok', 'closed').
    """
    if raw_value is None:
        return False
    s = str(raw_value).strip().lower()
    if s in ("1", "true", "yes", "alarm", "trip", "active", "fail", "failed", "abnormal", "open"):
        # Special case: 'door_open' -> open is active.
        return True
    if s in (
        "0",
        "false",
        "no",
        "normal",
        "not alarm",
        "ok",
        "healthy",
        "pass",
        "closed",
        "none",
        "null",
    ):
        return False
    # If not explicitly recognized as normal, do not guess
    return False


class AlarmReconstructor:
    """Pure pipeline orchestrator for reconstructing alarm and fault intervals."""

    def __init__(self, debounce_seconds: float = 0.0, version: str = "v1") -> None:
        self.debounce_seconds = max(debounce_seconds, 0.0)
        self.version = version

    def reconstruct_alarms(
        self,
        charger_id: str,
        alarm_code: str,
        alarm_name: str,
        component_type: str,
        component_id: int | None,
        observations: Sequence[AlarmObservation],
        gaps: Sequence[TelemetryGapInterval] = (),
        severity: AlarmSeverity = AlarmSeverity.WARNING,
    ) -> list[ReconstructedAlarm]:
        """Convert chronological observations for one alarm into interval events."""
        if not observations:
            return []

        ordered = sorted(observations, key=lambda o: (o.event_time, o.frame_sequence))
        reconstructed: list[ReconstructedAlarm] = []

        in_alarm = False
        start_time: dt.datetime | None = None
        start_state: str | None = None
        last_active_time: dt.datetime | None = None
        last_active_state: str | None = None
        first_frame_id: uuid.UUID | None = None
        last_frame_id: uuid.UUID | None = None

        for obs in ordered:
            if obs.is_active:
                if not in_alarm:
                    # Check debounce merge with previous closed alarm
                    if (
                        reconstructed
                        and self.debounce_seconds > 0.0
                        and reconstructed[-1].end_time is not None
                        and (obs.event_time - reconstructed[-1].end_time).total_seconds()
                        <= self.debounce_seconds
                    ):
                        # Re-open and extend previous alarm
                        prev = reconstructed.pop()
                        in_alarm = True
                        start_time = prev.start_time
                        start_state = prev.start_state
                        first_frame_id = prev.source_first_frame_id
                        last_active_time = obs.event_time
                        last_active_state = obs.state_str
                        last_frame_id = obs.frame_id
                    else:
                        in_alarm = True
                        start_time = obs.event_time
                        start_state = obs.state_str
                        first_frame_id = obs.frame_id
                        last_active_time = obs.event_time
                        last_active_state = obs.state_str
                        last_frame_id = obs.frame_id
                else:
                    last_active_time = obs.event_time
                    last_active_state = obs.state_str
                    last_frame_id = obs.frame_id
            else:
                if in_alarm:
                    # Alarm cleared
                    assert start_time is not None
                    end_time = obs.event_time
                    duration_s = max((end_time - start_time).total_seconds(), 0.0)
                    has_gap = any(g.overlaps(start_time, end_time) for g in gaps)
                    q_flags: list[str] = []
                    if has_gap:
                        q_flags.append(EventQualityFlag.EVENT_HAS_GAP.value)

                    reconstructed.append(
                        ReconstructedAlarm(
                            charger_id=charger_id,
                            alarm_code=alarm_code,
                            alarm_name=alarm_name,
                            component_type=component_type,
                            component_id=component_id,
                            start_time=start_time,
                            end_time=end_time,
                            duration_seconds=duration_s,
                            is_open=False,
                            start_state=start_state,
                            end_state=obs.state_str,
                            severity=severity,
                            confidence=EventConfidence.HIGH
                            if not has_gap
                            else EventConfidence.MEDIUM,
                            has_gap=has_gap,
                            quality_flags=tuple(q_flags),
                            reconstruction_version=self.version,
                            source_first_frame_id=first_frame_id,
                            source_last_frame_id=obs.frame_id,
                        )
                    )
                    in_alarm = False
                    start_time = None
                    start_state = None
                    last_active_time = None
                    first_frame_id = None
                    last_frame_id = None

        # Handle open alarm at end of timeline
        if in_alarm and start_time is not None and last_active_time is not None:
            duration_s = max((last_active_time - start_time).total_seconds(), 0.0)
            has_gap = any(g.overlaps(start_time, last_active_time) for g in gaps)
            q_flags = [EventQualityFlag.ALARM_OPEN_ENDED.value]
            if has_gap:
                q_flags.append(EventQualityFlag.EVENT_HAS_GAP.value)

            reconstructed.append(
                ReconstructedAlarm(
                    charger_id=charger_id,
                    alarm_code=alarm_code,
                    alarm_name=alarm_name,
                    component_type=component_type,
                    component_id=component_id,
                    start_time=start_time,
                    end_time=None,
                    duration_seconds=duration_s,
                    is_open=True,
                    start_state=start_state,
                    end_state=last_active_state,
                    severity=severity,
                    confidence=EventConfidence.MEDIUM,
                    has_gap=has_gap,
                    quality_flags=tuple(q_flags),
                    reconstruction_version=self.version,
                    source_first_frame_id=first_frame_id,
                    source_last_frame_id=last_frame_id,
                )
            )

        return reconstructed

    def reconstruct_faults(
        self,
        charger_id: str,
        fault_code: str,
        fault_name: str,
        component_type: str,
        component_id: int | None,
        observations: Sequence[AlarmObservation],
        gaps: Sequence[TelemetryGapInterval] = (),
    ) -> list[ReconstructedFault]:
        """Convert chronological observations for a hardware fault/trip into interval events."""
        alarms = self.reconstruct_alarms(
            charger_id=charger_id,
            alarm_code=fault_code,
            alarm_name=fault_name,
            component_type=component_type,
            component_id=component_id,
            observations=observations,
            gaps=gaps,
            severity=AlarmSeverity.CRITICAL,
        )
        return [
            ReconstructedFault(
                charger_id=a.charger_id,
                fault_code=a.alarm_code,
                fault_name=a.alarm_name,
                component_type=a.component_type,
                component_id=a.component_id,
                start_time=a.start_time,
                end_time=a.end_time,
                duration_seconds=a.duration_seconds,
                is_open=a.is_open,
                initial_reading=a.start_state,
                clearing_reading=a.end_state,
                confidence=a.confidence,
                has_gap=a.has_gap,
                quality_flags=a.quality_flags,
                reconstruction_version=self.version,
                source_first_frame_id=a.source_first_frame_id,
                source_last_frame_id=a.source_last_frame_id,
            )
            for a in alarms
        ]
