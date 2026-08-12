"""Versioned registry of incoming charger CSV schemas.

A schema version is identified by the *header fingerprint* - a hash over the
ordered, duplicate-preserving list of raw header names.  Two files share a
schema version if and only if their raw headers are byte-for-byte equivalent in
name and order, which is exactly the property that makes a field dictionary
transferable between them.
"""

from __future__ import annotations

import datetime as dt
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
from backend.app.models.enums import SchemaCoverageStatus, SchemaVersionStatus

if TYPE_CHECKING:
    from backend.app.models.field_definition import FieldDefinition
    from backend.app.models.telemetry_file import TelemetryFile


class SchemaVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    header_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    field_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    duplicate_header_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    status: Mapped[SchemaVersionStatus] = mapped_column(
        enum_column(SchemaVersionStatus), nullable=False, default=SchemaVersionStatus.DRAFT
    )

    # --- dictionary coverage (Phase 1B, section 21) -----------------------
    coverage_status: Mapped[SchemaCoverageStatus] = mapped_column(
        enum_column(SchemaCoverageStatus), nullable=False, default=SchemaCoverageStatus.INCOMPLETE
    )
    mapped_field_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    unmapped_field_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    dictionary_revision: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow
    )

    field_definitions: Mapped[list[FieldDefinition]] = relationship(
        back_populates="schema_version",
        cascade="all, delete-orphan",
        order_by="FieldDefinition.source_position",
    )
    files: Mapped[list[TelemetryFile]] = relationship(back_populates="schema_version")

    __table_args__ = (
        sa.UniqueConstraint("header_fingerprint", name="uq_schema_version_header_fingerprint"),
        sa.UniqueConstraint("version", name="uq_schema_version_version"),
        sa.Index("ix_schema_version_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SchemaVersion v{self.version} {self.name} fields={self.field_count}>"
