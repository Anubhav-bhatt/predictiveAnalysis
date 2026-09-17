"""Quality analysis and persistence.

Runs the rule engine against a single shared profiling context, persists the
findings and field profiles with replace-semantics, and computes the transparent
five-dimension score.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from backend.app.core.config import QualityScoreWeights
from backend.app.core.logging import get_logger
from backend.app.models.field_profile import MAX_EXAMPLE_VALUES, MAX_OBSERVED_VALUES
from backend.app.repositories.quality import QualityRepository
from pipelines.profiling.profiler import FileProfile
from pipelines.quality.base import QualityContext, QualityFinding, RuleRegistry
from pipelines.quality.scoring import QualityScore, compute_quality_score
from pipelines.validation.dictionary import ResolvedField

__all__ = ["QualityOutcome", "QualityService"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class QualityOutcome:
    findings: Sequence[QualityFinding]
    score: QualityScore

    @property
    def has_critical(self) -> bool:
        return any(f.severity.value == "CRITICAL" for f in self.findings)

    @property
    def has_error(self) -> bool:
        return any(f.severity.value in {"ERROR", "CRITICAL"} for f in self.findings)


class QualityService:
    def __init__(
        self,
        repository: QualityRepository,
        rules: RuleRegistry,
        weights: QualityScoreWeights | None = None,
    ) -> None:
        self._repo = repository
        self._rules = rules
        self._weights = weights or QualityScoreWeights()

    async def analyse(
        self,
        *,
        telemetry_file_id: UUID,
        ingestion_run_id: UUID | None,
        context: QualityContext,
        field_definition_ids: dict[int, UUID] | None = None,
    ) -> QualityOutcome:
        """Evaluate all rules, persist results, and score the file."""
        findings = self._rules.evaluate(context)
        score = compute_quality_score(context, findings, self._weights)

        await self._repo.replace_issues(
            telemetry_file_id,
            [self._issue_row(finding, ingestion_run_id) for finding in findings],
        )
        await self._repo.replace_field_profiles(
            telemetry_file_id,
            self._profile_rows(context.profile, context.resolved_fields, field_definition_ids),
        )

        logger.info(
            "quality.analysed",
            findings=len(findings),
            quality_score=float(score.overall_quality),
            schema_quality=score.schema_quality,
            completeness_quality=score.completeness_quality,
            validity_quality=score.validity_quality,
            duplicate_quality=score.duplicate_quality,
            timestamp_quality=score.timestamp_quality,
        )
        return QualityOutcome(findings=findings, score=score)

    # -- row building ------------------------------------------------------

    def _issue_row(self, finding: QualityFinding, ingestion_run_id: UUID | None) -> dict[str, Any]:
        return {
            "ingestion_run_id": ingestion_run_id,
            "rule_code": finding.rule_code,
            "scope": finding.scope,
            "severity": finding.severity,
            "entity": finding.entity,
            "field_name": finding.field_name,
            "field_occurrence": finding.field_occurrence,
            "source_row_number": finding.source_row_number,
            "event_time": finding.event_time,
            "entity_reference": finding.entity_reference,
            "raw_value": finding.truncated_value(),
            "message": finding.message,
            "details": dict(finding.details) or None,
            "occurrence_count": finding.occurrence_count,
            "issue_hash": finding.issue_hash,
            "detected_at": dt.datetime.now(dt.UTC),
        }

    def _profile_rows(
        self,
        profile: FileProfile,
        resolved: Sequence[ResolvedField],
        field_definition_ids: dict[int, UUID] | None,
    ) -> list[dict[str, Any]]:
        canonical_by_position = {r.source_position: r.spec.canonical_name for r in resolved}
        ids = field_definition_ids or {}
        rows: list[dict[str, Any]] = []
        for item in profile.fields:
            rows.append(
                {
                    "field_definition_id": ids.get(item.position),
                    "source_name": item.source_name,
                    "source_occurrence": item.source_occurrence,
                    "source_position": item.position,
                    "canonical_name": canonical_by_position.get(item.position, item.canonical_name),
                    "null_count": item.null_count,
                    "null_percentage": Decimal(f"{item.null_percentage:.3f}"),
                    "unique_count": item.unique_count,
                    "variability_class": item.variability,
                    "min_value": _truncate(item.min_value),
                    "max_value": _truncate(item.max_value),
                    "numeric_valid_count": item.numeric_valid_count,
                    "mean_value": item.mean_value,
                    "median_value": item.median_value,
                    "stddev_value": item.stddev_value,
                    "sentinel_hit_count": item.sentinel_hit_count,
                    "example_values": (
                        {"values": list(item.example_values[:MAX_EXAMPLE_VALUES])}
                        if item.example_values
                        else None
                    ),
                    "observed_values": (
                        {"values": list(item.observed_values[:MAX_OBSERVED_VALUES])}
                        if item.observed_values is not None
                        else None
                    ),
                }
            )
        return rows


def _truncate(value: str | None, limit: int = 256) -> str | None:
    return None if value is None else value[:limit]
