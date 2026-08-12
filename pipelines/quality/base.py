"""Quality rule framework (Phase 1B section 25).

The engine is a registry of small, independent rules - deliberately not one
large function.  Each rule declares its ``rule_code``, ``scope`` and default
severity, and evaluates against a *shared* :class:`QualityContext`.

The shared context is the performance contract (section 38): the file is loaded
and profiled exactly once, and every rule reads from that single result.  No
rule may re-open the file.

Determinism (section 39): each finding computes a stable ``issue_hash`` from its
rule code and locator.  Re-running analysis over the same immutable file and
schema version yields identical hashes, so persistence converges instead of
accumulating duplicate rows.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.app.models.enums import (
    FieldEntity,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)
from pipelines.profiling.profiler import FieldProfile, FileProfile
from pipelines.validation.dictionary import DictionaryRegistry, FieldSpec, ResolvedField

__all__ = [
    "QualityContext",
    "QualityFinding",
    "QualityRule",
    "RuleRegistry",
]

#: Raw values are truncated before they are ever stored or logged.
MAX_RAW_VALUE_CHARS = 128


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One rule outcome.

    Rules aggregate: a sentinel appearing 4,000 times is a single finding with
    ``occurrence_count=4000``, never 4,000 rows.
    """

    rule_code: QualityIssueType
    scope: QualityRuleScope
    severity: QualitySeverity
    message: str

    field_name: str | None = None
    field_occurrence: int | None = None
    canonical_name: str | None = None
    entity: FieldEntity | None = None
    source_row_number: int | None = None
    event_time: dt.datetime | None = None
    entity_reference: str | None = None
    raw_value: str | None = None
    occurrence_count: int = 1
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def issue_hash(self) -> str:
        """Stable identity: rule code plus the locator, never the counts.

        Counts are excluded deliberately so that a re-run which finds the same
        problem with a different tally updates one row rather than creating a
        second one.
        """
        parts = (
            self.rule_code.value,
            self.scope.value,
            self.field_name or "",
            str(self.field_occurrence or ""),
            str(self.source_row_number or ""),
            self.entity_reference or "",
            self.event_time.isoformat() if self.event_time else "",
        )
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def truncated_value(self) -> str | None:
        if self.raw_value is None:
            return None
        return self.raw_value[:MAX_RAW_VALUE_CHARS]


@dataclass
class QualityContext:
    """Everything the rules need, assembled once per file."""

    profile: FileProfile
    resolved_fields: Sequence[ResolvedField]
    registry: DictionaryRegistry

    original_filename: str
    filename_date: dt.date | None = None

    expected_connector_count: int | None = None
    expected_smr_count: int | None = None
    telemetry_gap_factor: float = 5.0
    timestamp_failure_tolerance: float = 0.02

    #: Fields the previously-registered schema had that this file does not,
    #: and vice versa. Populated by the schema compatibility check.
    missing_schema_fields: Sequence[str] = ()
    additional_schema_fields: Sequence[str] = ()
    schema_is_known: bool = True

    def __post_init__(self) -> None:
        self._spec_by_position: dict[int, FieldSpec] = {
            r.source_position: r.spec for r in self.resolved_fields
        }
        self._mapped_by_position: dict[int, bool] = {
            r.source_position: r.is_dictionary_mapped for r in self.resolved_fields
        }
        self._profile_by_position: dict[int, FieldProfile] = {
            f.position: f for f in self.profile.fields
        }

    def spec(self, position: int) -> FieldSpec | None:
        return self._spec_by_position.get(position)

    def is_dictionary_mapped(self, position: int) -> bool:
        return self._mapped_by_position.get(position, False)

    def field_profile(self, position: int) -> FieldProfile | None:
        return self._profile_by_position.get(position)

    def pairs(self) -> Iterable[tuple[FieldSpec, FieldProfile]]:
        """Every (definition, observation) pair, aligned by source position."""
        for position, spec in self._spec_by_position.items():
            observed = self._profile_by_position.get(position)
            if observed is not None:
                yield spec, observed


@runtime_checkable
class QualityRule(Protocol):
    """Contract every rule implements."""

    rule_code: QualityIssueType
    scope: QualityRuleScope
    default_severity: QualitySeverity

    def evaluate(self, context: QualityContext) -> Iterable[QualityFinding]:
        """Return findings. Must not mutate the context or read the file."""
        ...


class RuleRegistry:
    """Ordered collection of rules, executed as a unit."""

    def __init__(self, rules: Sequence[QualityRule] | None = None) -> None:
        self._rules: list[QualityRule] = list(rules or ())

    def register(self, rule: QualityRule) -> None:
        self._rules.append(rule)

    def __len__(self) -> int:
        return len(self._rules)

    @property
    def rules(self) -> Sequence[QualityRule]:
        return tuple(self._rules)

    def evaluate(self, context: QualityContext) -> list[QualityFinding]:
        """Run every rule.

        A rule that raises is contained: its failure is reported as a finding
        rather than aborting the whole quality pass, because one broken rule
        must not cost us the analysis of an otherwise good file.
        """
        findings: list[QualityFinding] = []
        for rule in self._rules:
            try:
                findings.extend(rule.evaluate(context))
            except Exception as exc:  # noqa: BLE001 - deliberate containment
                findings.append(
                    QualityFinding(
                        rule_code=rule.rule_code,
                        scope=rule.scope,
                        severity=QualitySeverity.ERROR,
                        message=f"Quality rule {type(rule).__name__} failed: {exc}",
                        details={"rule": type(rule).__name__, "error": str(exc)},
                    )
                )
        # Stable ordering makes persisted output reproducible run to run.
        findings.sort(key=lambda f: (f.rule_code.value, f.field_name or "", f.issue_hash))
        return findings
