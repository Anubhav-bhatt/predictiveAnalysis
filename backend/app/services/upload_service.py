"""Bulk manual upload staging and batch processing (Phase 1C.5).

Two distinct responsibilities, deliberately split so the HTTP request stays short
(sections 11, 13):

``stage_batch``  — runs inside the request
    Validates each file, streams its bytes to a per-batch staging directory,
    computes SHA-256, and records one ``upload_batch_file`` row. Returns a batch
    id. It does **no** profiling, schema work, quality work, coverage or frame
    reconstruction.

``process_batch`` — runs in the worker
    Builds a :class:`ManualUploadTelemetrySource` over the staged files and calls
    the *same* ``IngestionService.run`` the filesystem source uses, then the same
    coverage reconciliation and frame reconstruction. From that point nothing
    branches on source type.

That boundary is the whole architecture: **source-specific behaviour ends before
profiling begins.** When RMS access exists it becomes another adapter and this
module is the only kind of code that needs writing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger, log_context
from backend.app.models.enums import (
    IngestionTrigger,
    SourceType,
    UploadBatchStatus,
    UploadFileStatus,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.upload_batch import UploadBatchFile
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.frame_service import FrameReconstructionService
from backend.app.services.ingestion_service import IngestionService, RunSummary
from pipelines.sources.manual_upload import ManualUploadTelemetrySource, StagedUpload

__all__ = [
    "BatchProcessingResult",
    "StagedFileOutcome",
    "UploadRejected",
    "UploadService",
    "safe_staged_name",
]

logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STAGED_NAME = 120


class UploadRejected(ValueError):
    """The upload request itself is invalid - nothing was staged."""


@dataclass(frozen=True, slots=True)
class StagedFileOutcome:
    """Result of staging one file."""

    original_filename: str
    size_bytes: int
    status: UploadFileStatus
    sha256: str | None = None
    staged_reference: str | None = None
    rejection_reason: str | None = None
    duplicate_of_file_id: UUID | None = None


@dataclass(slots=True)
class BatchProcessingResult:
    """Outcome of running a staged batch through the common pipeline."""

    batch_id: UUID
    files_registered: int = 0
    files_ready: int = 0
    #: Files whose content the platform already held. Reported separately from
    #: ``files_duplicate`` because they are counted at different points: a file
    #: recognised before registration is *skipped*, one recognised during
    #: processing is *duplicate*. Both mean "already present"; collapsing them
    #: would hide which check caught it.
    files_already_present: int = 0
    files_duplicate: int = 0
    files_failed: int = 0
    files_quarantined: int = 0
    frames_reconstructed: int = 0
    dates_reconciled: list[dt.date] = field(default_factory=list)
    status: UploadBatchStatus = UploadBatchStatus.PROCESSING

    def as_dict(self) -> dict[str, object]:
        return {
            "batch_id": str(self.batch_id),
            "status": self.status.value,
            "files_registered": self.files_registered,
            "files_ready": self.files_ready,
            "files_already_present": self.files_already_present,
            "files_duplicate": self.files_duplicate,
            "files_failed": self.files_failed,
            "files_quarantined": self.files_quarantined,
            "frames_reconstructed": self.frames_reconstructed,
            "dates_reconciled": [d.isoformat() for d in self.dates_reconciled],
        }


def safe_staged_name(original: str) -> str:
    """Reduce an untrusted filename to something safe to place on disk.

    Path separators and traversal segments are removed rather than escaped, so the
    result cannot resolve outside the staging directory. The original name survives
    untouched in the database as metadata (section 15).
    """
    name = Path(original).name  # discards any directory component
    name = name.replace("..", "_")
    name = _UNSAFE.sub("_", name).strip("._-")
    if not name:
        name = "upload"
    if len(name) > _MAX_STAGED_NAME:
        stem, dot, suffix = name.rpartition(".")
        keep = _MAX_STAGED_NAME - (len(suffix) + 1 if dot else 0)
        name = f"{stem[:keep]}.{suffix}" if dot else name[:_MAX_STAGED_NAME]
    return name


class UploadService:
    def __init__(
        self,
        *,
        upload_repo: UploadRepository,
        settings: Settings,
    ) -> None:
        self._uploads = upload_repo
        self._settings = settings

    # -- staging (request path) -------------------------------------------

    async def stage_batch(
        self,
        files: Sequence[tuple[str, AsyncIterator[bytes]]],
        *,
        uploaded_by: str | None = None,
    ) -> tuple[UUID, list[StagedFileOutcome]]:
        """Validate and stage an upload request, returning the batch id.

        Every file is validated again here regardless of what the browser checked -
        client-side validation is a UX affordance, never a control.
        """
        limits = self._settings.upload
        if not files:
            raise UploadRejected("No files were supplied")
        if len(files) > limits.max_files_per_batch:
            raise UploadRejected(
                f"{len(files)} files exceeds the configured maximum of "
                f"{limits.max_files_per_batch} per batch"
            )

        batch = await self._uploads.create_batch(
            source_type=SourceType.MANUAL_UPLOAD,
            status=UploadBatchStatus.UPLOADING,
            upload_started_at=dt.datetime.now(dt.UTC),
            file_count=0,
            total_bytes=0,
        )

        staging_dir = Path(limits.staging_root) / str(batch.id)
        staging_dir.mkdir(parents=True, exist_ok=True)

        outcomes: list[StagedFileOutcome] = []
        rows: list[dict[str, object]] = []
        total_bytes = 0
        seen_in_batch: dict[str, str] = {}

        with log_context(upload_batch_id=batch.id):
            for index, (original_filename, chunks) in enumerate(files):
                outcome = await self._stage_one(
                    original_filename=original_filename,
                    chunks=chunks,
                    staging_dir=staging_dir,
                    index=index,
                    bytes_so_far=total_bytes,
                    seen_in_batch=seen_in_batch,
                )
                outcomes.append(outcome)
                total_bytes += outcome.size_bytes
                rows.append(
                    {
                        "id": uuid4(),
                        "batch_id": batch.id,
                        "original_filename": outcome.original_filename,
                        "size_bytes": outcome.size_bytes,
                        "staged_reference": outcome.staged_reference,
                        "sha256": outcome.sha256,
                        "status": outcome.status,
                        "telemetry_file_id": None,
                        "duplicate_of_file_id": outcome.duplicate_of_file_id,
                        "failure_reason": outcome.rejection_reason,
                        "staged_at": dt.datetime.now(dt.UTC),
                        "registered_at": None,
                    }
                )

            await self._uploads.add_files(rows)

            batch.file_count = len(rows)
            batch.total_bytes = total_bytes
            batch.upload_completed_at = dt.datetime.now(dt.UTC)
            # REGISTERED means "staged and queued for the worker" - the bytes are
            # safe, but nothing has been profiled yet.
            batch.status = UploadBatchStatus.REGISTERED

            logger.info(
                "upload.batch_staged",
                source_type=SourceType.MANUAL_UPLOAD.value,
                batch_status=batch.status.value,
                file_count=batch.file_count,
                total_bytes=batch.total_bytes,
                rejected=sum(
                    1 for o in outcomes if o.status is UploadFileStatus.REJECTED
                ),
            )
        return batch.id, outcomes

    async def _stage_one(
        self,
        *,
        original_filename: str,
        chunks: AsyncIterator[bytes],
        staging_dir: Path,
        index: int,
        bytes_so_far: int,
        seen_in_batch: dict[str, str],
    ) -> StagedFileOutcome:
        """Stream one file to staging, validating as it goes."""
        limits = self._settings.upload
        display = original_filename or f"upload-{index}"

        suffix = Path(display).suffix.lower()
        if limits.allowed_extensions and suffix not in limits.allowed_extensions:
            await _drain(chunks)
            return StagedFileOutcome(
                original_filename=display,
                size_bytes=0,
                status=UploadFileStatus.REJECTED,
                rejection_reason=(
                    f"Extension {suffix or '<none>'} is not permitted "
                    f"(allowed: {', '.join(limits.allowed_extensions)})"
                ),
            )

        # A unique internal name: the operator's filename is never a path.
        staged_path = staging_dir / f"{index:05d}-{uuid4().hex[:8]}-{safe_staged_name(display)}"
        digest = hashlib.sha256()
        size = 0
        rejection: str | None = None

        try:
            with staged_path.open("wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > limits.max_file_size_bytes:
                        rejection = (
                            f"File exceeds the configured maximum of "
                            f"{limits.max_file_size_bytes} bytes"
                        )
                        break
                    if bytes_so_far + size > limits.max_batch_size_bytes:
                        rejection = (
                            f"Batch exceeds the configured maximum of "
                            f"{limits.max_batch_size_bytes} bytes"
                        )
                        break
                    digest.update(chunk)
                    handle.write(chunk)
        except OSError as exc:  # pragma: no cover - disk-level failure
            rejection = f"Could not stage file: {exc}"

        if rejection is not None:
            staged_path.unlink(missing_ok=True)
            return StagedFileOutcome(
                original_filename=display,
                size_bytes=size,
                status=UploadFileStatus.REJECTED,
                rejection_reason=rejection,
            )

        if size == 0:
            staged_path.unlink(missing_ok=True)
            return StagedFileOutcome(
                original_filename=display,
                size_bytes=0,
                status=UploadFileStatus.REJECTED,
                rejection_reason="File is empty",
            )

        checksum = digest.hexdigest()

        # Identical bytes twice in one request: stage once. Cross-batch and
        # cross-source duplicates are caught later by the existing SHA-256
        # identity in the ingestion service, which is the single authority.
        if checksum in seen_in_batch:
            staged_path.unlink(missing_ok=True)
            return StagedFileOutcome(
                original_filename=display,
                size_bytes=size,
                status=UploadFileStatus.DUPLICATE,
                sha256=checksum,
                rejection_reason=(
                    f"Identical content to {seen_in_batch[checksum]!r} in this upload; "
                    f"staged once"
                ),
            )
        seen_in_batch[checksum] = display

        return StagedFileOutcome(
            original_filename=display,
            size_bytes=size,
            status=UploadFileStatus.PENDING,
            sha256=checksum,
            staged_reference=str(staged_path),
        )

    async def batch_status(self, batch_id: UUID) -> UploadBatchStatus:
        """Current batch status, for the upload response."""
        batch = await self._uploads.get_batch(batch_id)
        return batch.status if batch else UploadBatchStatus.FAILED

    # -- processing (worker path) ------------------------------------------

    async def process_batch(
        self,
        batch_id: UUID,
        *,
        ingestion: IngestionService,
        coverage: CoverageService,
        frames: FrameReconstructionService | None = None,
    ) -> BatchProcessingResult:
        """Run a staged batch through the common pipeline.

        Uses the same ``IngestionService.run`` as the filesystem source. There is
        deliberately no manual-upload branch below this point.
        """
        result = BatchProcessingResult(batch_id=batch_id)
        batch = await self._uploads.get_batch(batch_id)
        if batch is None:
            raise UploadRejected(f"Upload batch {batch_id} does not exist")

        staged_rows = await self._uploads.staged_files(batch_id)
        with log_context(upload_batch_id=batch_id):
            batch.status = UploadBatchStatus.PROCESSING
            batch.processing_started_at = dt.datetime.now(dt.UTC)

            if not staged_rows:
                batch.status = await self._uploads.resolve_batch_status(batch_id)
                batch.processing_completed_at = dt.datetime.now(dt.UTC)
                result.status = batch.status
                return result

            staged = [
                StagedUpload(
                    staged_path=Path(str(row.staged_reference)),
                    original_filename=row.original_filename,
                    size_bytes=row.size_bytes,
                    staged_at=row.staged_at,
                )
                for row in staged_rows
                if row.staged_reference
            ]
            source = ManualUploadTelemetrySource(
                staged,
                staging_root=Path(self._settings.upload.staging_root),
                max_size_bytes=self._settings.upload.max_file_size_bytes,
            )

            # THE common pipeline. Identical call the filesystem source makes.
            summary = await ingestion.run(source, trigger=IngestionTrigger.WORKER)

            result.files_registered = summary.files_registered
            result.files_ready = summary.files_ready
            result.files_already_present = summary.files_skipped
            result.files_duplicate = summary.files_duplicate
            result.files_failed = summary.files_failed
            result.files_quarantined = summary.files_quarantined

            await self._link_outcomes(batch_id, summary, staged_rows)

            # Coverage for whichever business dates the telemetry actually
            # contains - never the upload date (Phase 1C section 8).
            file_ids = [
                outcome.telemetry_file_id
                for outcome in summary.outcomes
                if outcome.telemetry_file_id is not None
            ]
            dates = list(await ingestion.files.dates_touched_by_files(file_ids))
            if dates:
                await coverage.reconcile_dates(dates)
                result.dates_reconciled = dates

            # Phase 1D on the same files, with no source-specific handling.
            if frames is not None:
                for file_id in file_ids:
                    telemetry_file = await ingestion.files.get(file_id)
                    if telemetry_file is None:
                        continue
                    try:
                        outcome = await frames.reconstruct_file(telemetry_file)
                    except Exception as exc:  # noqa: BLE001 - one file must not stop the batch
                        logger.exception(
                            "upload.reconstruction_failed",
                            telemetry_file_id=str(file_id),
                            error=str(exc),
                        )
                        continue
                    if outcome.outcome is not None:
                        result.frames_reconstructed += (
                            outcome.outcome.metrics.frames_reconstructed
                        )

            batch.status = await self._uploads.resolve_batch_status(batch_id)
            batch.processing_completed_at = dt.datetime.now(dt.UTC)
            result.status = batch.status

            logger.info(
                "upload.batch_processed",
                source_type=SourceType.MANUAL_UPLOAD.value,
                batch_status=batch.status.value,
                files_registered=result.files_registered,
                files_ready=result.files_ready,
                files_already_present=result.files_already_present,
                files_duplicate=result.files_duplicate,
                files_failed=result.files_failed,
                files_quarantined=result.files_quarantined,
                frames_reconstructed=result.frames_reconstructed,
                dates_reconciled=[d.isoformat() for d in result.dates_reconciled],
            )
        return result

    async def _link_outcomes(
        self,
        batch_id: UUID,
        summary: RunSummary,
        staged_rows: Sequence[UploadBatchFile],
    ) -> None:
        """Attach each ingestion outcome back to its staged row.

        Matching is by original filename, which is the only identifier shared
        between a staged row and a ``SourceFileRef``.
        """
        by_name = {row.original_filename: row for row in staged_rows}

        for outcome in summary.outcomes:
            row = by_name.get(outcome.filename)
            if row is None:
                continue
            row.telemetry_file_id = outcome.telemetry_file_id
            row.registered_at = dt.datetime.now(dt.UTC)
            if outcome.already_registered or outcome.status.value == "DUPLICATE":
                row.status = UploadFileStatus.DUPLICATE
                row.duplicate_of_file_id = outcome.telemetry_file_id
                row.failure_reason = outcome.message
            elif outcome.status.value in {"FAILED", "QUARANTINED"}:
                # The telemetry file itself carries the authoritative state; the
                # staged row records that acquisition handed it over.
                row.status = UploadFileStatus.REGISTERED
                row.failure_reason = outcome.message
            else:
                row.status = UploadFileStatus.REGISTERED

            # Stamp provenance on the telemetry file so an uploaded file can be
            # traced back to its delivery.
            if outcome.telemetry_file_id is not None:
                await self._stamp_batch(outcome.telemetry_file_id, batch_id)

    async def _stamp_batch(self, telemetry_file_id: UUID, batch_id: UUID) -> None:
        await self._uploads.session.execute(
            sa.update(TelemetryFile)
            .where(
                TelemetryFile.id == telemetry_file_id,
                TelemetryFile.upload_batch_id.is_(None),
            )
            .values(upload_batch_id=batch_id)
        )


async def _drain(chunks: AsyncIterator[bytes]) -> None:
    """Consume and discard a rejected file's bytes.

    The multipart stream must be read to completion even for a rejected part, or
    the remaining parts of the request cannot be parsed.
    """
    async for _ in chunks:
        continue
