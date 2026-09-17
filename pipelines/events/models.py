"""Data structures for reconstructed discrete events (Phase 8).

Pure dataclasses representing charging sessions, alarm events, faults, state
transitions, and configuration changes before persistence.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.app.models.enums import (
    AlarmSeverity,
    EventConfidence,
    TerminationClass,
)

__all__ = [
    "ReconstructedAlarm",
    "ReconstructedConfigChange",
    "ReconstructedFault",
    "ReconstructedSession",
    "ReconstructedStateTransition",
    "TelemetryGapInterval",
]


@dataclass(frozen=True, slots=True)
class TelemetryGapInterval:
    """A known telemetry outage gap bounding missing frames."""

    start_time: dt.datetime
    end_time: dt.datetime

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    def overlaps(self, start: dt.datetime, end: dt.datetime | None) -> bool:
        """Return True if this gap overlaps the time window [start, end]."""
        if end is None:
            return self.end_time >= start
        return not (self.end_time <= start or self.start_time >= end)


@dataclass(frozen=True, slots=True)
class ReconstructedSession:
    """A reconstructed EV charging session with complete evidence."""

    charger_id: str
    connector_id: int
    start_time: dt.datetime
    session_id: str | None = None
    charging_start_time: dt.datetime | None = None
    charging_end_time: dt.datetime | None = None
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    energy_delivered_kwh: float | None = None
    start_soc: float | None = None
    end_soc: float | None = None
    stop_reason: str | None = None
    termination_class: TerminationClass | None = None
    confidence: EventConfidence = EventConfidence.MEDIUM
    has_gap: bool = False
    quality_flags: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    reconstruction_version: str = "v1"
    source_first_frame_id: uuid.UUID | None = None
    source_last_frame_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedAlarm:
    """A reconstructed continuous alarm interval."""

    charger_id: str
    alarm_code: str
    alarm_name: str
    component_type: str
    component_id: int | None
    start_time: dt.datetime
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    is_open: bool = False
    start_state: str | None = None
    end_state: str | None = None
    severity: AlarmSeverity = AlarmSeverity.WARNING
    confidence: EventConfidence = EventConfidence.HIGH
    has_gap: bool = False
    quality_flags: tuple[str, ...] = ()
    reconstruction_version: str = "v1"
    source_first_frame_id: uuid.UUID | None = None
    source_last_frame_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedFault:
    """A reconstructed hardware protection fault or trip interval."""

    charger_id: str
    fault_code: str
    fault_name: str
    component_type: str
    component_id: int | None
    start_time: dt.datetime
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    is_open: bool = False
    initial_reading: str | None = None
    clearing_reading: str | None = None
    confidence: EventConfidence = EventConfidence.HIGH
    has_gap: bool = False
    quality_flags: tuple[str, ...] = ()
    reconstruction_version: str = "v1"
    source_first_frame_id: uuid.UUID | None = None
    source_last_frame_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedStateTransition:
    """A point-in-time discrete state change on an operational field."""

    charger_id: str
    component_type: str
    component_id: int | None
    state_field: str
    from_state: str | None
    to_state: str
    transition_time: dt.datetime
    frame_sequence: int = 0
    frame_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedConfigChange:
    """A parameter configuration change between consecutive snapshots."""

    charger_id: str
    change_time: dt.datetime
    old_config_hash: str
    new_config_hash: str
    changed_fields_json: dict[str, Any]
    previous_config_json: dict[str, Any] | None = None
    new_config_json: dict[str, Any] | None = None
    reconstruction_version: str = "v1"
