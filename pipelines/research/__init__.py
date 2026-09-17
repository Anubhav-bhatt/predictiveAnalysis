"""Phase 9 scientific pattern discovery and analytical dataset pipelines."""

from pipelines.research.dataset_builder import ResearchDatasetBuilder
from pipelines.research.fleet_profiler import FleetProfiler
from pipelines.research.models import (
    AnalyticalDataset,
    AnalyticalRecord,
    ChargerProfile,
    CorrelationEntry,
    CorrelationMatrix,
    DatasetMetadata,
    FleetProfile,
    PatternCandidate,
    PatternEvidence,
    PatternScanResult,
    SignalStatistics,
)
from pipelines.research.pattern_scanner import PatternScanner
from pipelines.research.signal_statistician import SignalStatistician

__all__ = [
    "AnalyticalDataset",
    "AnalyticalRecord",
    "ChargerProfile",
    "CorrelationEntry",
    "CorrelationMatrix",
    "DatasetMetadata",
    "FleetProfile",
    "FleetProfiler",
    "PatternCandidate",
    "PatternEvidence",
    "PatternScanner",
    "PatternScanResult",
    "ResearchDatasetBuilder",
    "SignalStatistician",
    "SignalStatistics",
]
