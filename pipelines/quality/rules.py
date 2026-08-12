"""Concrete quality rules (Phase 1A section 13, Phase 1B section 26).

Each rule is small, independent and reads only the shared context.  Severity
choices are deliberate and documented inline - notably ALL_NULL_FIELD is INFO,
not an error, because an alarm that did not fire is normal.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation

from backend.app.models.enums import (
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
    VariabilityClass,
)
from pipelines.profiling.column_roles import ColumnRole
from pipelines.quality.base import QualityContext, QualityFinding, QualityRule, RuleRegistry

__all__ = ["build_default_registry"]


# ---------------------------------------------------------------------------
# File-scope structural rules
# ---------------------------------------------------------------------------


class DuplicateHeaderRule:
    rule_code = QualityIssueType.DUPLICATE_HEADER
    scope = QualityRuleScope.FILE
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        for name, count in sorted(context.profile.header.duplicate_names.items()):
            yield QualityFinding(
                rule_code=self.rule_code,
                scope=self.scope,
                severity=self.default_severity,
                message=(
                    f"Raw header {name!r} appears {count} times. Occurrences are preserved "
                    f"as separate source identities and are not renamed."
                ),
                field_name=name,
                occurrence_count=count,
                details={"occurrences": count},
            )


class MissingRequiredFieldRule:
    """A field the contract marks ``required`` is absent from the header."""

    rule_code = QualityIssueType.MISSING_REQUIRED_FIELD
    scope = QualityRuleScope.FILE
    default_severity = QualitySeverity.CRITICAL

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        present = {f.source_name for f in context.profile.header.fields}
        required = [
            spec
            for spec in (
                *context.registry.by_name.values(),
                *context.registry.by_identity.values(),
            )
            if spec.required
        ]
        for spec in sorted(required, key=lambda s: s.source_name):
            if spec.source_name not in present:
                yield QualityFinding(
                    rule_code=self.rule_code,
                    scope=self.scope,
                    severity=self.default_severity,
                    message=f"Required field {spec.source_name!r} is missing from the file.",
                    field_name=spec.source_name,
                    canonical_name=spec.canonical_name,
                    entity=spec.entity,
                )

        # A structurally required *role* being unresolvable is equally fatal.
        for role in context.profile.roles.missing_required:
            yield QualityFinding(
                rule_code=self.rule_code,
                scope=self.scope,
                severity=QualitySeverity.CRITICAL,
                message=(
                    f"No column could be resolved for the required structural role "
                    f"{role.value}; the file cannot be interpreted."
                ),
                details={"role": role.value},
            )


class UnknownFieldRule:
    """Source positions with no curated dictionary entry (classifier only)."""

    rule_code = QualityIssueType.UNKNOWN_FIELD
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.INFO

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        unmapped = [r for r in context.resolved_fields if not r.is_dictionary_mapped]
        if not unmapped:
            return
        # Aggregated: hundreds of individually-uninteresting rows would drown the
        # genuinely actionable findings.
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"{len(unmapped)} source position(s) have no curated dictionary entry and "
                f"were classified automatically."
            ),
            occurrence_count=len(unmapped),
            details={
                "positions": [r.source_position for r in unmapped[:50]],
                "examples": [r.spec.source_name for r in unmapped[:10]],
            },
        )


class SchemaDriftRule:
    """Fields present in the registered schema but absent here, and vice versa."""

    rule_code = QualityIssueType.SCHEMA_MISMATCH
    scope = QualityRuleScope.FILE
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        if context.missing_schema_fields:
            yield QualityFinding(
                rule_code=QualityIssueType.MISSING_FIELD,
                scope=self.scope,
                severity=QualitySeverity.WARNING,
                message=(
                    f"{len(context.missing_schema_fields)} field(s) known to the registered "
                    f"schema are absent from this file."
                ),
                occurrence_count=len(context.missing_schema_fields),
                details={"fields": list(context.missing_schema_fields[:50])},
            )
        if context.additional_schema_fields:
            yield QualityFinding(
                rule_code=self.rule_code,
                scope=self.scope,
                severity=QualitySeverity.WARNING,
                message=(
                    f"{len(context.additional_schema_fields)} field(s) in this file are not "
                    f"present in the registered schema."
                ),
                occurrence_count=len(context.additional_schema_fields),
                details={"fields": list(context.additional_schema_fields[:50])},
            )


# ---------------------------------------------------------------------------
# Temporal rules
# ---------------------------------------------------------------------------


class InvalidTimestampRule:
    rule_code = QualityIssueType.INVALID_TIMESTAMP
    scope = QualityRuleScope.TIMESTAMP
    default_severity = QualitySeverity.ERROR

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        analysis = context.profile.timestamps
        if analysis.failed_count <= 0:
            return
        severity = (
            QualitySeverity.CRITICAL
            if not analysis.is_within_tolerance(context.timestamp_failure_tolerance)
            else QualitySeverity.WARNING
        )
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=severity,
            message=(
                f"{analysis.failed_count} event timestamp(s) could not be parsed using "
                f"{analysis.chosen_format or 'any configured format'} "
                f"({analysis.failure_ratio:.2%} of non-null values)."
            ),
            field_name=analysis.column,
            occurrence_count=analysis.failed_count,
            details={
                "chosen_format": analysis.chosen_format,
                "failure_ratio": round(analysis.failure_ratio, 6),
                "tolerance": context.timestamp_failure_tolerance,
            },
        )


class TelemetryGapRule:
    """Sampling interval far above the file's own median cadence."""

    rule_code = QualityIssueType.TELEMETRY_GAP
    scope = QualityRuleScope.TIMESTAMP
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        analysis = context.profile.timestamps
        median = analysis.median_interval_seconds
        largest = analysis.max_interval_seconds
        if not median or not largest or median <= 0:
            return
        threshold = median * context.telemetry_gap_factor
        if largest <= threshold:
            return
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"Largest inter-sample interval is {largest:.0f}s against a median cadence of "
                f"{median:.0f}s (threshold {threshold:.0f}s)."
            ),
            field_name=analysis.column,
            details={
                "median_interval_seconds": median,
                "largest_interval_seconds": largest,
                "threshold_seconds": threshold,
                "factor": context.telemetry_gap_factor,
            },
        )


class EventDateFilenameMismatchRule:
    """The filename's date disagrees with the telemetry it contains.

    Informational by design: the filename is never authoritative, so a mismatch
    is a labelling observation, not a data defect.
    """

    rule_code = QualityIssueType.EVENT_DATE_FILENAME_MISMATCH
    scope = QualityRuleScope.FILE
    default_severity = QualitySeverity.INFO

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        filename_date = context.filename_date
        actual = context.profile.timestamps.dominant_business_date
        if filename_date is None or actual is None or filename_date == actual:
            return
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"Filename suggests {filename_date.isoformat()} but telemetry event times "
                f"resolve to {actual.isoformat()}. Event time is authoritative."
            ),
            details={
                "filename_date": filename_date.isoformat(),
                "event_business_date": actual.isoformat(),
            },
        )


# ---------------------------------------------------------------------------
# Duplication rules
# ---------------------------------------------------------------------------


class ExactDuplicateRule:
    rule_code = QualityIssueType.EXACT_DUPLICATE
    scope = QualityRuleScope.ROW
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        duplicates = context.profile.duplicates
        if duplicates.exact_duplicate_rows <= 0:
            return
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"{duplicates.exact_duplicate_rows} byte-identical duplicate row(s) detected "
                f"across {duplicates.rows_participating_in_duplicates} participating rows."
            ),
            occurrence_count=duplicates.exact_duplicate_rows,
            details={
                "exact_duplicate_rows": duplicates.exact_duplicate_rows,
                "participating_rows": duplicates.rows_participating_in_duplicates,
            },
        )


class LogicalKeyCollisionRule:
    """Several raw rows share (event time, connector, SMR).

    Escalated when the colliding rows differ: identical rows are a harmless
    replay, but differing rows are genuine competing observations that Phase 1D
    must reconcile and that must never be silently discarded.
    """

    rule_code = QualityIssueType.LOGICAL_KEY_COLLISION
    scope = QualityRuleScope.ENTITY
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        duplicates = context.profile.duplicates
        if duplicates.logical_collision_groups <= 0:
            return
        conflicting = duplicates.conflicting_logical_groups
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=(QualitySeverity.ERROR if conflicting > 0 else QualitySeverity.WARNING),
            message=(
                f"{duplicates.logical_collision_groups} logical key group(s) hold more than one "
                f"row; {conflicting} contain differing values and require Phase 1D "
                f"reconstruction. Max rows per key: {duplicates.max_rows_per_logical_key}."
            ),
            occurrence_count=duplicates.logical_collision_groups,
            details={
                "collision_groups": duplicates.logical_collision_groups,
                "conflicting_groups": conflicting,
                "max_rows_per_key": duplicates.max_rows_per_logical_key,
                "rows_per_timestamp": dict(duplicates.rows_per_timestamp),
            },
        )


# ---------------------------------------------------------------------------
# Cardinality rules
# ---------------------------------------------------------------------------


class _CardinalityRule:
    role: ColumnRole
    label: str

    def __init__(self, rule_code: QualityIssueType, role: ColumnRole, label: str) -> None:
        self.rule_code = rule_code
        self.scope = QualityRuleScope.FILE
        self.default_severity = QualitySeverity.WARNING
        self.role = role
        self.label = label

    def _expected(self, context: QualityContext) -> int | None:
        return (
            context.expected_connector_count
            if self.role is ColumnRole.CONNECTOR
            else context.expected_smr_count
        )

    def _observed(self, context: QualityContext) -> dict[str, int]:
        return dict(
            context.profile.connectors
            if self.role is ColumnRole.CONNECTOR
            else context.profile.smrs
        )

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        expected = self._expected(context)
        observed = self._observed(context)
        if expected is None or not observed:
            return
        if len(observed) == expected:
            return
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"Expected {expected} {self.label}(s) but observed {len(observed)}: "
                f"{sorted(observed)}."
            ),
            occurrence_count=abs(expected - len(observed)),
            details={"expected": expected, "observed": sorted(observed)},
        )


def _connector_rule() -> QualityRule:
    return _CardinalityRule(
        QualityIssueType.UNEXPECTED_CONNECTOR_CARDINALITY, ColumnRole.CONNECTOR, "connector"
    )


def _smr_rule() -> QualityRule:
    return _CardinalityRule(QualityIssueType.UNEXPECTED_SMR_CARDINALITY, ColumnRole.SMR, "SMR")


# ---------------------------------------------------------------------------
# Field-scope value rules
# ---------------------------------------------------------------------------


class AllNullFieldRule:
    """Informational only.

    A field being empty for one charger-day says nothing about its usefulness:
    the alarm may not have fired, or the optional hardware may not be fitted.
    Section 29 is explicit that this must never become "field is useless".
    """

    rule_code = QualityIssueType.ALL_NULL_FIELD
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.INFO

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        empty = [
            f
            for f in context.profile.fields
            if f.variability is VariabilityClass.ALL_NULL_IN_SAMPLE
        ]
        if not empty:
            return
        yield QualityFinding(
            rule_code=self.rule_code,
            scope=self.scope,
            severity=self.default_severity,
            message=(
                f"{len(empty)} field(s) are empty throughout this file. This is an observation "
                f"about this charger-day only, not a judgement about the fields."
            ),
            occurrence_count=len(empty),
            details={"fields": [f.source_name for f in empty[:50]]},
        )


class SentinelValueRule:
    """Field-specific sentinel detection.

    Sentinels come from the field's own definition, never from a global list, so
    ``-150`` is flagged on SMR internal temperature but not on a field where it
    could be a real reading.
    """

    rule_code = QualityIssueType.SENTINEL_VALUE
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        for spec, observed in context.pairs():
            if not spec.sentinel_values:
                continue
            declared = {s.value: s.meaning for s in spec.sentinel_values}
            for value, count in observed.sentinel_hits.items():
                if value not in declared or count <= 0:
                    continue
                yield QualityFinding(
                    rule_code=self.rule_code,
                    scope=self.scope,
                    severity=self.default_severity,
                    message=(
                        f"{count} reading(s) of {spec.source_name!r} equal the sentinel "
                        f"{value!r} ({declared[value] or 'meaning undeclared'}); these are not "
                        f"measurements."
                    ),
                    field_name=spec.source_name,
                    field_occurrence=spec.source_occurrence,
                    canonical_name=spec.canonical_name,
                    entity=spec.entity,
                    raw_value=value,
                    occurrence_count=count,
                    details={"sentinel": value, "meaning": declared[value]},
                )


class OutOfRangeRule:
    """Only fires for ranges marked VERIFIED (section 15)."""

    rule_code = QualityIssueType.OUT_OF_RANGE
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.ERROR

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        for spec, observed in context.pairs():
            if not spec.has_verified_range or not observed.is_numeric:
                continue
            sentinels = {s.value for s in spec.sentinel_values}
            for bound_name, bound, actual in (
                ("valid_min", spec.valid_min, observed.min_value),
                ("valid_max", spec.valid_max, observed.max_value),
            ):
                if bound is None or actual is None:
                    continue
                # A sentinel is not an out-of-range measurement.
                if actual in sentinels:
                    continue
                try:
                    numeric = Decimal(actual)
                except (InvalidOperation, ValueError):
                    continue
                breached = numeric < bound if bound_name == "valid_min" else numeric > bound
                if not breached:
                    continue
                yield QualityFinding(
                    rule_code=self.rule_code,
                    scope=self.scope,
                    severity=self.default_severity,
                    message=(
                        f"{spec.source_name!r} observed {actual} which breaches the verified "
                        f"{bound_name} of {bound}."
                    ),
                    field_name=spec.source_name,
                    field_occurrence=spec.source_occurrence,
                    canonical_name=spec.canonical_name,
                    entity=spec.entity,
                    raw_value=actual,
                    details={bound_name: str(bound), "observed": actual},
                )


class InvalidTypeRule:
    """Values that cannot be read as the field's declared semantic type."""

    rule_code = QualityIssueType.INVALID_TYPE
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.ERROR

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        row_count = context.profile.row_count
        for spec, observed in context.pairs():
            if not spec.data_type.is_numeric:
                continue
            non_null = row_count - observed.null_count
            if non_null <= 0:
                continue
            valid = observed.numeric_valid_count or 0
            invalid = non_null - valid
            if invalid <= 0:
                continue
            yield QualityFinding(
                rule_code=self.rule_code,
                scope=self.scope,
                severity=self.default_severity,
                message=(
                    f"{invalid} value(s) in {spec.source_name!r} are not valid "
                    f"{spec.data_type.value}."
                ),
                field_name=spec.source_name,
                field_occurrence=spec.source_occurrence,
                canonical_name=spec.canonical_name,
                entity=spec.entity,
                occurrence_count=invalid,
                details={
                    "declared_type": spec.data_type.value,
                    "non_null": non_null,
                    "parsed": valid,
                },
            )


class UnknownEnumValueRule:
    """Fires only where an authoritative allowed-value set has been declared."""

    rule_code = QualityIssueType.UNKNOWN_ENUM_VALUE
    scope = QualityRuleScope.FIELD
    default_severity = QualitySeverity.WARNING

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        for spec, observed in context.pairs():
            if not spec.allowed_values_authoritative or not spec.allowed_values:
                continue
            if observed.observed_values is None:
                continue  # too high-cardinality to enumerate; not an enum in practice
            allowed = {a.value for a in spec.allowed_values}
            unexpected = [v for v in observed.observed_values if v not in allowed]
            if not unexpected:
                continue
            yield QualityFinding(
                rule_code=self.rule_code,
                scope=self.scope,
                severity=self.default_severity,
                message=(
                    f"{spec.source_name!r} contains {len(unexpected)} value(s) outside its "
                    f"authoritative allowed set: {unexpected[:10]}."
                ),
                field_name=spec.source_name,
                field_occurrence=spec.source_occurrence,
                canonical_name=spec.canonical_name,
                entity=spec.entity,
                raw_value=unexpected[0],
                occurrence_count=len(unexpected),
                details={"unexpected": unexpected[:20], "allowed": sorted(allowed)},
            )


# ---------------------------------------------------------------------------


def build_default_registry() -> RuleRegistry:
    """The Phase 1A/1B rule set, in execution order."""
    rules: Sequence[QualityRule] = (
        DuplicateHeaderRule(),
        MissingRequiredFieldRule(),
        UnknownFieldRule(),
        SchemaDriftRule(),
        InvalidTimestampRule(),
        TelemetryGapRule(),
        EventDateFilenameMismatchRule(),
        ExactDuplicateRule(),
        LogicalKeyCollisionRule(),
        _connector_rule(),
        _smr_rule(),
        AllNullFieldRule(),
        SentinelValueRule(),
        OutOfRangeRule(),
        InvalidTypeRule(),
        UnknownEnumValueRule(),
    )
    return RuleRegistry(rules)
