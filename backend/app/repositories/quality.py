"""Data-quality issue and field-profile persistence.

Both use a replace-then-insert strategy keyed on the file. That is what makes
re-analysis idempotent (section 39): analysing the same immutable file twice
leaves exactly one row per finding, with no stale rows surviving from a previous
run whose outcome has since changed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from backend.app.models.data_quality_issue import DataQualityIssue
from backend.app.models.enums import (
    FieldEntity,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)
from backend.app.models.field_profile import FieldProfile
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["QualityRepository"]


class QualityRepository(Repository):
    async def replace_issues(self, telemetry_file_id: UUID, rows: Sequence[dict[str, Any]]) -> None:
        await self.session.execute(
            sa.delete(DataQualityIssue).where(
                DataQualityIssue.telemetry_file_id == telemetry_file_id
            )
        )
        if rows:
            await self.session.execute(
                sa.insert(DataQualityIssue),
                [{**row, "id": uuid4(), "telemetry_file_id": telemetry_file_id} for row in rows],
            )

    async def replace_scoped_issues(
        self,
        telemetry_file_id: UUID,
        scope: QualityRuleScope,
        rows: Sequence[dict[str, Any]],
    ) -> None:
        """Replace only one scope's findings for a file.

        Phase 1D writes FRAME-scope findings for a file that already carries
        FILE/FIELD-scope findings from Phase 1A/1B. Deleting by file alone would
        wipe those, so the delete is narrowed to the scope being rewritten - which
        is also what keeps re-running reconstruction idempotent.
        """
        await self.session.execute(
            sa.delete(DataQualityIssue).where(
                DataQualityIssue.telemetry_file_id == telemetry_file_id,
                DataQualityIssue.scope == scope,
            )
        )
        if rows:
            await self.session.execute(
                sa.insert(DataQualityIssue),
                [{**row, "id": uuid4(), "telemetry_file_id": telemetry_file_id} for row in rows],
            )

    async def replace_charger_day_issues(
        self, coverage_id: UUID, rows: Sequence[dict[str, Any]]
    ) -> None:
        """Replace the CHARGER_DAY-scope findings for one charger-day.

        Anchored to the coverage row rather than a file, because the most
        important daily finding - ``MISSING_CHARGER_DATA`` - has no file at all.
        Delete-then-insert is what lets a late file turn yesterday's MISSING
        finding into today's LATE finding without leaving both behind
        (sections 24, 41).
        """
        await self.session.execute(
            sa.delete(DataQualityIssue).where(
                DataQualityIssue.charger_day_coverage_id == coverage_id
            )
        )
        if rows:
            await self.session.execute(
                sa.insert(DataQualityIssue),
                [{**row, "id": uuid4(), "charger_day_coverage_id": coverage_id} for row in rows],
            )

    async def replace_charger_day_issues_bulk(
        self, payloads: Sequence[tuple[UUID, Sequence[dict[str, Any]]]]
    ) -> None:
        """Batched form of :meth:`replace_charger_day_issues`.

        One delete and one insert for the whole batch, so reconciling thousands of
        charger-days stays at constant statement count (section 40).
        """
        if not payloads:
            return
        coverage_ids = [coverage_id for coverage_id, _ in payloads]
        await self.session.execute(
            sa.delete(DataQualityIssue).where(
                DataQualityIssue.charger_day_coverage_id.in_(coverage_ids)
            )
        )
        rows = [
            {**row, "id": uuid4(), "charger_day_coverage_id": coverage_id}
            for coverage_id, issue_rows in payloads
            for row in issue_rows
        ]
        if rows:
            await self.session.execute(sa.insert(DataQualityIssue), rows)

    async def charger_day_issues(self, coverage_id: UUID) -> Sequence[DataQualityIssue]:
        """CHARGER_DAY-scope findings for one charger-day, worst first."""
        stmt = (
            sa.select(DataQualityIssue)
            .where(DataQualityIssue.charger_day_coverage_id == coverage_id)
            .order_by(DataQualityIssue.severity.desc(), DataQualityIssue.rule_code)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def charger_day_rule_counts(self, business_date: dt.date) -> dict[str, int]:
        """Daily findings by rule code, for the operations summary."""
        rows = await self.session.execute(
            sa.select(DataQualityIssue.rule_code, sa.func.count())
            .where(DataQualityIssue.business_date == business_date)
            .group_by(DataQualityIssue.rule_code)
        )
        return {str(code.value): int(count) for code, count in rows.all()}

    async def replace_field_profiles(
        self, telemetry_file_id: UUID, rows: Sequence[dict[str, Any]]
    ) -> None:
        await self.session.execute(
            sa.delete(FieldProfile).where(FieldProfile.telemetry_file_id == telemetry_file_id)
        )
        if rows:
            await self.session.execute(
                sa.insert(FieldProfile),
                [{**row, "id": uuid4(), "telemetry_file_id": telemetry_file_id} for row in rows],
            )

    async def list_issues(
        self,
        request: PageRequest,
        *,
        telemetry_file_id: UUID | None = None,
        severity: QualitySeverity | None = None,
        rule_code: QualityIssueType | None = None,
        entity: FieldEntity | None = None,
        field_name: str | None = None,
        detected_from: dt.datetime | None = None,
        detected_to: dt.datetime | None = None,
    ) -> Page[DataQualityIssue]:
        stmt = sa.select(DataQualityIssue).order_by(
            DataQualityIssue.severity.desc(), DataQualityIssue.detected_at.desc()
        )
        conditions = [
            (DataQualityIssue.telemetry_file_id == telemetry_file_id, telemetry_file_id),
            (DataQualityIssue.severity == severity, severity),
            (DataQualityIssue.rule_code == rule_code, rule_code),
            (DataQualityIssue.entity == entity, entity),
            (DataQualityIssue.field_name == field_name, field_name),
            (DataQualityIssue.detected_at >= detected_from, detected_from),
            (DataQualityIssue.detected_at <= detected_to, detected_to),
        ]
        for clause, value in conditions:
            if value is not None:
                stmt = stmt.where(clause)
        return await paginate(self.session, stmt, request)

    async def severity_counts(self, telemetry_file_id: UUID | None = None) -> dict[str, int]:
        stmt = sa.select(DataQualityIssue.severity, sa.func.count()).group_by(
            DataQualityIssue.severity
        )
        if telemetry_file_id is not None:
            stmt = stmt.where(DataQualityIssue.telemetry_file_id == telemetry_file_id)
        rows = await self.session.execute(stmt)
        counts = {severity.value: 0 for severity in QualitySeverity}
        counts.update({str(sev.value): int(count) for sev, count in rows.all()})
        return counts

    async def rule_counts(self, telemetry_file_id: UUID | None = None) -> dict[str, int]:
        stmt = sa.select(DataQualityIssue.rule_code, sa.func.count()).group_by(
            DataQualityIssue.rule_code
        )
        if telemetry_file_id is not None:
            stmt = stmt.where(DataQualityIssue.telemetry_file_id == telemetry_file_id)
        rows = await self.session.execute(stmt)
        return {str(code.value): int(count) for code, count in rows.all()}

    async def field_profiles(self, telemetry_file_id: UUID) -> Sequence[FieldProfile]:
        stmt = (
            sa.select(FieldProfile)
            .where(FieldProfile.telemetry_file_id == telemetry_file_id)
            .order_by(FieldProfile.source_position)
        )
        return list((await self.session.execute(stmt)).scalars().all())
