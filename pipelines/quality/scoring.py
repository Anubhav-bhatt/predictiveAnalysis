"""Transparent quality scoring (Phase 1B section 28).

The score is deliberately *not* one opaque formula.  Five dimensions are
computed independently from measured quantities, each is retained, and the
headline number is their configured weighted mean.  Every dimension carries the
inputs that produced it, so a low score can always be explained rather than
merely observed.

Dimensions
----------
``schema_quality``
    Structural agreement with the registered contract: required fields present,
    duplicate headers, and field drift relative to the known schema.

``completeness_quality``
    Populated cells as a share of cells that *could* have been populated.
    Fields that are empty for the whole file are excluded from the denominator
    on purpose - an alarm that did not fire, or optional hardware that is not
    fitted, is not missing data.  Those are reported separately as
    ALL_NULL_FIELD findings.

``validity_quality``
    Share of non-null values that survived the value rules: sentinels, verified
    range breaches, type violations and unknown enum values.

``duplicate_quality``
    Penalised by byte-identical duplicate rows and, more heavily in effect, by
    logical keys holding genuinely *differing* observations.

``timestamp_quality``
    Event-time parse success, penalised by the largest cadence gap relative to
    the file's own median interval.

All weights come from configuration; nothing here hard-codes a result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from backend.app.core.config import QualityScoreWeights
from backend.app.models.enums import (
    QualityIssueType,
    QualitySeverity,
    VariabilityClass,
)
from pipelines.quality.base import QualityContext, QualityFinding

__all__ = ["QualityScore", "compute_quality_score"]

#: Rule codes that count as validity violations.
_VALIDITY_RULES = frozenset(
    {
        QualityIssueType.SENTINEL_VALUE,
        QualityIssueType.OUT_OF_RANGE,
        QualityIssueType.INVALID_TYPE,
        QualityIssueType.UNKNOWN_ENUM_VALUE,
    }
)

_MISSING_REQUIRED_PENALTY = 30.0
_DUPLICATE_HEADER_PENALTY_EACH = 2.0
_DUPLICATE_HEADER_PENALTY_CAP = 10.0
_SCHEMA_DRIFT_PENALTY_CAP = 40.0
_UNKNOWN_SCHEMA_PENALTY = 10.0
_GAP_PENALTY_CAP = 30.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class QualityScore:
    """The five dimensions, the overall score, and how each was derived."""

    schema_quality: float
    completeness_quality: float
    validity_quality: float
    duplicate_quality: float
    timestamp_quality: float
    overall_quality: float

    #: Inputs behind each dimension, for the API and the UI to display.
    explanation: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def as_decimals(self) -> dict[str, Decimal]:
        return {
            "schema_quality": Decimal(f"{self.schema_quality:.2f}"),
            "completeness_quality": Decimal(f"{self.completeness_quality:.2f}"),
            "validity_quality": Decimal(f"{self.validity_quality:.2f}"),
            "duplicate_quality": Decimal(f"{self.duplicate_quality:.2f}"),
            "timestamp_quality": Decimal(f"{self.timestamp_quality:.2f}"),
            "quality_score": Decimal(f"{self.overall_quality:.2f}"),
        }


def _schema_dimension(
    context: QualityContext, findings: Sequence[QualityFinding]
) -> tuple[float, dict[str, object]]:
    header = context.profile.header
    field_count = max(header.field_count, 1)

    has_missing_required = any(
        f.rule_code is QualityIssueType.MISSING_REQUIRED_FIELD
        and f.severity is QualitySeverity.CRITICAL
        for f in findings
    )
    duplicate_names = header.duplicate_header_count
    drift = len(context.missing_schema_fields) + len(context.additional_schema_fields)

    required_penalty = _MISSING_REQUIRED_PENALTY if has_missing_required else 0.0
    duplicate_penalty = min(
        _DUPLICATE_HEADER_PENALTY_CAP, duplicate_names * _DUPLICATE_HEADER_PENALTY_EACH
    )
    drift_penalty = min(_SCHEMA_DRIFT_PENALTY_CAP, 100.0 * drift / field_count)
    unknown_penalty = 0.0 if context.schema_is_known else _UNKNOWN_SCHEMA_PENALTY

    score = _clamp(100.0 - required_penalty - duplicate_penalty - drift_penalty - unknown_penalty)
    return score, {
        "field_count": header.field_count,
        "duplicate_header_names": duplicate_names,
        "missing_required": has_missing_required,
        "schema_drift_fields": drift,
        "schema_is_known": context.schema_is_known,
        "penalties": {
            "missing_required": required_penalty,
            "duplicate_headers": duplicate_penalty,
            "schema_drift": drift_penalty,
            "unknown_schema": unknown_penalty,
        },
    }


def _completeness_dimension(context: QualityContext) -> tuple[float, dict[str, object]]:
    row_count = context.profile.row_count
    considered = [
        f
        for f in context.profile.fields
        if f.variability is not VariabilityClass.ALL_NULL_IN_SAMPLE
    ]
    excluded = len(context.profile.fields) - len(considered)

    total_cells = row_count * len(considered)
    if total_cells <= 0:
        return 100.0, {"note": "no populated fields to assess", "excluded_all_null": excluded}

    null_cells = sum(f.null_count for f in considered)
    populated = total_cells - null_cells
    score = _clamp(100.0 * populated / total_cells)
    return score, {
        "considered_fields": len(considered),
        "excluded_all_null_fields": excluded,
        "total_cells": total_cells,
        "populated_cells": populated,
        "null_cells": null_cells,
    }


def _validity_dimension(
    context: QualityContext, findings: Sequence[QualityFinding]
) -> tuple[float, dict[str, object]]:
    row_count = context.profile.row_count
    non_null_cells = sum(row_count - f.null_count for f in context.profile.fields)
    if non_null_cells <= 0:
        return 100.0, {"note": "no values to validate"}

    by_rule: dict[str, int] = {}
    violations = 0
    for finding in findings:
        if finding.rule_code in _VALIDITY_RULES:
            violations += finding.occurrence_count
            by_rule[finding.rule_code.value] = (
                by_rule.get(finding.rule_code.value, 0) + finding.occurrence_count
            )

    score = _clamp(100.0 * (1.0 - violations / non_null_cells))
    return score, {
        "non_null_cells": non_null_cells,
        "violations": violations,
        "by_rule": by_rule,
    }


def _duplicate_dimension(context: QualityContext) -> tuple[float, dict[str, object]]:
    duplicates = context.profile.duplicates
    row_count = max(context.profile.row_count, 1)
    groups = max(duplicates.logical_key_groups, 1)

    exact_ratio = duplicates.exact_duplicate_rows / row_count
    conflict_ratio = duplicates.conflicting_logical_groups / groups

    score = _clamp(100.0 - 100.0 * exact_ratio - 100.0 * conflict_ratio)
    return score, {
        "exact_duplicate_rows": duplicates.exact_duplicate_rows,
        "exact_duplicate_ratio": round(exact_ratio, 6),
        "logical_key_groups": duplicates.logical_key_groups,
        "conflicting_groups": duplicates.conflicting_logical_groups,
        "conflicting_ratio": round(conflict_ratio, 6),
        "max_rows_per_logical_key": duplicates.max_rows_per_logical_key,
    }


def _timestamp_dimension(context: QualityContext) -> tuple[float, dict[str, object]]:
    analysis = context.profile.timestamps
    considered = analysis.total_values - analysis.null_count
    parse_score = 100.0 if considered <= 0 else 100.0 * analysis.parsed_count / considered

    gap_penalty = 0.0
    threshold: float | None = None
    median = analysis.median_interval_seconds
    largest = analysis.max_interval_seconds
    if median and largest and median > 0:
        threshold = median * context.telemetry_gap_factor
        if largest > threshold:
            gap_penalty = min(_GAP_PENALTY_CAP, 10.0 * (largest / threshold - 1.0))

    score = _clamp(parse_score - gap_penalty)
    return score, {
        "chosen_format": analysis.chosen_format,
        "parsed": analysis.parsed_count,
        "failed": analysis.failed_count,
        "unique_timestamps": analysis.unique_count,
        "median_interval_seconds": median,
        "largest_interval_seconds": largest,
        "gap_threshold_seconds": threshold,
        "gap_penalty": round(gap_penalty, 3),
    }


def compute_quality_score(
    context: QualityContext,
    findings: Sequence[QualityFinding],
    weights: QualityScoreWeights | None = None,
) -> QualityScore:
    """Compute the five dimensions and their configured weighted mean."""
    weights = weights or QualityScoreWeights()

    schema, schema_detail = _schema_dimension(context, findings)
    completeness, completeness_detail = _completeness_dimension(context)
    validity, validity_detail = _validity_dimension(context, findings)
    duplicates, duplicate_detail = _duplicate_dimension(context)
    timestamps, timestamp_detail = _timestamp_dimension(context)

    weighted = {
        schema: weights.schema_quality,
        completeness: weights.completeness_quality,
        validity: weights.validity_quality,
        duplicates: weights.duplicate_quality,
        timestamps: weights.timestamp_quality,
    }
    # Recomputed from the values actually used, so a misconfigured weight set
    # that does not sum to 1.0 still yields a correctly normalised mean.
    total_weight = sum(weighted.values())
    overall = (
        sum(score * weight for score, weight in weighted.items()) / total_weight
        if total_weight > 0
        else 0.0
    )

    return QualityScore(
        schema_quality=round(schema, 2),
        completeness_quality=round(completeness, 2),
        validity_quality=round(validity, 2),
        duplicate_quality=round(duplicates, 2),
        timestamp_quality=round(timestamps, 2),
        overall_quality=round(_clamp(overall), 2),
        explanation={
            "schema_quality": schema_detail,
            "completeness_quality": completeness_detail,
            "validity_quality": validity_detail,
            "duplicate_quality": duplicate_detail,
            "timestamp_quality": timestamp_detail,
            "weights": {
                "schema_quality": weights.schema_quality,
                "completeness_quality": weights.completeness_quality,
                "validity_quality": weights.validity_quality,
                "duplicate_quality": weights.duplicate_quality,
                "timestamp_quality": weights.timestamp_quality,
            },
        },
    )
