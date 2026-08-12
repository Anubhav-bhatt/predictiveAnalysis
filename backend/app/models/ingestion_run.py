"""One execution of the ingestion pipeline over a source."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import (
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
    enum_column,
    utcnow,
)
from backend.app.models.enums import IngestionRunStatus, IngestionTrigger, SourceType

if TYPE_CHECKING:
    from backend.app.models.data_quality_issue import DataQualityIssue
    from backend.app.models.telemetry_file import TelemetryFile


class IngestionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_run"

    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType), nullable=False)
    trigger: Mapped[IngestionTrigger] = mapped_column(
        enum_column(IngestionTrigger), nullable=False, default=IngestionTrigger.CLI
    )
    status: Mapped[IngestionRunStatus] = mapped_column(
        enum_column(IngestionRunStatus), nullable=False, default=IngestionRunStatus.STARTED
    )

    #: The telemetry business date this collection cycle targets.  NULL for
    #: ad-hoc single-file runs from the CLI.
    business_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True, index=True)

    started_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )

    # Outcome counters, maintained by the orchestrator as each file resolves.
    # These are a point-in-time snapshot of the run for operational reporting;
    # live truth always remains derivable from telemetry_file.
    files_discovered: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_registered: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_ready: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_partial: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_duplicate: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_quarantined: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    files_failed: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # --- fleet reconciliation outcome (Phase 1C) --------------------------
    expected_charger_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    received_charger_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    missing_charger_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    late_charger_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    fleet_coverage_percentage: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(6, 3), nullable=True
    )

    # Correlation id when the run was initiated through the API (section 19).
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    files: Mapped[list[TelemetryFile]] = relationship(
        back_populates="ingestion_run",
        cascade="all, delete-orphan",
        foreign_keys="TelemetryFile.ingestion_run_id",
    )
    quality_issues: Mapped[list[DataQualityIssue]] = relationship(
        back_populates="ingestion_run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.Index("ix_ingestion_run_started_at", "started_at"),
        sa.Index("ix_ingestion_run_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<IngestionRun {self.id} {self.status} source={self.source_type}>"
