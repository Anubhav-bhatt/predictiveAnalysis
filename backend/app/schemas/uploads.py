"""Upload batch response models (Phase 1C.5 sections 29-31, 41).

Internal paths never appear: ``staged_reference`` is absent from every model, and
files are identified by original filename and id only.

Status labels are mapped for humans in the frontend, not here — the API returns the
real enum so a client can reason about it, and the UI owns presentation.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backend.app.models.enums import (
    FileStatus,
    SourceType,
    UploadBatchStatus,
    UploadFileStatus,
)

__all__ = [
    "BatchFileRow",
    "StagedFileResult",
    "UploadBatchDetail",
    "UploadBatchRow",
    "UploadCounts",
    "UploadCreated",
]


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UploadCounts(_Base):
    """Derived outcome tallies. Computed per request, never stored."""

    total_files: int
    pending: int = 0
    processing: int = 0
    completed: int = 0
    duplicate: int = 0
    failed: int = 0
    quarantined: int = 0
    rejected: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_percentage(self) -> float:
        """Share of files that have reached a terminal outcome."""
        if self.total_files <= 0:
            return 0.0
        settled = self.completed + self.duplicate + self.failed + self.quarantined + self.rejected
        return round(100.0 * min(settled, self.total_files) / self.total_files, 2)


class UploadLimits(_Base):
    """Server-enforced limits, published so the UI can pre-check honestly.

    The browser must not carry its own copy of these numbers: an operator who
    raises ``CPI_UPLOAD_MAX_FILE_SIZE_BYTES`` would otherwise see the UI reject a
    file the server would happily accept.
    """

    max_files_per_batch: int
    max_file_size_bytes: int
    max_batch_size_bytes: int
    allowed_extensions: list[str]


class StagedFileResult(_Base):
    """Per-file outcome of the staging request itself."""

    original_filename: str
    size_bytes: int
    status: UploadFileStatus
    reason: str | None = None


class UploadCreated(_Base):
    """Response to a bulk upload: the batch id plus what was staged.

    Returned as soon as bytes are safe. Processing has *not* happened yet - the
    worker picks the batch up next, which is why ``status`` is REGISTERED rather
    than COMPLETED.
    """

    upload_batch_id: UUID
    status: UploadBatchStatus
    file_count: int
    total_bytes: int
    staged: list[StagedFileResult] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accepted_count(self) -> int:
        return sum(1 for item in self.staged if item.status is UploadFileStatus.PENDING)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rejected_count(self) -> int:
        return sum(1 for item in self.staged if item.status is UploadFileStatus.REJECTED)


class UploadBatchRow(_Base):
    """One batch in the history list (section 31)."""

    id: UUID
    source_type: SourceType
    status: UploadBatchStatus
    created_at: dt.datetime
    file_count: int
    total_bytes: int
    upload_completed_at: dt.datetime | None = None
    processing_started_at: dt.datetime | None = None
    processing_completed_at: dt.datetime | None = None
    uploaded_by: str | None = None
    counts: UploadCounts | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def processing_duration_seconds(self) -> float | None:
        if self.processing_started_at is None or self.processing_completed_at is None:
            return None
        delta = self.processing_completed_at - self.processing_started_at
        return round(delta.total_seconds(), 3)


class BatchFileRow(_Base):
    """One file within a batch (section 39).

    ``telemetry_status`` is the authoritative processing state, read from the
    telemetry file rather than duplicated here. It is null until registration, so
    the UI can show "—" instead of a fabricated zero.
    """

    original_filename: str
    size_bytes: int
    status: UploadFileStatus
    telemetry_file_id: UUID | None = None
    duplicate_of_file_id: UUID | None = None
    failure_reason: str | None = None
    staged_at: dt.datetime
    registered_at: dt.datetime | None = None

    telemetry_status: FileStatus | None = None
    charger_id: str | None = None
    business_date: dt.date | None = None
    row_count: int | None = None
    unique_event_timestamp_count: int | None = None
    quality_score: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_duplicate(self) -> bool:
        return self.status is UploadFileStatus.DUPLICATE


class UploadBatchDetail(_Base):
    """Batch header plus derived counts (section 29)."""

    batch: UploadBatchRow
    counts: UploadCounts
