"""Pydantic schemas for Silver normalization endpoints (Phase 6)."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field


class NormalizationRunSummary(BaseModel):
    """Execution metrics and status of a file normalization run."""

    id: UUID
    file_id: UUID
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    status: str
    frames_input: int = 0
    frames_normalized: int = 0
    frames_with_warnings: int = 0
    frames_failed: int = 0
    conflicts_detected_count: int = 0
    sentinels_masked_count: int = 0
    records_created_by_table: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = None


class SilverChargerTelemetryDTO(BaseModel):
    """Cabinet-level telemetry observation."""

    id: UUID
    charger_id: str
    event_time: dt.datetime
    frame_sequence: int
    frame_id: UUID
    ocpp_id: str | None = None
    # Key continuous electrical signals
    input_voltage: float | None = None
    input_current: float | None = None
    frequency: float | None = None
    power_factor: float | None = None
    cabinet_temperature: float | None = None
    neutral_voltage: float | None = None
    l1_n_voltage: float | None = None
    l2_n_voltage: float | None = None
    l3_n_voltage: float | None = None


class SilverConnectorTelemetryDTO(BaseModel):
    """Connector-level telemetry observation."""

    id: UUID
    charger_id: str
    connector_id: int
    event_time: dt.datetime
    frame_sequence: int
    frame_id: UUID
    connector_type: str | None = None
    connector_status: str | None = None
    plug_status: str | None = None
    gun_temp_dc_positive: float | None = None
    gun_temp_dc_negative: float | None = None
    gun_temp_dc_positive_raw: float | None = None
    gun_temp_dc_negative_raw: float | None = None
    gun_temp_dc_positive_masked: bool = False
    gun_temp_dc_negative_masked: bool = False


class SilverSmrTelemetryDTO(BaseModel):
    """SMR-level telemetry observation."""

    id: UUID
    charger_id: str
    smr_id: int
    event_time: dt.datetime
    frame_sequence: int
    frame_id: UUID
    smr_output_voltage: float | None = None
    smr_output_current: float | None = None
    smr_output_power: float | None = None
    smr_dc_dc_temperature: float | None = None
    smr_pfc_temperature: float | None = None
    smr_dc_dc_temperature_masked: bool = False
    smr_pfc_temperature_masked: bool = False


class SilverRectifierTelemetryDTO(BaseModel):
    """Rectifier-level telemetry observation."""

    id: UUID
    charger_id: str
    rectifier_id: int
    event_time: dt.datetime
    frame_sequence: int
    frame_id: UUID
    rectifier_internal_temp: float | None = None
    rect_max_temperature: float | None = None
    rectifier_internal_temp_masked: bool = False
    rect_max_temperature_masked: bool = False
