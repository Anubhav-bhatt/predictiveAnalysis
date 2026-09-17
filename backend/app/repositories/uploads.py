"""Upload batch persistence (Phase 1C.5 sections 7, 29-31).

Outcome counts are **derived here in SQL**, never stored on the batch. A stored
"completed" counter can drift from the files it claims to describe; a query cannot.
Only ``file_count`` and ``total_bytes`` live on the batch row, because they are
fixed when the upload request finishes and are not re-derivable after staged bytes
are cleaned up.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from backend.app.models.enums import (
    FileStatus,
    UploadBatchStatus,
    UploadFileStatus,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.upload_batch import UploadBatch, UploadBatchFile
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["UploadRepository"]

#: File states that mean the telemetry is usable downstream.
_READY_STATES = (FileStatus.FRAMES_RECONSTRUCTED, FileStatus.COMPLETED)
#: States that still need operator attention.
_PROBLEM_STATES = (FileStatus.FAILED, FileStatus.QUARANTINED)


class UploadRepository(Repository):
    # -- batches -----------------------------------------------------------

    async def create_batch(self, **values: Any) -> UploadBatch:
        batch = UploadBatch(**values)
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_batch(self, batch_id: UUID, *, with_files: bool = False) -> UploadBatch | None:
        stmt = sa.select(UploadBatch).where(UploadBatch.id == batch_id)
        if with_files:
            stmt = stmt.options(selectinload(UploadBatch.files))
        return (await self.session.execute(stmt)).scalars().first()

    async def list_batches(self, request: PageRequest) -> Page[UploadBatch]:
        stmt = sa.select(UploadBatch).order_by(UploadBatch.created_at.desc())
        return await paginate(self.session, stmt, request)

    async def queued_batches(self) -> Sequence[UploadBatch]:
        """Batches whose bytes are staged and awaiting the worker.

        PROCESSING is included so a batch interrupted mid-run is picked up again -
        processing is idempotent, so re-entering it is safe.
        """
        stmt = (
            sa.select(UploadBatch)
            .where(
                UploadBatch.status.in_([UploadBatchStatus.REGISTERED, UploadBatchStatus.PROCESSING])
            )
            .order_by(UploadBatch.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_files(self, rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            await self.session.execute(sa.insert(UploadBatchFile), list(rows))

    async def batch_files(
        self,
        request: PageRequest,
        batch_id: UUID,
        *,
        status: UploadFileStatus | None = None,
        charger_id: str | None = None,
        business_date: dt.date | None = None,
    ) -> Page[UploadBatchFile]:
        """Paginated batch contents (section 30).

        The telemetry file is eager-loaded because the UI reads the real
        processing state from it - a lazy load would raise ``MissingGreenlet``
        under asyncio rather than quietly N+1.
        """
        stmt = (
            sa.select(UploadBatchFile)
            .where(UploadBatchFile.batch_id == batch_id)
            .options(selectinload(UploadBatchFile.telemetry_file))
            .order_by(UploadBatchFile.original_filename)
        )
        if status is not None:
            stmt = stmt.where(UploadBatchFile.status == status)
        if charger_id is not None or business_date is not None:
            joined = sa.select(TelemetryFile.id)
            if business_date is not None:
                joined = joined.where(TelemetryFile.business_date == business_date)
            if charger_id is not None:
                from backend.app.models.telemetry_file_day import TelemetryFileDay

                joined = joined.where(
                    TelemetryFile.id.in_(
                        sa.select(TelemetryFileDay.telemetry_file_id).where(
                            TelemetryFileDay.charger_id == charger_id
                        )
                    )
                )
            stmt = stmt.where(UploadBatchFile.telemetry_file_id.in_(joined))
        return await paginate(self.session, stmt, request)

    async def staged_files(self, batch_id: UUID) -> Sequence[UploadBatchFile]:
        """Files still awaiting registration, in stable filename order."""
        stmt = (
            sa.select(UploadBatchFile)
            .where(
                UploadBatchFile.batch_id == batch_id,
                UploadBatchFile.status == UploadFileStatus.PENDING,
            )
            .order_by(UploadBatchFile.original_filename)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def file_by_name(self, batch_id: UUID, original_filename: str) -> UploadBatchFile | None:
        stmt = sa.select(UploadBatchFile).where(
            UploadBatchFile.batch_id == batch_id,
            UploadBatchFile.original_filename == original_filename,
        )
        return (await self.session.execute(stmt)).scalars().first()

    # -- derived outcome counts -------------------------------------------

    async def batch_counts(self, batch_id: UUID) -> dict[str, int]:
        """Outcome tallies, computed rather than stored.

        Staged-file status covers the acquisition attempt (rejected, duplicate);
        the linked telemetry file's status covers real processing progress. Both
        are read here so the UI never has to join them itself.

        **Every staged file lands in exactly one bucket**, so the buckets sum to
        ``total_files``. That is why the telemetry-file query is restricted to rows
        whose staged status is REGISTERED: a re-uploaded file is marked DUPLICATE at
        acquisition *and* linked to the telemetry file it matched, which is already
        FRAMES_RECONSTRUCTED. Counting both sides reported a one-file batch as
        "1 ready and 1 already uploaded" - two outcomes for one file.

        The flush is load-bearing: the session runs with autoflush disabled, so a
        file whose status was advanced to FRAMES_RECONSTRUCTED earlier in this same
        transaction is still pending in the identity map. These Core selects would
        not see it, and the batch would report PROCESSING forever.
        """
        await self.session.flush()

        staged = await self.session.execute(
            sa.select(UploadBatchFile.status, sa.func.count())
            .where(UploadBatchFile.batch_id == batch_id)
            .group_by(UploadBatchFile.status)
        )
        staged_counts = {status.value: int(count) for status, count in staged.all()}

        file_rows = await self.session.execute(
            sa.select(TelemetryFile.status, sa.func.count())
            .join(
                UploadBatchFile,
                UploadBatchFile.telemetry_file_id == TelemetryFile.id,
            )
            .where(
                UploadBatchFile.batch_id == batch_id,
                UploadBatchFile.status == UploadFileStatus.REGISTERED,
            )
            .group_by(TelemetryFile.status)
        )
        file_counts = {status.value: int(count) for status, count in file_rows.all()}

        total = sum(staged_counts.values())
        ready = sum(file_counts.get(state.value, 0) for state in _READY_STATES)
        failed = file_counts.get(FileStatus.FAILED.value, 0) + staged_counts.get(
            UploadFileStatus.FAILED.value, 0
        )
        quarantined = file_counts.get(FileStatus.QUARANTINED.value, 0)
        duplicate = staged_counts.get(UploadFileStatus.DUPLICATE.value, 0) + file_counts.get(
            FileStatus.DUPLICATE.value, 0
        )
        rejected = staged_counts.get(UploadFileStatus.REJECTED.value, 0)
        pending = staged_counts.get(UploadFileStatus.PENDING.value, 0)

        # Anything registered but not yet in a terminal file state is still moving
        # through the pipeline.
        registered = staged_counts.get(UploadFileStatus.REGISTERED.value, 0)
        processing = max(registered - (ready + failed + quarantined), 0)

        return {
            "total_files": total,
            "pending": pending,
            "processing": processing,
            "completed": ready,
            "duplicate": duplicate,
            "failed": failed,
            "quarantined": quarantined,
            "rejected": rejected,
        }

    async def resolve_batch_status(self, batch_id: UUID) -> UploadBatchStatus:
        """Terminal status derived from outcomes (section 8).

        One bad file never fails a batch: a batch is FAILED only when nothing at
        all became usable and something went wrong.
        """
        counts = await self.batch_counts(batch_id)
        if counts["pending"] or counts["processing"]:
            return UploadBatchStatus.PROCESSING

        problems = counts["failed"] + counts["quarantined"] + counts["rejected"]
        if counts["completed"] == 0 and problems > 0:
            return UploadBatchStatus.FAILED
        if problems or counts["duplicate"]:
            return UploadBatchStatus.COMPLETED_WITH_WARNINGS
        return UploadBatchStatus.COMPLETED

    async def list_counts_for_batches(
        self, batch_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, int]]:
        """Counts for many batches in two queries, for the history page.

        Avoids a per-row lookup while rendering a paginated batch list
        (section 46).
        """
        if not batch_ids:
            return {}
        # Same reason as batch_counts: pending ORM status updates must be visible.
        await self.session.flush()
        ids = list(batch_ids)
        result: dict[UUID, dict[str, int]] = {
            batch_id: {
                "total_files": 0,
                "completed": 0,
                "duplicate": 0,
                "failed": 0,
                "quarantined": 0,
                "rejected": 0,
                "pending": 0,
                "processing": 0,
            }
            for batch_id in ids
        }

        staged = await self.session.execute(
            sa.select(UploadBatchFile.batch_id, UploadBatchFile.status, sa.func.count())
            .where(UploadBatchFile.batch_id.in_(ids))
            .group_by(UploadBatchFile.batch_id, UploadBatchFile.status)
        )
        for batch_id, status, count in staged.all():
            bucket = result[batch_id]
            bucket["total_files"] += int(count)
            if status is UploadFileStatus.DUPLICATE:
                bucket["duplicate"] += int(count)
            elif status is UploadFileStatus.REJECTED:
                bucket["rejected"] += int(count)
            elif status is UploadFileStatus.FAILED:
                bucket["failed"] += int(count)
            elif status is UploadFileStatus.PENDING:
                bucket["pending"] += int(count)

        # Restricted to REGISTERED for the same reason as batch_counts: a file
        # already recognised at acquisition must not be tallied a second time by the
        # telemetry file it matched.
        files = await self.session.execute(
            sa.select(UploadBatchFile.batch_id, TelemetryFile.status, sa.func.count())
            .join(TelemetryFile, TelemetryFile.id == UploadBatchFile.telemetry_file_id)
            .where(
                UploadBatchFile.batch_id.in_(ids),
                UploadBatchFile.status == UploadFileStatus.REGISTERED,
            )
            .group_by(UploadBatchFile.batch_id, TelemetryFile.status)
        )
        for batch_id, status, count in files.all():
            bucket = result[batch_id]
            if status in _READY_STATES:
                bucket["completed"] += int(count)
            elif status is FileStatus.QUARANTINED:
                bucket["quarantined"] += int(count)
            elif status is FileStatus.FAILED:
                bucket["failed"] += int(count)
            elif status is FileStatus.DUPLICATE:
                bucket["duplicate"] += int(count)
            else:
                bucket["processing"] += int(count)
        return result
