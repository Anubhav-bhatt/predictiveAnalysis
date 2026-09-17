"""Discrete operational event models (Phase 8).

Transform continuous telemetry observations and state flags into duration-bounded
operational events: charging sessions, alarm intervals, protection faults, discrete
state transitions, and configuration change events.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import (
    Base,
    JSONVariant,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
    enum_column,
    utcnow,
)
from backend.app.models.enums import (
    AlarmSeverity,
    EventConfidence,
    TerminationClass,
)

__all__ = [
    "AlarmEvent",
    "ChargingSessionEvent",
    "ConfigurationChangeEvent",
    "FaultEvent",
    "StateTransitionEvent",
]


class ChargingSessionEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reconstructed EV charging session lifecycle event on a physical connector."""

    __tablename__ = "charging_session_event"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True, default=1)
    session_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)

    start_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    charging_start_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    charging_end_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)

    duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    energy_delivered_kwh: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    start_soc: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    end_soc: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    stop_reason: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    termination_class: Mapped[TerminationClass | None] = mapped_column(
        enum_column(TerminationClass), nullable=True
    )
    confidence: Mapped[EventConfidence] = mapped_column(
        enum_column(EventConfidence), nullable=False, default=EventConfidence.MEDIUM
    )
    has_gap: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    quality_flags: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    reconstruction_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")
    source_first_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    source_last_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "connector_id",
            "start_time",
            "reconstruction_version",
            name="uq_charging_session_event",
        ),
        sa.Index(
            "ix_charging_session_event_lookup",
            "charger_id",
            "connector_id",
            "start_time",
        ),
        sa.Index(
            "ix_charging_session_event_time",
            "charger_id",
            "start_time",
        ),
    )


class AlarmEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reconstructed continuous alarm active span with open/closed state tracking."""

    __tablename__ = "alarm_event"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="cabinet")
    component_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    alarm_code: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    alarm_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    severity: Mapped[AlarmSeverity] = mapped_column(
        enum_column(AlarmSeverity), nullable=False, default=AlarmSeverity.WARNING
    )

    start_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_open: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, index=True)

    start_state: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    end_state: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    confidence: Mapped[EventConfidence] = mapped_column(
        enum_column(EventConfidence), nullable=False, default=EventConfidence.HIGH
    )
    has_gap: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    quality_flags: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)

    reconstruction_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")
    source_first_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    source_last_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "alarm_code",
            "component_type",
            "component_id",
            "start_time",
            "reconstruction_version",
            name="uq_alarm_event",
        ),
        sa.Index(
            "ix_alarm_event_lookup",
            "charger_id",
            "alarm_code",
            "start_time",
        ),
        sa.Index(
            "ix_alarm_event_open",
            "charger_id",
            "is_open",
        ),
    )


class FaultEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reconstructed hardware protection trips and authoritative physical fault spans."""

    __tablename__ = "fault_event"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="cabinet")
    component_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    fault_code: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    fault_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    start_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_open: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, index=True)

    initial_reading: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    clearing_reading: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    confidence: Mapped[EventConfidence] = mapped_column(
        enum_column(EventConfidence), nullable=False, default=EventConfidence.HIGH
    )
    has_gap: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    quality_flags: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)

    reconstruction_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")
    source_first_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    source_last_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "fault_code",
            "component_type",
            "component_id",
            "start_time",
            "reconstruction_version",
            name="uq_fault_event",
        ),
        sa.Index(
            "ix_fault_event_lookup",
            "charger_id",
            "fault_code",
            "start_time",
        ),
    )


class StateTransitionEvent(UUIDPrimaryKeyMixin, Base):
    """Discrete operational state change event preserving exact arrival and frame sequence."""

    __tablename__ = "state_transition_event"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="connector")
    component_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    state_field: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    from_state: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    to_state: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    transition_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    frame_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "component_type",
            "component_id",
            "state_field",
            "transition_time",
            "frame_sequence",
            name="uq_state_transition_event",
        ),
        sa.Index(
            "ix_state_transition_event_lookup",
            "charger_id",
            "state_field",
            "transition_time",
        ),
    )


class ConfigurationChangeEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reconstructed hardware/firmware parameter configuration change event."""

    __tablename__ = "configuration_change_event"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    change_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)

    old_config_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    new_config_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    changed_fields_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    previous_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    new_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    reconstruction_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "old_config_hash",
            "new_config_hash",
            "change_time",
            "reconstruction_version",
            name="uq_configuration_change_event",
        ),
        sa.Index(
            "ix_configuration_change_event_lookup",
            "charger_id",
            "change_time",
        ),
    )
