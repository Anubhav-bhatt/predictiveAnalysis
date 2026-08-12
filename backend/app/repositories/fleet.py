"""Fleet registry, charger-day coverage and telemetry-gap persistence.

Two properties drive the design here:

*Idempotency* (section 41): coverage identity is ``(charger_id, business_date)``
and gaps are fully replaced per coverage row, so ``run-daily`` and ``reconcile``
converge on the same state no matter how often they run.

*Bulk access* (section 40): reconciling a fleet of thousands must not issue a
query per charger. Coverage upserts read existing keys in one statement and then
perform at most one bulk update and one bulk insert.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from backend.app.models.charger import Charger
from backend.app.models.charger_day_coverage import ChargerDayCoverage
from backend.app.models.enums import (
    ArrivalStatus,
    ChargerLifecycleStatus,
    CompletenessStatus,
    FileStatus,
    GapSeverity,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.models.telemetry_gap import TelemetryGap
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["FleetRepository"]


class FleetRepository(Repository):
    # -- charger registry --------------------------------------------------

    async def get_charger(self, charger_id: str) -> Charger | None:
        stmt = sa.select(Charger).where(Charger.charger_id == charger_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def upsert_charger(self, **values: Any) -> Charger:
        charger_id = values["charger_id"]
        existing = await self.get_charger(charger_id)
        if existing is not None:
            for key, value in values.items():
                setattr(existing, key, value)
            await self.session.flush()
            return existing
        charger = Charger(**values)
        self.session.add(charger)
        await self.session.flush()
        return charger

    async def expected_chargers(self, business_date: dt.date) -> Sequence[Charger]:
        """Chargers that should have delivered telemetry on a date.

        The date-window and lifecycle filters run in SQL so the fleet is never
        fully materialised just to be filtered in Python.
        """
        stmt = sa.select(Charger).where(
            Charger.telemetry_expected.is_(True),
            Charger.lifecycle_status.notin_(
                [
                    ChargerLifecycleStatus.DECOMMISSIONED,
                    ChargerLifecycleStatus.TEMPORARILY_INACTIVE,
                    ChargerLifecycleStatus.TEST,
                ]
            ),
            sa.or_(
                Charger.telemetry_start_date.is_(None),
                Charger.telemetry_start_date <= business_date,
            ),
            sa.or_(
                Charger.telemetry_end_date.is_(None),
                Charger.telemetry_end_date >= business_date,
            ),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_chargers(self, request: PageRequest) -> Page[Charger]:
        stmt = sa.select(Charger).order_by(Charger.charger_id)
        return await paginate(self.session, stmt, request)

    # -- charger-day coverage ---------------------------------------------

    async def upsert_coverage_bulk(
        self, business_date: dt.date, rows: Sequence[dict[str, Any]]
    ) -> dict[str, UUID]:
        """Insert or update many charger-days, returning charger_id -> row id.

        Portable across PostgreSQL and SQLite: existing identities are fetched
        in one query, then the batch is split into a bulk update and a bulk
        insert. Three statements total, regardless of fleet size.
        """
        if not rows:
            return {}

        charger_ids = [str(row["charger_id"]) for row in rows]
        existing = await self.session.execute(
            sa.select(ChargerDayCoverage.charger_id, ChargerDayCoverage.id).where(
                ChargerDayCoverage.business_date == business_date,
                ChargerDayCoverage.charger_id.in_(charger_ids),
            )
        )
        existing_ids: dict[str, UUID] = {str(cid): rid for cid, rid in existing.all()}

        to_insert: list[dict[str, Any]] = []
        to_update: list[dict[str, Any]] = []
        result: dict[str, UUID] = {}

        for row in rows:
            charger_id = str(row["charger_id"])
            payload = {**row, "business_date": business_date}
            if charger_id in existing_ids:
                row_id = existing_ids[charger_id]
                payload["id"] = row_id
                to_update.append(payload)
            else:
                row_id = uuid4()
                payload["id"] = row_id
                to_insert.append(payload)
            result[charger_id] = row_id

        if to_insert:
            await self.session.execute(sa.insert(ChargerDayCoverage), to_insert)
        if to_update:
            await self.session.execute(sa.update(ChargerDayCoverage), to_update)
        return result

    async def get_coverage(
        self, charger_id: str, business_date: dt.date
    ) -> ChargerDayCoverage | None:
        stmt = sa.select(ChargerDayCoverage).where(
            ChargerDayCoverage.charger_id == charger_id,
            ChargerDayCoverage.business_date == business_date,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_coverage(
        self,
        request: PageRequest,
        *,
        business_date: dt.date | None = None,
        arrival_status: ArrivalStatus | None = None,
        completeness_status: CompletenessStatus | None = None,
        processing_status: FileStatus | None = None,
        charger_id: str | None = None,
        site_code: str | None = None,
    ) -> Page[ChargerDayCoverage]:
        """Worst coverage first (section 34).

        The ``charger`` relationship is eager-loaded: the API reads site and OCPP
        id off it, and a lazy load under asyncio would raise ``MissingGreenlet``
        rather than quietly issuing one query per row.
        """
        stmt = (
            sa.select(ChargerDayCoverage)
            .options(selectinload(ChargerDayCoverage.charger))
            .order_by(
                ChargerDayCoverage.coverage_percentage.asc().nulls_first(),
                ChargerDayCoverage.charger_id,
            )
        )
        conditions = [
            (ChargerDayCoverage.business_date == business_date, business_date),
            (ChargerDayCoverage.arrival_status == arrival_status, arrival_status),
            (ChargerDayCoverage.completeness_status == completeness_status, completeness_status),
            (ChargerDayCoverage.charger_id == charger_id, charger_id),
        ]
        for clause, value in conditions:
            if value is not None:
                stmt = stmt.where(clause)
        if site_code is not None:
            stmt = stmt.where(
                ChargerDayCoverage.charger_pk.in_(
                    sa.select(Charger.id).where(Charger.site_code == site_code)
                )
            )
        if processing_status is not None:
            # File-level state, applied to the charger-day: keep only days whose
            # telemetry came from a file in that state. Daily status derives from
            # file state rather than duplicating its lifecycle (section 6).
            stmt = stmt.where(
                ChargerDayCoverage.charger_id.in_(
                    sa.select(TelemetryFileDay.charger_id)
                    .join(TelemetryFile, TelemetryFile.id == TelemetryFileDay.telemetry_file_id)
                    .where(
                        TelemetryFile.status == processing_status,
                        TelemetryFileDay.business_date == ChargerDayCoverage.business_date,
                    )
                )
            )
        return await paginate(self.session, stmt, request)

    async def coverage_history(
        self, charger_id: str, date_from: dt.date, date_to: dt.date
    ) -> Sequence[ChargerDayCoverage]:
        stmt = (
            sa.select(ChargerDayCoverage)
            .where(
                ChargerDayCoverage.charger_id == charger_id,
                ChargerDayCoverage.business_date >= date_from,
                ChargerDayCoverage.business_date <= date_to,
            )
            .order_by(ChargerDayCoverage.business_date)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def last_successful_days(
        self, business_date: dt.date, charger_ids: Sequence[str] | None = None
    ) -> dict[str, tuple[dt.date, float | None]]:
        """Most recent earlier date on which each charger delivered telemetry.

        Powers the "Last Successful Data" column of the missing-chargers table
        (section 33). One grouped query for the whole fleet, then a single lookup
        of the coverage on those dates - never a query per charger (section 40).
        """
        latest = (
            sa.select(
                ChargerDayCoverage.charger_id.label("charger_id"),
                sa.func.max(ChargerDayCoverage.business_date).label("last_date"),
            )
            .where(
                ChargerDayCoverage.business_date < business_date,
                ChargerDayCoverage.unique_timestamp_count > 0,
            )
            .group_by(ChargerDayCoverage.charger_id)
        )
        if charger_ids:
            latest = latest.where(ChargerDayCoverage.charger_id.in_(list(charger_ids)))
        sub = latest.subquery()

        stmt = sa.select(
            sub.c.charger_id, sub.c.last_date, ChargerDayCoverage.coverage_percentage
        ).join(
            ChargerDayCoverage,
            sa.and_(
                ChargerDayCoverage.charger_id == sub.c.charger_id,
                ChargerDayCoverage.business_date == sub.c.last_date,
            ),
        )
        rows = (await self.session.execute(stmt)).all()
        return {
            str(charger_id): (last_date, float(pct) if pct is not None else None)
            for charger_id, last_date, pct in rows
        }

    async def coverage_percentage_on(
        self, business_date: dt.date, charger_ids: Sequence[str] | None = None
    ) -> dict[str, float | None]:
        """charger_id -> coverage% for one date; used for previous-day context."""
        stmt = sa.select(
            ChargerDayCoverage.charger_id, ChargerDayCoverage.coverage_percentage
        ).where(ChargerDayCoverage.business_date == business_date)
        if charger_ids:
            stmt = stmt.where(ChargerDayCoverage.charger_id.in_(list(charger_ids)))
        rows = (await self.session.execute(stmt)).all()
        return {
            str(charger_id): (float(pct) if pct is not None else None)
            for charger_id, pct in rows
        }

    async def coverage_distribution(self, business_date: dt.date) -> list[float]:
        """Ordered coverage percentages for percentile maths (section 39).

        Percentiles are computed in Python from this ordered list rather than with
        a dialect-specific SQL percentile function, so PostgreSQL and SQLite agree.
        """
        rows = await self.session.execute(
            sa.select(ChargerDayCoverage.coverage_percentage)
            .where(
                ChargerDayCoverage.business_date == business_date,
                ChargerDayCoverage.coverage_percentage.is_not(None),
            )
            .order_by(ChargerDayCoverage.coverage_percentage)
        )
        return [float(row[0]) for row in rows.all()]

    async def largest_gap_distribution(self, business_date: dt.date) -> list[int]:
        rows = await self.session.execute(
            sa.select(ChargerDayCoverage.largest_gap_seconds)
            .where(
                ChargerDayCoverage.business_date == business_date,
                ChargerDayCoverage.largest_gap_seconds.is_not(None),
            )
            .order_by(ChargerDayCoverage.largest_gap_seconds)
        )
        return [int(row[0]) for row in rows.all()]

    async def daily_summary(self, business_date: dt.date) -> dict[str, Any]:
        """Fleet-level aggregates for one date, computed in SQL (section 39)."""
        arrival = await self.session.execute(
            sa.select(ChargerDayCoverage.arrival_status, sa.func.count())
            .where(ChargerDayCoverage.business_date == business_date)
            .group_by(ChargerDayCoverage.arrival_status)
        )
        completeness = await self.session.execute(
            sa.select(ChargerDayCoverage.completeness_status, sa.func.count())
            .where(ChargerDayCoverage.business_date == business_date)
            .group_by(ChargerDayCoverage.completeness_status)
        )
        aggregates = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("total"),
                    sa.func.avg(ChargerDayCoverage.coverage_percentage).label("avg_coverage"),
                    sa.func.sum(ChargerDayCoverage.gap_count).label("gap_count"),
                    sa.func.max(ChargerDayCoverage.largest_gap_seconds).label("max_gap"),
                    sa.func.sum(ChargerDayCoverage.file_count).label("file_count"),
                ).where(ChargerDayCoverage.business_date == business_date)
            )
        ).one()

        return {
            "arrival": {str(k.value): int(v) for k, v in arrival.all()},
            "completeness": {str(k.value): int(v) for k, v in completeness.all()},
            "total_charger_days": int(aggregates.total or 0),
            "average_coverage_percentage": (
                round(float(aggregates.avg_coverage), 3)
                if aggregates.avg_coverage is not None
                else None
            ),
            "total_gap_count": int(aggregates.gap_count or 0),
            "largest_gap_seconds": int(aggregates.max_gap or 0),
            "total_files": int(aggregates.file_count or 0),
        }

    # -- gaps --------------------------------------------------------------

    async def replace_gaps(self, coverage_id: UUID, rows: Sequence[dict[str, Any]]) -> None:
        """Full recomputation per charger-day.

        Deleting first is what guarantees no stale gap survives after a late
        file fills a hole (section 44).
        """
        await self.session.execute(
            sa.delete(TelemetryGap).where(TelemetryGap.coverage_id == coverage_id)
        )
        if rows:
            await self.session.execute(
                sa.insert(TelemetryGap),
                [{**row, "id": uuid4(), "coverage_id": coverage_id} for row in rows],
            )

    async def replace_gaps_bulk(
        self, payloads: Sequence[tuple[UUID, Sequence[dict[str, Any]]]]
    ) -> None:
        """Batched gap recomputation for a whole reconciliation pass.

        Two statements for the entire fleet - one delete over every affected
        coverage row, one insert of the recomputed set - so gap handling does not
        become a per-charger round trip (section 40). Deleting every affected
        coverage's gaps up front is also what removes gaps that no longer exist
        because a late file filled them (section 44).
        """
        if not payloads:
            return
        coverage_ids = [coverage_id for coverage_id, _ in payloads]
        await self.session.execute(
            sa.delete(TelemetryGap).where(TelemetryGap.coverage_id.in_(coverage_ids))
        )
        rows = [
            {**row, "id": uuid4(), "coverage_id": coverage_id}
            for coverage_id, gap_rows in payloads
            for row in gap_rows
        ]
        if rows:
            await self.session.execute(sa.insert(TelemetryGap), rows)

    async def gaps_for_coverage(self, coverage_id: UUID) -> Sequence[TelemetryGap]:
        stmt = (
            sa.select(TelemetryGap)
            .where(TelemetryGap.coverage_id == coverage_id)
            .order_by(TelemetryGap.start_event_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_gaps(
        self,
        request: PageRequest,
        *,
        charger_id: str | None = None,
        business_date: dt.date | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        severity: GapSeverity | None = None,
    ) -> Page[TelemetryGap]:
        stmt = sa.select(TelemetryGap).order_by(
            TelemetryGap.business_date.desc(), TelemetryGap.duration_seconds.desc()
        )
        if charger_id is not None:
            stmt = stmt.where(TelemetryGap.charger_id == charger_id)
        if business_date is not None:
            stmt = stmt.where(TelemetryGap.business_date == business_date)
        if date_from is not None:
            stmt = stmt.where(TelemetryGap.business_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(TelemetryGap.business_date <= date_to)
        if severity is not None:
            stmt = stmt.where(TelemetryGap.severity == severity)
        return await paginate(self.session, stmt, request)
