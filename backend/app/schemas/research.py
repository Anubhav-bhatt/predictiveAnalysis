"""Pydantic response schemas for Phase 9 research endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AnalyticalDatasetSummaryDTO",
    "CorrelationEntryDTO",
    "CorrelationMatrixDTO",
    "DataReadinessDTO",
    "FleetEDASummaryDTO",
    "PatternCandidateDTO",
    "PatternScanOutcomeDTO",
    "SignalStatisticsDTO",
]


class SignalStatisticsDTO(BaseModel):
    """Descriptive statistics for a signal."""

    model_config = ConfigDict(from_attributes=True)

    signal_name: str
    count: int
    non_null_count: int
    null_count: int
    sentinel_count: int
    zero_count: int
    negative_count: int
    mean: float | None = None
    std: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    p05: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p95: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    distinct_count: int | None = None
    missing_rate: float = 0.0


class CorrelationEntryDTO(BaseModel):
    """A single pairwise signal correlation."""

    model_config = ConfigDict(from_attributes=True)

    signal_a: str
    signal_b: str
    pearson_r: float | None = None
    spearman_rho: float | None = None
    sample_count: int = 0


class CorrelationMatrixDTO(BaseModel):
    """Collection of pairwise signal correlations."""

    model_config = ConfigDict(from_attributes=True)

    signal_names: list[str] = Field(default_factory=list)
    entries: list[CorrelationEntryDTO] = Field(default_factory=list)


class PatternCandidateDTO(BaseModel):
    """A discovered pattern candidate with evidence and confidence."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    charger_id: str
    pattern_category: str
    evidence_level: str
    title: str
    description: str
    confidence_score: float = 0.0
    affected_signals: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    observation_window_start: dt.datetime | None = None
    observation_window_end: dt.datetime | None = None
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    analytical_grain: str | None = None
    scan_version: str = "v1"
    created_at: dt.datetime | None = None


class FleetEDASummaryDTO(BaseModel):
    """Fleet-wide exploratory data analysis summary."""

    model_config = ConfigDict(from_attributes=True)

    total_chargers: int = 0
    total_observations: int = 0
    total_sessions: int = 0
    total_alarms: int = 0
    total_faults: int = 0
    total_gaps: int = 0
    temporal_span_start: dt.datetime | None = None
    temporal_span_end: dt.datetime | None = None
    fleet_missing_rate: float = 0.0
    signal_count: int = 0
    pattern_candidate_count: int = 0
    charger_summaries: list[dict[str, Any]] = Field(default_factory=list)


class AnalyticalDatasetSummaryDTO(BaseModel):
    """Metadata for an analytical dataset build."""

    model_config = ConfigDict(from_attributes=True)

    grain: str
    charger_id: str | None = None
    record_count: int = 0
    signal_count: int = 0
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    gap_count: int = 0
    missing_rate: float = 0.0
    dataset_version: str = "v1"
    build_duration_ms: float = 0.0


class DataReadinessDTO(BaseModel):
    """Assessment of data readiness for future ML phases."""

    model_config = ConfigDict(from_attributes=True)

    overall_readiness: str  # "READY", "PARTIAL", "NOT_READY"
    temporal_depth: str  # "SINGLE_SNAPSHOT", "MULTI_DAY", "LONGITUDINAL"
    charger_count: int = 0
    observation_count: int = 0
    signal_coverage_rate: float = 0.0
    temporal_span_days: float = 0.0
    gap_rate: float = 0.0
    session_count: int = 0
    alarm_count: int = 0
    pattern_candidate_count: int = 0
    blockers: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PatternScanOutcomeDTO(BaseModel):
    """Result of a pattern scanning run."""

    model_config = ConfigDict(from_attributes=True)

    charger_id: str
    candidates_found: int = 0
    candidates_persisted: int = 0
    scan_duration_ms: float = 0.0
    signals_scanned: int = 0
    records_analyzed: int = 0
    scan_version: str = "v1"
