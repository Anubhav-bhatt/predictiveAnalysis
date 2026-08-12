"""Ingestion-run and telemetry-file persistence."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from backend.app.models.enums import FileStatus, IngestionRunStatus, SourceType
from backend.app.models.ingestion_run import IngestionRun
from backend.app.models.telemetry_file import TelemetryFile, TelemetryFileIdentifier
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["IngestionRunRepository", "TelemetryFileRepository"]

#: File states whose telemetry is trustworthy enough to count toward a
#: charger-day. QUARANTINED and FAILED files contribute nothing (section 43).
USABLE_FILE_STATES = (
    FileStatus.READY_FOR_NORMALIZATION,
    FileStatus.COMPLETED,
    FileStatus.PARTIAL,
)


class IngestionRunRepository(Repository):
    async def create(
        self,
        *,
        source_type: SourceType,
        trigger: Any,
        business_date: dt.date | None = None,
        request_id: str | None = None,
    ) -> IngestionRun:
        run = IngestionRun(
            source_type=source_type,
            trigger=trigger,
            business_date=business_date,
            request_id=request_id,
            status=IngestionRunStatus.STARTED,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(self, run_id: UUID) -> IngestionRun | None:
        return await self.session.get(IngestionRun, run_id)

    async def list(self, request: PageRequest) -> Page[IngestionRun]:
        stmt = sa.select(IngestionRun).order_by(IngestionRun.started_at.desc())
        return await paginate(self.session, stmt, request)

    async def list_for_date(self, business_date: dt.date) -> Sequence[IngestionRun]:
        """Runs relevant to a business date, newest first.

        Relevance is not just ``ingestion_run.business_date``: that column is NULL
        for an undated cycle, and a single run can legitimately deliver telemetry
        for two dates (a cross-midnight file, section 8). So a run also counts when
        one of its files contributed telemetry to this date - which is what makes
        the daily stage view reflect the work that actually happened.
        """
        contributed = (
            sa.select(TelemetryFile.ingestion_run_id)
            .join(TelemetryFileDay, TelemetryFileDay.telemetry_file_id == TelemetryFile.id)
            .where(
                TelemetryFileDay.business_date == business_date,
                TelemetryFile.ingestion_run_id.is_not(None),
            )
        )
        rows = await self.session.execute(
            sa.select(IngestionRun)
            .where(
                sa.or_(
                    IngestionRun.business_date == business_date,
                    IngestionRun.id.in_(contributed),
                )
            )
            .order_by(IngestionRun.started_at.desc())
        )
        return list(rows.scalars().all())


class TelemetryFileRepository(Repository):
    async def get(self, file_id: UUID, *, with_relations: bool = False) -> TelemetryFile | None:
        stmt = sa.select(TelemetryFile).where(TelemetryFile.id == file_id)
        if with_relations:
            stmt = stmt.options(
                selectinload(TelemetryFile.identifiers),
                selectinload(TelemetryFile.schema_version),
            )
        return (await self.session.execute(stmt)).scalars().first()

    async def find_by_checksum_and_name(self, sha256: str, filename: str) -> TelemetryFile | None:
        """The idempotency lookup: identical bytes under the same name."""
        stmt = sa.select(TelemetryFile).where(
            TelemetryFile.sha256 == sha256, TelemetryFile.original_filename == filename
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def find_by_checksum(self, sha256: str) -> Sequence[TelemetryFile]:
        stmt = sa.select(TelemetryFile).where(TelemetryFile.sha256 == sha256)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, telemetry_file: TelemetryFile) -> TelemetryFile:
        self.session.add(telemetry_file)
        await self.session.flush()
        return telemetry_file

    async def replace_identifiers(
        self, file_id: UUID, identifiers: Sequence[dict[str, Any]]
    ) -> None:
        """Delete-then-bulk-insert keeps re-profiling deterministic."""
        await self.session.execute(
            sa.delete(TelemetryFileIdentifier).where(
                TelemetryFileIdentifier.telemetry_file_id == file_id
            )
        )
        if identifiers:
            await self.session.execute(sa.insert(TelemetryFileIdentifier), list(identifiers))

    async def list(
        self,
        request: PageRequest,
        *,
        status: FileStatus | None = None,
        charger_id: str | None = None,
        business_date: dt.date | None = None,
        source_type: SourceType | None = None,
    ) -> Page[TelemetryFile]:
        stmt = sa.select(TelemetryFile).order_by(TelemetryFile.received_at.desc())
        if status is not None:
            stmt = stmt.where(TelemetryFile.status == status)
        if source_type is not None:
            stmt = stmt.where(TelemetryFile.source_type == source_type)
        if business_date is not None:
            stmt = stmt.where(TelemetryFile.business_date == business_date)
        if charger_id is not None:
            stmt = stmt.where(
                TelemetryFile.id.in_(
                    sa.select(TelemetryFileIdentifier.telemetry_file_id).where(
                        TelemetryFileIdentifier.identifier_type == "CHARGER",
                        TelemetryFileIdentifier.value == charger_id,
                    )
                )
            )
        return await paginate(self.session, stmt, request)

    async def counts_by_status(self) -> dict[str, int]:
        rows = await self.session.execute(
            sa.select(TelemetryFile.status, sa.func.count()).group_by(TelemetryFile.status)
        )
        return {str(status.value): int(count) for status, count in rows.all()}

    async def files_for_charger_day(
        self, charger_id: str, business_date: dt.date
    ) -> Sequence[TelemetryFile]:
        """Every usable file contributing to one charger-day (section 19).

        Membership comes from ``telemetry_file_day``, not from the file's dominant
        ``business_date``: a file that merely *touches* this date must contribute
        to it even when most of its telemetry belongs to another (section 8).
        """
        stmt = (
            sa.select(TelemetryFile)
            .join(TelemetryFileDay, TelemetryFileDay.telemetry_file_id == TelemetryFile.id)
            .where(
                TelemetryFileDay.charger_id == charger_id,
                TelemetryFileDay.business_date == business_date,
                TelemetryFile.status.in_(USABLE_FILE_STATES),
            )
            .order_by(TelemetryFile.received_at)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def charger_days_present(self, business_date: dt.date) -> Sequence[tuple[str, UUID]]:
        """(charger_id, file_id) pairs observed for a business date.

        One aggregated query - reconciliation must never issue a query per
        charger (section 40).
        """
        stmt = (
            sa.select(TelemetryFileIdentifier.value, TelemetryFile.id)
            .join(TelemetryFile, TelemetryFile.id == TelemetryFileIdentifier.telemetry_file_id)
            .where(
                TelemetryFileIdentifier.identifier_type == "CHARGER",
                TelemetryFile.business_date == business_date,
            )
        )
        return [(str(row[0]), row[1]) for row in (await self.session.execute(stmt)).all()]

    # -- per-date contributions (Phase 1C sections 8, 19) ------------------

    async def replace_file_days(self, file_id: UUID, rows: Sequence[dict[str, Any]]) -> None:
        """Delete-then-insert this file's per-date rows.

        Re-profiling an immutable file must converge on one row per date, never
        accumulate a second set (section 41).
        """
        await self.session.execute(
            sa.delete(TelemetryFileDay).where(TelemetryFileDay.telemetry_file_id == file_id)
        )
        if rows:
            await self.session.execute(
                sa.insert(TelemetryFileDay),
                [{**row, "id": uuid4()} for row in rows],
            )

    async def file_days_for_date(
        self, business_date: dt.date, *, charger_ids: Sequence[str] | None = None
    ) -> Sequence[tuple[TelemetryFileDay, TelemetryFile]]:
        """Every usable file-day for a business date, in one query.

        This is the fleet-scale read that reconciliation is built on: one
        statement returns every charger's contributions for the date, so the
        worker never issues a query per charger (section 40).
        """
        stmt = (
            sa.select(TelemetryFileDay, TelemetryFile)
            .join(TelemetryFile, TelemetryFile.id == TelemetryFileDay.telemetry_file_id)
            .where(
                TelemetryFileDay.business_date == business_date,
                TelemetryFile.status.in_(USABLE_FILE_STATES),
            )
            .order_by(TelemetryFileDay.charger_id, TelemetryFile.received_at)
        )
        if charger_ids:
            stmt = stmt.where(TelemetryFileDay.charger_id.in_(list(charger_ids)))
        rows = await self.session.execute(stmt)
        return [(day, file) for day, file in rows.all()]

    async def file_days_for_charger(
        self, charger_id: str, date_from: dt.date, date_to: dt.date
    ) -> Sequence[TelemetryFileDay]:
        stmt = (
            sa.select(TelemetryFileDay)
            .join(TelemetryFile, TelemetryFile.id == TelemetryFileDay.telemetry_file_id)
            .where(
                TelemetryFileDay.charger_id == charger_id,
                TelemetryFileDay.business_date >= date_from,
                TelemetryFileDay.business_date <= date_to,
                TelemetryFile.status.in_(USABLE_FILE_STATES),
            )
            .order_by(TelemetryFileDay.business_date)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def dates_touched_by_files(self, file_ids: Sequence[UUID]) -> Sequence[dt.date]:
        """Distinct business dates the given files contribute telemetry to.

        Used after an ingestion run to reconcile exactly the dates that actually
        changed, rather than assuming the run's nominal date.
        """
        if not file_ids:
            return []
        rows = await self.session.execute(
            sa.select(TelemetryFileDay.business_date)
            .where(TelemetryFileDay.telemetry_file_id.in_(list(file_ids)))
            .distinct()
            .order_by(TelemetryFileDay.business_date)
        )
        return [row[0] for row in rows.all()]
