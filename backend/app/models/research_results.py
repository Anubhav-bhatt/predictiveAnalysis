"""Research results persistence models (Phase 9).

Stores discovered pattern candidates and analytical dataset run metadata.
"""

from __future__ import annotations

import datetime as dt
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
)
from backend.app.models.enums import (
    AnalyticalGrain,
    PatternCategory,
    PatternEvidenceLevel,
)

__all__ = [
    "AnalyticalDatasetRun",
    "PatternCandidateRecord",
]


class PatternCandidateRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A discovered telemetry pattern candidate with graduated evidence scoring."""

    __tablename__ = "pattern_candidate"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    pattern_category: Mapped[PatternCategory] = mapped_column(
        enum_column(PatternCategory), nullable=False, index=True
    )
    evidence_level: Mapped[PatternEvidenceLevel] = mapped_column(
        enum_column(PatternEvidenceLevel), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)

    affected_signals: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    affected_components: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)

    observation_window_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    observation_window_end: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    supporting_evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONVariant, nullable=True
    )

    analytical_grain: Mapped[AnalyticalGrain | None] = mapped_column(
        enum_column(AnalyticalGrain), nullable=True
    )
    dataset_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")
    scan_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")

    __table_args__ = (
        sa.Index(
            "ix_pattern_candidate_lookup",
            "charger_id",
            "pattern_category",
            "evidence_level",
        ),
    )


class AnalyticalDatasetRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks metadata for each analytical dataset build run."""

    __tablename__ = "analytical_dataset_run"

    grain: Mapped[AnalyticalGrain] = mapped_column(
        enum_column(AnalyticalGrain), nullable=False, index=True
    )
    charger_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)

    record_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    signal_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    observation_window_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    observation_window_end: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    gap_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    missing_rate: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)

    dataset_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="v1")
    duration_ms: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
