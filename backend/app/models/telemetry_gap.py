"""A stretch of a charger-day with no telemetry (Phase 1C, sections 13-15).

A gap is an *interval between two consecutive observed event timestamps* that
exceeds ``expected_interval x multiplier``.  The multiplier is configuration,
never a literal in the detector, because cadence varies by charger and model.

Gaps are fully recomputed for a charger-day whenever that day is evaluated, and
the recomputation deletes the previous set first.  That is what keeps gap state
deterministic and prevents stale records surviving after a late file fills a hole
(section 44).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, UtcDateTime, UUIDPrimaryKeyMixin, enum_column, utcnow
from backend.app.models.enums import GapSeverity

if TYPE_CHECKING:
    from backend.app.models.charger import Charger
    from backend.app.models.charger_day_coverage import ChargerDayCoverage


class TelemetryGap(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telemetry_gap"

    coverage_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("charger_day_coverage.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charger_pk: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("charger.id", ondelete="CASCADE"), nullable=True, index=True
    )
    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    business_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    telemetry_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="SET NULL"), nullable=True
    )

    start_event_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False)
    end_event_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    expected_interval_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    estimated_missing_samples: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    severity: Mapped[GapSeverity] = mapped_column(enum_column(GapSeverity), nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)

    coverage: Mapped[ChargerDayCoverage] = relationship(back_populates="gaps")
    charger: Mapped[Charger | None] = relationship(back_populates="gaps")

    __table_args__ = (
        # Deterministic gap identity: a gap is uniquely located by the day it
        # belongs to and the two observations that bracket it.
        sa.UniqueConstraint(
            "coverage_id", "start_event_at", "end_event_at", name="uq_telemetry_gap_identity"
        ),
        sa.Index("ix_telemetry_gap_charger_date", "charger_id", "business_date"),
        sa.Index("ix_telemetry_gap_severity", "severity"),
        sa.CheckConstraint("duration_seconds > 0", name="duration_positive"),
        sa.CheckConstraint("end_event_at > start_event_at", name="gap_interval_ordered"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TelemetryGap {self.charger_id} {self.business_date} "
            f"{self.duration_seconds}s {self.severity}>"
        )
