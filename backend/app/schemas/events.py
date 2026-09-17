"""Pydantic schemas and DTOs for Phase 8 Discrete Event Reconstruction."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import (
    AlarmSeverity,
    EventConfidence,
    EventType,
    TerminationClass,
)

__all__ = [
    "AlarmEventRead",
    "AlarmEventsResponse",
    "ChargingSessionEventRead",
    "ChargingSessionsResponse",
    "ConfigurationChangeEventRead",
    "EventReconstructionOutcome",
    "EventTimelineResponse",
    "FaultEventRead",
    "StateTransitionEventRead",
    "UnifiedEventTimelineItem",
]


class ChargingSessionEventRead(BaseModel):
    """Reconstructed charging session event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    charger_id: str
    connector_id: int
    session_id: str | None = None
    start_time: dt.datetime
    charging_start_time: dt.datetime | None = None
    charging_end_time: dt.datetime | None = None
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    energy_delivered_kwh: float | None = None
    start_soc: float | None = None
    end_soc: float | None = None
    stop_reason: str | None = None
    termination_class: TerminationClass | None = None
    confidence: EventConfidence
    has_gap: bool
    quality_flags: list[str] | None = None
    evidence: dict[str, Any] | None = None
    reconstruction_version: str
    created_at: dt.datetime


class ChargingSessionsResponse(BaseModel):
    """List of charging session events for a charger."""

    charger_id: str
    total_count: int
    sessions: list[ChargingSessionEventRead]


class AlarmEventRead(BaseModel):
    """Reconstructed alarm span event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    charger_id: str
    component_type: str
    component_id: int | None = None
    alarm_code: str
    alarm_name: str
    severity: AlarmSeverity
    start_time: dt.datetime
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    is_open: bool
    start_state: str | None = None
    end_state: str | None = None
    confidence: EventConfidence
    has_gap: bool
    quality_flags: list[str] | None = None
    reconstruction_version: str
    created_at: dt.datetime


class AlarmEventsResponse(BaseModel):
    """List of alarm events for a charger."""

    charger_id: str
    total_count: int
    alarms: list[AlarmEventRead]


class FaultEventRead(BaseModel):
    """Reconstructed hardware protection fault event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    charger_id: str
    component_type: str
    component_id: int | None = None
    fault_code: str
    fault_name: str
    start_time: dt.datetime
    end_time: dt.datetime | None = None
    duration_seconds: float | None = None
    is_open: bool
    initial_reading: str | None = None
    clearing_reading: str | None = None
    confidence: EventConfidence
    has_gap: bool
    quality_flags: list[str] | None = None
    reconstruction_version: str
    created_at: dt.datetime


class StateTransitionEventRead(BaseModel):
    """Discrete operational state change event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    charger_id: str
    component_type: str
    component_id: int | None = None
    state_field: str
    from_state: str | None = None
    to_state: str
    transition_time: dt.datetime
    frame_sequence: int
    created_at: dt.datetime


class ConfigurationChangeEventRead(BaseModel):
    """Reconstructed configuration change event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    charger_id: str
    change_time: dt.datetime
    old_config_hash: str
    new_config_hash: str
    changed_fields_json: dict[str, Any]
    previous_config_json: dict[str, Any] | None = None
    new_config_json: dict[str, Any] | None = None
    reconstruction_version: str
    created_at: dt.datetime


class UnifiedEventTimelineItem(BaseModel):
    """A generic item in a unified chronological event stream."""

    event_id: UUID
    event_type: EventType
    event_time: dt.datetime
    end_time: dt.datetime | None = None
    title: str
    description: str
    component: str
    severity: str | None = None
    duration_seconds: float | None = None
    is_open: bool = False
    has_gap: bool = False
    confidence: EventConfidence = EventConfidence.HIGH
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventTimelineResponse(BaseModel):
    """Unified chronological event stream combining sessions, alarms, faults, and changes."""

    charger_id: str
    total_count: int
    events: list[UnifiedEventTimelineItem]


class EventReconstructionOutcome(BaseModel):
    """Summary of event reconstruction execution for a charger."""

    charger_id: str
    sessions_reconstructed: int
    alarms_reconstructed: int
    faults_reconstructed: int
    state_transitions_reconstructed: int
    configuration_changes_reconstructed: int
    reconstruction_duration_ms: float
