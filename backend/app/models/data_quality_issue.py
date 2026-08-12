"""Persisted findings from the quality rules engine.

Determinism (section 39): every issue carries an ``issue_hash`` derived from the
rule code plus its stable locator (field identity, row number, entity
reference).  Re-analysing the same immutable file against the same schema
version therefore produces the same hashes, and the unique constraint on
``(telemetry_file_id, issue_hash)`` makes repeated runs converge instead of
accumulating duplicates.

Two scopes share this table, which is why ``telemetry_file_id`` is nullable:

*File-scope* issues (Phase 1A/1B) always have a file.

*Charger-day-scope* issues (Phase 1C section 28) may have no file at all - the
whole point of ``MISSING_CHARGER_DATA`` is that nothing arrived.  Those rows are
anchored to ``charger_day_coverage_id`` instead, with their own convergence key.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

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
from backend.app.models.enums import (
    FieldEntity,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)

if TYPE_CHECKING:
    from backend.app.models.ingestion_run import IngestionRun
    from backend.app.models.telemetry_file import TelemetryFile

#: Raw values are stored only as a short, truncated sample so an issue can be
#: understood without the table becoming a copy of the telemetry.
MAX_RAW_VALUE_CHARS = 128


class DataQualityIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_quality_issue"

    #: NULL for charger-day findings that have no originating file - a charger
    #: that delivered nothing cannot reference one.
    telemetry_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Set for CHARGER_DAY-scope findings (Phase 1C section 28).
    charger_day_coverage_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("charger_day_coverage.id", ondelete="CASCADE"), nullable=True, index=True
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("ingestion_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("field_definition.id", ondelete="SET NULL"), nullable=True, index=True
    )

    rule_code: Mapped[QualityIssueType] = mapped_column(
        enum_column(QualityIssueType), nullable=False
    )
    scope: Mapped[QualityRuleScope] = mapped_column(enum_column(QualityRuleScope), nullable=False)
    severity: Mapped[QualitySeverity] = mapped_column(enum_column(QualitySeverity), nullable=False)
    entity: Mapped[FieldEntity | None] = mapped_column(enum_column(FieldEntity), nullable=True)

    # Locators - all optional, populated only when the rule scope makes them
    # meaningful.
    field_name: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    field_occurrence: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_row_number: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    event_time: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    entity_reference: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    # Charger-day locators, populated for CHARGER_DAY scope so daily findings are
    # queryable without joining through coverage.
    charger_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    business_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)

    raw_value: Mapped[str | None] = mapped_column(sa.String(MAX_RAW_VALUE_CHARS), nullable=True)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    #: How many times this finding occurred; rules aggregate rather than
    #: emitting one row per affected telemetry row.
    occurrence_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=1)

    issue_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow
    )

    telemetry_file: Mapped[TelemetryFile | None] = relationship(back_populates="quality_issues")
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="quality_issues")

    __table_args__ = (
        sa.UniqueConstraint("telemetry_file_id", "issue_hash", name="uq_data_quality_issue_hash"),
        # Charger-day convergence key. Both scopes additionally use
        # delete-then-insert, so idempotency does not rely on NULL semantics
        # differing between PostgreSQL and SQLite.
        sa.UniqueConstraint(
            "charger_day_coverage_id", "issue_hash", name="uq_data_quality_issue_coverage_hash"
        ),
        sa.Index("ix_data_quality_issue_rule_code", "rule_code"),
        sa.Index("ix_data_quality_issue_severity", "severity"),
        sa.Index("ix_data_quality_issue_detected_at", "detected_at"),
        sa.Index("ix_data_quality_issue_file_severity", "telemetry_file_id", "severity"),
        sa.Index("ix_data_quality_issue_charger_date", "charger_id", "business_date"),
        sa.CheckConstraint("occurrence_count >= 1", name="occurrence_count_positive"),
        # Every issue must be attributable to something.
        sa.CheckConstraint(
            "telemetry_file_id IS NOT NULL OR charger_day_coverage_id IS NOT NULL",
            name="issue_has_an_anchor",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<DataQualityIssue {self.rule_code} {self.severity} field={self.field_name}>"
