"""Research results repository (Phase 9).

Handles persistence and queries for pattern candidates and
analytical dataset run metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.enums import (
    AnalyticalGrain,
    PatternCategory,
    PatternEvidenceLevel,
)
from backend.app.models.research_results import (
    AnalyticalDatasetRun,
    PatternCandidateRecord,
)

__all__ = ["ResearchRepository"]


class ResearchRepository:
    """Async database repository for Phase 9 research results."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ patterns

    async def save_pattern_candidates(
        self,
        candidates: list[PatternCandidateRecord],
    ) -> int:
        """Bulk insert pattern candidates. Returns count of records saved."""
        if not candidates:
            return 0
        self.session.add_all(candidates)
        await self.session.flush()
        return len(candidates)

    async def clear_patterns_for_charger(
        self,
        charger_id: str,
        *,
        scan_version: str = "v1",
    ) -> int:
        """Delete existing patterns for a charger before re-scanning."""
        stmt = sa.delete(PatternCandidateRecord).where(
            PatternCandidateRecord.charger_id == charger_id,
            PatternCandidateRecord.scan_version == scan_version,
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def get_patterns(
        self,
        charger_id: str,
        *,
        pattern_category: PatternCategory | None = None,
        evidence_level: PatternEvidenceLevel | None = None,
        min_confidence: float | None = None,
        limit: int = 200,
    ) -> list[PatternCandidateRecord]:
        """Query pattern candidates for a charger with optional filters."""
        stmt = sa.select(PatternCandidateRecord).where(
            PatternCandidateRecord.charger_id == charger_id
        )
        if pattern_category:
            stmt = stmt.where(PatternCandidateRecord.pattern_category == pattern_category)
        if evidence_level:
            stmt = stmt.where(PatternCandidateRecord.evidence_level == evidence_level)
        if min_confidence is not None:
            stmt = stmt.where(PatternCandidateRecord.confidence_score >= min_confidence)
        stmt = stmt.order_by(
            PatternCandidateRecord.confidence_score.desc(),
            PatternCandidateRecord.created_at.desc(),
        ).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_fleet_pattern_count(self) -> int:
        """Count total pattern candidates across the entire fleet."""
        stmt = sa.select(sa.func.count(PatternCandidateRecord.id))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def get_pattern_breakdown(self) -> list[dict[str, Any]]:
        """Pattern candidate counts grouped by category and evidence level."""
        stmt = (
            sa.select(
                PatternCandidateRecord.pattern_category,
                PatternCandidateRecord.evidence_level,
                sa.func.count(PatternCandidateRecord.id).label("count"),
            )
            .group_by(
                PatternCandidateRecord.pattern_category,
                PatternCandidateRecord.evidence_level,
            )
            .order_by(
                PatternCandidateRecord.pattern_category,
                PatternCandidateRecord.evidence_level,
            )
        )
        result = await self.session.execute(stmt)
        return [
            {
                "pattern_category": str(row._mapping["pattern_category"]),
                "evidence_level": str(row._mapping["evidence_level"]),
                "count": int(row._mapping["count"]),
            }
            for row in result.all()
        ]

    # ------------------------------------------------------------------ dataset runs

    async def save_dataset_run(
        self,
        run: AnalyticalDatasetRun,
    ) -> None:
        """Persist a dataset run record."""
        self.session.add(run)
        await self.session.flush()

    async def get_dataset_runs(
        self,
        *,
        charger_id: str | None = None,
        grain: AnalyticalGrain | None = None,
        limit: int = 50,
    ) -> Sequence[AnalyticalDatasetRun]:
        """Query dataset run history."""
        stmt = (
            sa.select(AnalyticalDatasetRun)
            .order_by(AnalyticalDatasetRun.created_at.desc())
            .limit(limit)
        )
        if charger_id is not None:
            stmt = stmt.where(AnalyticalDatasetRun.charger_id == charger_id)
        if grain is not None:
            stmt = stmt.where(AnalyticalDatasetRun.grain == grain)
        result = await self.session.execute(stmt)
        return result.scalars().all()
