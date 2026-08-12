"""Delivery status of one charger for one telemetry business date (Phase 1C).

This entity is deliberately *not* a health score and *not* a prediction.  It
answers one operational question: how much of this charger-day's telemetry do we
actually have, and did it arrive when expected?

Identity is ``(charger_id, business_date)``.  Reconciliation therefore upserts
rather than inserts, which is what makes ``run-daily`` and ``reconcile``
idempotent (section 41) - a late file flips MISSING to LATE/COMPLETE in place.

Coverage is computed from *unique event timestamps*, never raw row count
(section 11): with 2 connectors x 4 SMRs the raw grain is 8 rows per timestamp,
and replayed frames inflate row counts without adding real observations.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UtcDateTime, UUIDPrimaryKeyMixin, enum_column
from backend.app.models.enums import ArrivalStatus, CompletenessStatus

if TYPE_CHECKING:
    from backend.app.models.charger import Charger
    from backend.app.models.data_quality_issue import DataQualityIssue
    from backend.app.models.telemetry_file import TelemetryFile
    from backend.app.models.telemetry_gap import TelemetryGap


class ChargerDayCoverage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "charger_day_coverage"

    charger_pk: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("charger.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Denormalised so that telemetry from an unregistered charger (an
    #: UNEXPECTED arrival) can still be recorded without a registry row.
    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    business_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    expected: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    file_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    primary_telemetry_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="SET NULL"), nullable=True
    )

    # --- observed window --------------------------------------------------
    first_event_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    last_event_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    unique_timestamp_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    expected_timestamp_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- cadence ----------------------------------------------------------
    expected_sampling_interval_seconds: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    observed_median_sampling_interval_seconds: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 3), nullable=True
    )
    observed_p95_sampling_interval_seconds: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 3), nullable=True
    )
    observed_min_sampling_interval_seconds: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 3), nullable=True
    )
    observed_max_sampling_interval_seconds: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 3), nullable=True
    )

    # --- coverage dimensions (section 12) ---------------------------------
    # span:   how much of the day lies between first and last event
    # sample: how many of the expected observations actually exist
    # gap-adjusted: span minus time lost inside detected gaps
    coverage_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    expected_coverage_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    span_coverage_percentage: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(6, 3), nullable=True
    )
    sample_coverage_percentage: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(6, 3), nullable=True
    )
    gap_adjusted_coverage_percentage: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(6, 3), nullable=True
    )
    #: Headline number; equals sample coverage, which is the signal that cannot
    #: be inflated by replayed rows.
    coverage_percentage: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3), nullable=True)

    # --- gaps -------------------------------------------------------------
    largest_gap_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    gap_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_gap_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- duplication / overlap (quantified only; resolved in Phase 1D) ----
    duplicate_timestamp_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    logical_collision_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    overlapping_timestamp_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    duplicate_file_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # --- topology ---------------------------------------------------------
    connector_count_detected: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    smr_count_detected: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    expected_connector_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    expected_smr_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- status -----------------------------------------------------------
    arrival_status: Mapped[ArrivalStatus] = mapped_column(
        enum_column(ArrivalStatus), nullable=False, default=ArrivalStatus.EXPECTED
    )
    completeness_status: Mapped[CompletenessStatus] = mapped_column(
        enum_column(CompletenessStatus), nullable=False, default=CompletenessStatus.UNKNOWN
    )

    first_received_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    late_by_seconds: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)

    #: File-level quality stays on telemetry_file; this is the aggregate for the
    #: day and is intentionally a separate number (section 25).
    quality_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)

    last_evaluated_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )

    charger: Mapped[Charger | None] = relationship(back_populates="coverage_days")
    primary_file: Mapped[TelemetryFile | None] = relationship()
    gaps: Mapped[list[TelemetryGap]] = relationship(
        back_populates="coverage", cascade="all, delete-orphan"
    )
    #: CHARGER_DAY-scope findings (section 28). Separate from file quality, which
    #: stays on telemetry_file and is never overwritten by these (section 25).
    quality_issues: Mapped[list[DataQualityIssue]] = relationship(
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint("charger_id", "business_date", name="uq_charger_day_coverage_identity"),
        sa.Index("ix_charger_day_coverage_business_date", "business_date"),
        sa.Index("ix_charger_day_coverage_arrival", "business_date", "arrival_status"),
        sa.Index("ix_charger_day_coverage_completeness", "business_date", "completeness_status"),
        sa.CheckConstraint("file_count >= 0", name="file_count_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ChargerDayCoverage {self.charger_id} {self.business_date} "
            f"{self.arrival_status}/{self.completeness_status} {self.coverage_percentage}%>"
        )
