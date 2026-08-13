"""Bulk manual upload endpoints (Phase 1C.5 sections 10, 11, 29-31).

The upload endpoint **stages and returns**. It never waits for profiling, schema
validation, quality, coverage or frame reconstruction: a 100-file backfill would
hold the connection open for minutes and time out, and heavy processing belongs to
the worker (sections 11, 13).

So a successful response means *"your bytes are safe and queued"*, not *"your
telemetry is processed"*. The batch's own status is what tells an operator where
processing has got to, which is why the frontend treats upload progress and
processing progress as two different things.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.app.api.deps import PageDep, SettingsDep, UploadRepoDep, UploadServiceDep
from backend.app.core.logging import get_logger
from backend.app.models.enums import UploadFileStatus
from backend.app.models.upload_batch import UploadBatchFile
from backend.app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from backend.app.schemas.uploads import (
    BatchFileRow,
    StagedFileResult,
    UploadBatchDetail,
    UploadBatchRow,
    UploadCounts,
    UploadCreated,
    UploadLimits,
)
from backend.app.services.upload_service import UploadRejected

router = APIRouter(prefix="/ingestion/uploads", tags=["uploads"])

logger = get_logger(__name__)

_UPLOAD_CHUNK = 1024 * 1024


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="batch_id is not a valid UUID"
        ) from exc


@router.post(
    "",
    response_model=Envelope[UploadCreated],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload telemetry files as one batch (staging only)",
)
async def create_upload(
    uploads: UploadServiceDep,
    settings: SettingsDep,
    files: Annotated[list[UploadFile], File(description="Telemetry CSV files.")],
) -> Envelope[UploadCreated]:
    """Stage uploaded files and return a batch id.

    202 rather than 201: the batch has been accepted for processing, which has not
    happened yet.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No files were supplied"
        )

    async def stream(upload: UploadFile) -> AsyncIterator[bytes]:
        """Chunked read, so a large file never lands in memory whole."""
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            yield chunk

    payload = [((upload.filename or "unnamed"), stream(upload)) for upload in files]

    try:
        batch_id, outcomes = await uploads.stage_batch(payload)
    except UploadRejected as exc:
        # A rejected *request* is a client error; a rejected individual file is
        # reported per file instead, so the rest of the batch still proceeds.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    staged = [
        StagedFileResult(
            original_filename=item.original_filename,
            size_bytes=item.size_bytes,
            status=item.status,
            reason=item.rejection_reason,
        )
        for item in outcomes
    ]
    created = UploadCreated(
        upload_batch_id=batch_id,
        status=(await uploads.batch_status(batch_id)),
        file_count=len(staged),
        total_bytes=sum(item.size_bytes for item in staged),
        staged=staged,
    )
    return ok(
        created,
        note=(
            "Files are staged and queued. Processing runs in the ingestion worker; "
            "poll the batch for progress."
        ),
    )


@router.get(
    "/limits",
    response_model=Envelope[UploadLimits],
    summary="Upload limits enforced by this deployment",
)
async def get_limits(settings: SettingsDep) -> Envelope[UploadLimits]:
    """Declared before ``/{batch_id}`` on purpose - otherwise that route would
    capture "limits" as a batch id."""
    return ok(
        UploadLimits(
            max_files_per_batch=settings.upload.max_files_per_batch,
            max_file_size_bytes=settings.upload.max_file_size_bytes,
            max_batch_size_bytes=settings.upload.max_batch_size_bytes,
            allowed_extensions=list(settings.upload.allowed_extensions),
        )
    )


@router.get(
    "",
    response_model=PaginatedEnvelope[UploadBatchRow],
    summary="Upload history, newest first",
)
async def list_uploads(
    repo: UploadRepoDep, page: PageDep
) -> PaginatedEnvelope[UploadBatchRow]:
    result = await repo.list_batches(page)
    ids = [batch.id for batch in result.items]
    counts = await repo.list_counts_for_batches(ids)

    rows = [
        UploadBatchRow.model_validate(batch).model_copy(
            update={"counts": UploadCounts(**counts[batch.id])}
        )
        for batch in result.items
    ]
    return paginated(rows, result.meta())


@router.get(
    "/{batch_id}",
    response_model=Envelope[UploadBatchDetail],
    summary="One upload batch with derived outcome counts",
)
async def get_upload(batch_id: str, repo: UploadRepoDep) -> Envelope[UploadBatchDetail]:
    parsed = _parse_uuid(batch_id)
    batch = await repo.get_batch(parsed)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload batch not found"
        )
    counts = UploadCounts(**await repo.batch_counts(parsed))
    detail = UploadBatchDetail(
        batch=UploadBatchRow.model_validate(batch).model_copy(update={"counts": counts}),
        counts=counts,
    )
    return ok(detail)


@router.get(
    "/{batch_id}/files",
    response_model=PaginatedEnvelope[BatchFileRow],
    summary="Files in one upload batch",
)
async def get_upload_files(
    batch_id: str,
    repo: UploadRepoDep,
    page: PageDep,
    file_status: Annotated[UploadFileStatus | None, Query(alias="status")] = None,
    charger: Annotated[str | None, Query()] = None,
    business_date: Annotated[dt.date | None, Query(alias="date")] = None,
) -> PaginatedEnvelope[BatchFileRow]:
    parsed = _parse_uuid(batch_id)
    if await repo.get_batch(parsed) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload batch not found"
        )

    result = await repo.batch_files(
        page, parsed, status=file_status, charger_id=charger, business_date=business_date
    )
    return paginated([_file_row(item) for item in result.items], result.meta())


def _file_row(item: UploadBatchFile) -> BatchFileRow:
    """Map a staged file, enriching from its telemetry file when registered.

    ``storage_reference`` and ``staged_reference`` are deliberately never copied
    across - internal paths do not leave the backend.
    """
    row = BatchFileRow.model_validate(item)
    telemetry_file = item.telemetry_file
    if telemetry_file is None:
        return row
    return row.model_copy(
        update={
            "telemetry_status": telemetry_file.status,
            "business_date": telemetry_file.business_date,
            "row_count": telemetry_file.row_count,
            "unique_event_timestamp_count": telemetry_file.unique_event_timestamp_count,
            "quality_score": (
                float(telemetry_file.quality_score)
                if telemetry_file.quality_score is not None
                else None
            ),
        }
    )


__all__ = ["router"]
