"""Bulk manual upload batches (Phase 1C.5 sections 7, 9).

**Manual upload is the initial POC acquisition path. It is not a separate
analytical workflow.** A batch groups files that an operator delivered together so
that delivery can be watched and audited. Nothing downstream reasons about batches:
profiling, schema validation, quality, coverage and frame reconstruction all see a
registered ``telemetry_file`` and neither know nor care how it arrived. When RMS
access exists it becomes another adapter feeding the same pipeline.

Two tables:

``upload_batch``
    The delivery itself: when, how many files, how many bytes, what state.

``upload_batch_file``
    One staged file. It exists from the moment bytes land in staging, which is what
    lets the UI show a file list *before* the worker has registered anything. Once
    registration succeeds it points at the resulting ``telemetry_file``, and that
    row becomes the authority on the file's real lifecycle - this table never
    duplicates ``FileStatus``.

Outcome counts are **derived**, not stored. A batch's completed/failed/duplicate
tallies are computed from its linked files, so a counter can never drift out of
step with the files it claims to describe. Only ``file_count`` and ``total_bytes``
are persisted, because those are properties of the delivery that are fixed at
staging time and cannot be re-derived once a staged file is cleaned up.
"""

from __future__ import annotations

import datetime as dt
import uuid
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
from backend.app.models.enums import SourceType, UploadBatchStatus, UploadFileStatus

if TYPE_CHECKING:
    from backend.app.models.telemetry_file import TelemetryFile


class UploadBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "upload_batch"

    #: Which acquisition path delivered this batch. MANUAL_UPLOAD today; the
    #: column exists so a future RMS pull batch is representable without a schema
    #: change.
    source_type: Mapped[SourceType] = mapped_column(
        enum_column(SourceType), nullable=False, default=SourceType.MANUAL_UPLOAD
    )
    status: Mapped[UploadBatchStatus] = mapped_column(
        enum_column(UploadBatchStatus), nullable=False, default=UploadBatchStatus.CREATED
    )

    #: Fixed at staging time and not re-derivable afterwards, so persisted.
    file_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)

    upload_started_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    upload_completed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    processing_started_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    processing_completed_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )

    #: Populated only when the deployment has authentication. The platform has
    #: none yet, so this stays NULL rather than inventing an identity.
    uploaded_by: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    #: Batch-level failure (e.g. the request itself was rejected). Per-file
    #: reasons live on upload_batch_file.
    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    files: Mapped[list[UploadBatchFile]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="UploadBatchFile.original_filename",
    )

    __table_args__ = (
        sa.Index("ix_upload_batch_created_at", "created_at"),
        sa.Index("ix_upload_batch_status", "status"),
        sa.CheckConstraint("file_count >= 0", name="file_count_non_negative"),
        sa.CheckConstraint("total_bytes >= 0", name="total_bytes_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<UploadBatch {self.id} {self.status} files={self.file_count}>"


class UploadBatchFile(UUIDPrimaryKeyMixin, Base):
    """One file staged as part of a batch.

    Exists before registration, so the UI can list what was uploaded while the
    worker is still working. ``telemetry_file_id`` is the bridge into the common
    pipeline; once set, that file's ``FileStatus`` is authoritative.
    """

    __tablename__ = "upload_batch_file"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("upload_batch.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: As the operator's browser reported it. Metadata only - never used as a
    #: filesystem path, and never trusted for a telemetry date.
    original_filename: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)

    #: Internal staging reference, generated by the platform. Never returned by
    #: the API.
    staged_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    #: Computed at staging so cross-source duplicate detection can run before the
    #: worker touches the file.
    sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    status: Mapped[UploadFileStatus] = mapped_column(
        enum_column(UploadFileStatus), nullable=False, default=UploadFileStatus.PENDING
    )
    #: Set once the file entered the common pipeline. NULL for rejected files and
    #: for duplicates that resolved to an existing file (which is recorded in
    #: duplicate_of_file_id instead).
    telemetry_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="SET NULL"), nullable=True
    )
    #: For a duplicate: the already-registered file this content matches.
    duplicate_of_file_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="SET NULL"), nullable=True
    )

    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    staged_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow
    )
    registered_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    batch: Mapped[UploadBatch] = relationship(back_populates="files")
    telemetry_file: Mapped[TelemetryFile | None] = relationship(
        foreign_keys=[telemetry_file_id]
    )
    duplicate_of: Mapped[TelemetryFile | None] = relationship(
        foreign_keys=[duplicate_of_file_id]
    )

    __table_args__ = (
        # One staged entry per filename per batch. Re-presenting the same batch
        # converges rather than accumulating.
        sa.UniqueConstraint(
            "batch_id", "original_filename", name="uq_upload_batch_file_identity"
        ),
        sa.Index("ix_upload_batch_file_status", "status"),
        sa.Index("ix_upload_batch_file_sha256", "sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<UploadBatchFile {self.original_filename} {self.status}>"
