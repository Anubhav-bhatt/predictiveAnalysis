"""Expected fleet registry (Phase 1C, section 7).

Missing-data metrics are only meaningful against a declared expectation.  A
charger contributes to "missing" on a given business date only when it was
actually expected to send telemetry that date - which depends on its lifecycle
status and its telemetry window, not merely on its existence in this table.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from backend.app.models.enums import ChargerLifecycleStatus

if TYPE_CHECKING:
    from backend.app.models.charger_day_coverage import ChargerDayCoverage
    from backend.app.models.telemetry_gap import TelemetryGap


class Charger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "charger"

    #: Vendor charger identifier as it appears inside telemetry (e.g. D82510560390014).
    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    ocpp_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    site_code: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    lifecycle_status: Mapped[ChargerLifecycleStatus] = mapped_column(
        enum_column(ChargerLifecycleStatus), nullable=False, default=ChargerLifecycleStatus.ACTIVE
    )
    telemetry_expected: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    telemetry_start_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)
    telemetry_end_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)

    # Per-charger overrides for cadence/topology.  NULL means "fall back to the
    # configured global default" (section 10 precedence).
    expected_sampling_interval_seconds: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    expected_connector_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    expected_smr_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Source timezone for this charger's naive event timestamps (section 9).
    source_timezone: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    coverage_days: Mapped[list[ChargerDayCoverage]] = relationship(
        back_populates="charger", cascade="all, delete-orphan"
    )
    gaps: Mapped[list[TelemetryGap]] = relationship(
        back_populates="charger", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint("charger_id", name="uq_charger_charger_id"),
        sa.Index("ix_charger_lifecycle_status", "lifecycle_status"),
        sa.Index("ix_charger_site_code", "site_code"),
        sa.Index("ix_charger_ocpp_id", "ocpp_id"),
    )

    def is_expected_on(self, business_date: dt.date) -> bool:
        """Whether this charger should have delivered telemetry for a date.

        A charger is expected only when telemetry is switched on, its lifecycle
        status is one that produces data, and the date falls inside its
        configured telemetry window.
        """
        if not self.telemetry_expected:
            return False
        if self.lifecycle_status in {
            ChargerLifecycleStatus.DECOMMISSIONED,
            ChargerLifecycleStatus.TEMPORARILY_INACTIVE,
            ChargerLifecycleStatus.TEST,
        }:
            return False
        if self.telemetry_start_date and business_date < self.telemetry_start_date:
            return False
        return not (self.telemetry_end_date and business_date > self.telemetry_end_date)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Charger {self.charger_id} {self.lifecycle_status}>"
