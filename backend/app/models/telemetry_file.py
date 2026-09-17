"""Bronze-layer registration record for one discovered telemetry file.

One row is the *logical source file*.  Re-presenting byte-identical content
under the same name is idempotent (it resolves to this row); byte-identical
content arriving under a different name is recorded as a ``DUPLICATE`` row that
points back at the canonical one, so the arrival is auditable without creating a
second logical file.

``storage_reference`` is internal and is never serialised into an API response
(section 20 - do not leak local filesystem paths).
"""

from __future__ import annotations

import datetime as dt
import uuid
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
from backend.app.models.enums import FileDateSpan, FileStatus, SchemaCompatibility, SourceType

if TYPE_CHECKING:
    from backend.app.models.data_quality_issue import DataQualityIssue
    from backend.app.models.field_profile import FieldProfile
    from backend.app.models.ingestion_run import IngestionRun
    from backend.app.models.schema_version import SchemaVersion
    from backend.app.models.telemetry_file_day import TelemetryFileDay


class TelemetryFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_file"

    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("ingestion_run.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Set when this file arrived through a bulk manual upload. NULL for files
    #: discovered from a filesystem or, later, pulled from RMS. Metadata only -
    #: no downstream stage branches on it.
    upload_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("upload_batch.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- provenance -------------------------------------------------------
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType), nullable=False)
    original_filename: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    source_reference: Mapped[str] = mapped_column(sa.Text, nullable=False)
    storage_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)

    status: Mapped[FileStatus] = mapped_column(
        enum_column(FileStatus), nullable=False, default=FileStatus.DISCOVERED
    )
    duplicate_of_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="SET NULL"), nullable=True
    )

    # --- shape ------------------------------------------------------------
    row_count: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    column_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    connector_count_detected: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    smr_count_detected: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    session_id_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- event time (parsed from content, never from the filename) --------
    event_time_min: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    event_time_max: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    event_time_format: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    #: Business date derived from telemetry content only.  When a file spans
    #: more than one date this holds the *dominant* date (most unique
    #: timestamps); every date the file touches gets its own coverage record.
    business_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True, index=True)
    distinct_business_date_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    file_date_span: Mapped[FileDateSpan | None] = mapped_column(
        enum_column(FileDateSpan), nullable=True
    )
    #: Date parsed out of the filename, retained as *metadata only* so the
    #: mismatch can be reported.  It never influences business_date.
    filename_date: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)
    unique_event_timestamp_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    median_sampling_interval_seconds: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 3), nullable=True
    )
    invalid_timestamp_count: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)

    # --- duplicate / replay profile (classified only, never resolved here) -
    exact_duplicate_row_count: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    duplicate_participating_row_count: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    logical_key_collision_group_count: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    logical_key_conflicting_group_count: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    max_occurrences_per_logical_key: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- field shape summary ---------------------------------------------
    empty_field_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    constant_field_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    varying_field_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    duplicate_header_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- lifecycle timestamps --------------------------------------------
    discovered_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow
    )
    received_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    processed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    profiling_duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    schema_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("schema_version.id", ondelete="SET NULL"), nullable=True, index=True
    )
    header_fingerprint: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    schema_compatibility: Mapped[SchemaCompatibility | None] = mapped_column(
        enum_column(SchemaCompatibility), nullable=True
    )

    # --- transparent quality score (section 28) ---------------------------
    # Each dimension is computed independently and stored; ``quality_score`` is
    # their configured weighted mean, so a low score can always be attributed.
    quality_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    schema_quality: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    completeness_quality: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    validity_quality: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    duplicate_quality: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    timestamp_quality: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), nullable=True)

    # --- failure context --------------------------------------------------
    quarantine_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # Field-level profile is written as an immutable JSON artifact; the
    # reference is internal, like storage_reference.
    profile_artifact_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    ingestion_run: Mapped[IngestionRun | None] = relationship(
        back_populates="files", foreign_keys=[ingestion_run_id]
    )
    schema_version: Mapped[SchemaVersion | None] = relationship(back_populates="files")
    identifiers: Mapped[list[TelemetryFileIdentifier]] = relationship(
        back_populates="telemetry_file", cascade="all, delete-orphan"
    )
    quality_issues: Mapped[list[DataQualityIssue]] = relationship(
        back_populates="telemetry_file", cascade="all, delete-orphan"
    )
    field_profiles: Mapped[list[FieldProfile]] = relationship(
        back_populates="telemetry_file",
        cascade="all, delete-orphan",
        order_by="FieldProfile.source_position",
    )
    #: One row per *actual* telemetry date in this file - a multi-day file has
    #: several (Phase 1C section 8).
    file_days: Mapped[list[TelemetryFileDay]] = relationship(
        back_populates="telemetry_file",
        cascade="all, delete-orphan",
        order_by="TelemetryFileDay.business_date",
    )

    __table_args__ = (
        # Idempotency boundary: identical bytes under the same name is the same
        # logical file, no matter how many times it is presented.
        sa.UniqueConstraint("sha256", "original_filename", name="uq_telemetry_file_sha256_name"),
        sa.Index("ix_telemetry_file_sha256", "sha256"),
        sa.Index("ix_telemetry_file_status", "status"),
        sa.Index("ix_telemetry_file_event_time_min", "event_time_min"),
        sa.Index("ix_telemetry_file_received_at", "received_at"),
        sa.CheckConstraint("file_size_bytes >= 0", name="file_size_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TelemetryFile {self.id} {self.original_filename} {self.status}>"


class TelemetryFileIdentifier(UUIDPrimaryKeyMixin, Base):
    """Business identifiers observed inside a file.

    Charger ids, OCPP ids and session ids are multi-valued, queryable facts, so
    they are modelled relationally rather than as a JSON blob on the parent
    (section 7 - normalized design where arrays/JSON are inappropriate).
    """

    __tablename__ = "telemetry_file_identifier"

    telemetry_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    value: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)

    telemetry_file: Mapped[TelemetryFile] = relationship(back_populates="identifiers")

    __table_args__ = (
        sa.UniqueConstraint(
            "telemetry_file_id",
            "identifier_type",
            "value",
            name="uq_telemetry_file_identifier_value",
        ),
        sa.Index("ix_telemetry_file_identifier_lookup", "identifier_type", "value"),
    )


class IdentifierType:
    """Identifier kinds recorded in :class:`TelemetryFileIdentifier`."""

    CHARGER = "CHARGER"
    OCPP = "OCPP"
    SESSION = "SESSION"
    CONNECTOR = "CONNECTOR"
    SMR = "SMR"
