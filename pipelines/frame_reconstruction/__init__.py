"""Phase 1D: source frame reconstruction, replay resolution and collision handling.

Turns raw source rows into trusted *canonical source frames*. It does not produce
Silver telemetry - that is Phase 1E's job, and it consumes only the canonical frames
this package emits.

The rule the package exists to enforce:

    Two rows may share (event_time, connector, SMR) and still be genuinely
    different observations, so ``drop_duplicates`` on that key is never the
    resolution strategy. Repetition is *classified*, never deleted.
"""

from __future__ import annotations

from pipelines.frame_reconstruction.canonical_serializer import (
    NULL_TOKEN,
    CanonicalSerializer,
)
from pipelines.frame_reconstruction.diagnostics import (
    ChargerDayFrameMetrics,
    FileReconstructionMetrics,
)
from pipelines.frame_reconstruction.models import (
    RECONSTRUCTION_VERSION,
    DuplicateClassification,
    FrameStatus,
    LogicalPosition,
    LogicalTelemetryKey,
    RawRowRef,
    ReconstructedFrame,
    ReconstructionIssueType,
    TimestampGroup,
)
from pipelines.frame_reconstruction.reconstruction_service import (
    ReconstructionInput,
    ReconstructionOutcome,
    reconstruct,
)
from pipelines.frame_reconstruction.topology import (
    FrameTopology,
    FrameTopologyResolver,
    TopologyBasis,
)

__all__ = [
    "NULL_TOKEN",
    "RECONSTRUCTION_VERSION",
    "CanonicalSerializer",
    "ChargerDayFrameMetrics",
    "DuplicateClassification",
    "FileReconstructionMetrics",
    "FrameStatus",
    "FrameTopology",
    "FrameTopologyResolver",
    "LogicalPosition",
    "LogicalTelemetryKey",
    "RawRowRef",
    "ReconstructedFrame",
    "ReconstructionInput",
    "ReconstructionIssueType",
    "ReconstructionOutcome",
    "TimestampGroup",
    "TopologyBasis",
    "reconstruct",
]
