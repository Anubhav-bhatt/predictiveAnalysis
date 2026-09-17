"""Pydantic schemas and DTOs for Phase 7 Historical Continuity & Time-Series Research Layer."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HistoricalObservationDTO(BaseModel):
    """Normalized observation entry at a discrete canonical event time."""

    model_config = ConfigDict(from_attributes=True)

    event_time: dt.datetime
    frame_sequence: int
    frame_id: UUID
    metrics: dict[str, Any]


class ChargerHistoryResponse(BaseModel):
    """Chronological telemetry stream for a charger."""

    charger_id: str
    total_count: int
    observations: list[HistoricalObservationDTO]
    next_cursor: str | None = None


class HistoricalGapDTO(BaseModel):
    """An unobserved period in telemetry relative to local sampling interval."""

    gap_start: dt.datetime
    gap_end: dt.datetime
    gap_duration_seconds: float
    previous_event_time: dt.datetime
    next_event_time: dt.datetime
    expected_interval_seconds: float | None = None
    gap_multiple: float | None = None


class SamplingProfileDTO(BaseModel):
    """Empirical sampling cadence statistics."""

    observation_count: int
    distinct_timestamps: int
    first_event_time: dt.datetime | None = None
    last_event_time: dt.datetime | None = None
    coverage_duration_seconds: float
    median_interval_seconds: float | None = None
    p05_interval_seconds: float | None = None
    p95_interval_seconds: float | None = None
    min_interval_seconds: float | None = None
    max_interval_seconds: float | None = None
    expected_interval_seconds: float | None = None
    same_second_frame_count: int = 0


class ComponentPresenceDTO(BaseModel):
    """Component presence timeline."""

    component_type: str
    component_id: int
    first_seen: dt.datetime
    last_seen: dt.datetime
    observation_count: int
    active_days_count: int


class PatternResearchEligibilityDTO(BaseModel):
    """Descriptive pattern research readiness."""

    charger_id: str
    history_days: int
    observation_count: int
    median_sampling_interval_seconds: float | None = None
    largest_gap_seconds: float | None = None
    gap_count: int = 0
    signal_count: int = 0
    pattern_research_ready: bool
    reason: str


class ChargerContinuitySummaryDTO(BaseModel):
    """Descriptive multi-day fleet-history summary for a charger."""

    charger_id: str
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None
    observation_count: int
    distinct_timestamps: int
    observed_days: int
    latest_observation_age_seconds: float | None = None
    connectors_observed: list[int] = Field(default_factory=list)
    smrs_observed: list[int] = Field(default_factory=list)
    rectifiers_observed: list[int] = Field(default_factory=list)
    configuration_versions_count: int = 0
    sampling_profile: SamplingProfileDTO
    gaps: list[HistoricalGapDTO] = Field(default_factory=list)
    pattern_eligibility: PatternResearchEligibilityDTO
    history_depth_status: str  # "SINGLE_OBSERVATION" | "MULTI_OBSERVATION" | "NO_DATA"


class SignalObservationDTO(BaseModel):
    """Individual atomic canonical signal observation."""

    event_time: dt.datetime
    frame_sequence: int
    value: Any
    raw_value: str | None = None
    masked_sentinel: bool = False


class SignalHistoryResponse(BaseModel):
    """Stream of observations for a single canonical signal."""

    charger_id: str
    component_type: str | None = None
    component_id: int | None = None
    signal_name: str
    observation_count: int
    observations: list[SignalObservationDTO]


class SignalAvailabilityMatrixResponse(BaseModel):
    """Fleet-wide signal availability matrix based on observed non-null telemetry."""

    signals: list[str]
    matrix: dict[str, dict[str, bool]]


class ConfigurationSnapshotDTO(BaseModel):
    """Hardware and firmware configuration snapshot."""

    event_time: dt.datetime
    frame_sequence: int
    config_hash: str
    raw_config_json: dict[str, Any] | None = None
    charging_mode: str | None = None
    charging_start_method: str | None = None
    charge_selected_mode: str | None = None
    ev_max_voltage_limit: float | None = None
    ev_max_current_limit: float | None = None
