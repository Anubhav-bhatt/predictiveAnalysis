"""Pure dataclasses for Phase 9 scientific pattern discovery and analytical datasets.

All structures are immutable, IO-free value objects.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from backend.app.models.enums import (
    AnalyticalGrain,
    PatternCategory,
    PatternEvidenceLevel,
)

__all__ = [
    "AnalyticalDataset",
    "AnalyticalRecord",
    "ChargerProfile",
    "CorrelationEntry",
    "CorrelationMatrix",
    "DatasetMetadata",
    "FleetProfile",
    "PatternCandidate",
    "PatternEvidence",
    "PatternScanResult",
    "SignalStatistics",
]


@dataclass(frozen=True, slots=True)
class SignalStatistics:
    """Descriptive statistics for a single signal's observations."""

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


@dataclass(frozen=True, slots=True)
class CorrelationEntry:
    """A single pairwise signal correlation result."""

    signal_a: str
    signal_b: str
    pearson_r: float | None = None
    spearman_rho: float | None = None
    sample_count: int = 0


@dataclass(frozen=True, slots=True)
class CorrelationMatrix:
    """Collection of pairwise correlations for a signal set."""

    entries: tuple[CorrelationEntry, ...] = ()
    signal_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChargerProfile:
    """Statistical profile for a single charger."""

    charger_id: str
    observation_count: int = 0
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None
    distinct_timestamps: int = 0
    connector_count: int = 0
    smr_count: int = 0
    rectifier_count: int = 0
    session_count: int = 0
    alarm_count: int = 0
    fault_count: int = 0
    gap_count: int = 0
    signal_coverage: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FleetProfile:
    """Fleet-wide statistical profile aggregated across all chargers."""

    total_chargers: int = 0
    total_observations: int = 0
    charger_profiles: tuple[ChargerProfile, ...] = ()
    fleet_signal_stats: tuple[SignalStatistics, ...] = ()
    temporal_span_start: dt.datetime | None = None
    temporal_span_end: dt.datetime | None = None
    total_sessions: int = 0
    total_alarms: int = 0
    total_faults: int = 0
    total_gaps: int = 0
    fleet_missing_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class AnalyticalRecord:
    """A single unit-of-analysis record for research datasets."""

    grain: AnalyticalGrain
    charger_id: str
    component_type: str | None = None
    component_id: int | None = None
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    features: dict[str, Any] = field(default_factory=dict)
    observation_count: int = 0
    has_gap: bool = False
    gap_count: int = 0
    missing_signals: tuple[str, ...] = ()
    quality_score: float = 1.0


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Metadata describing an analytical dataset build."""

    grain: AnalyticalGrain
    charger_id: str | None = None
    record_count: int = 0
    signal_count: int = 0
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    gap_count: int = 0
    missing_rate: float = 0.0
    dataset_version: str = "v1"
    build_duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class AnalyticalDataset:
    """A constructed analytical dataset with records and metadata."""

    metadata: DatasetMetadata
    records: tuple[AnalyticalRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class PatternEvidence:
    """Supporting evidence for a detected pattern candidate."""

    metric_name: str
    observed_value: float | None = None
    reference_value: float | None = None
    threshold: float | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    """A detected pattern candidate with evidence and confidence scoring."""

    charger_id: str
    pattern_category: PatternCategory
    evidence_level: PatternEvidenceLevel
    title: str
    description: str
    confidence_score: float = 0.0
    affected_signals: tuple[str, ...] = ()
    affected_components: tuple[str, ...] = ()
    observation_window_start: dt.datetime | None = None
    observation_window_end: dt.datetime | None = None
    supporting_evidence: tuple[PatternEvidence, ...] = ()
    analytical_grain: AnalyticalGrain = AnalyticalGrain.CHARGER_TIME
    scan_version: str = "v1"


@dataclass(frozen=True, slots=True)
class PatternScanResult:
    """Result of a pattern scanning run."""

    charger_id: str
    candidates: tuple[PatternCandidate, ...] = ()
    scan_duration_ms: float = 0.0
    signals_scanned: int = 0
    records_analyzed: int = 0
    scan_version: str = "v1"
