"""The programmatic data-dictionary registry (Phase 1B sections 4, 5, 12, 13).

The dictionary is authored as YAML under ``data/dictionaries`` and ``data/
contracts``, but everything in the platform reads it through this one interface.

Resolution precedence for a raw source position, highest first:

1. explicit entry matching ``(source_name, source_occurrence)``
2. explicit entry matching ``source_name`` with no occurrence declared
3. the first matching pattern rule, in registry file order
4. the deterministic classifier (see :mod:`pipelines.validation.classifier`)

Levels 1-3 are "dictionary mapped".  Level 4 still produces a definition - no
source position is ever left without one - but it is flagged so that coverage
reporting can distinguish curated knowledge from mechanical inference.

Unknown units are rejected at load time.  That is what stops ``degC``, ``DegC``
and ``°C`` from drifting apart across 449 fields.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, overload

import yaml

from backend.app.models.enums import (
    AggregationStrategy,
    AvailabilitySemantics,
    CanonicalDataType,
    FieldCategory,
    FieldClass,
    FieldEntity,
    LeakageRisk,
    MlCandidate,
    NormalizationStrategy,
    PredictionDomain,
    RangeStatus,
    ReviewStatus,
    StorageStrategy,
)

__all__ = [
    "AllowedValueSpec",
    "DictionaryError",
    "DictionaryRegistry",
    "FieldSpec",
    "MissingValueRegistry",
    "ResolvedField",
    "SentinelSpec",
    "UnitRegistry",
]


class DictionaryError(RuntimeError):
    """The dictionary itself is invalid - a deployment error, not a data error."""


@dataclass(frozen=True, slots=True)
class SentinelSpec:
    """A field-specific value meaning "no reading" rather than a measurement."""

    value: str
    meaning: str | None = None


@dataclass(frozen=True, slots=True)
class AllowedValueSpec:
    value: str
    meaning: str | None = None


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A complete field definition (Phase 1B section 5)."""

    source_name: str
    canonical_name: str
    source_occurrence: int | None = None
    display_name: str | None = None
    description: str | None = None

    entity: FieldEntity = FieldEntity.UNKNOWN
    field_class: FieldClass = FieldClass.UNKNOWN
    category: FieldCategory = FieldCategory.UNKNOWN
    sub_category: str | None = None

    data_type: CanonicalDataType = CanonicalDataType.UNKNOWN
    unit: str | None = None
    nullable: bool = True
    required: bool = False

    sentinel_values: tuple[SentinelSpec, ...] = ()
    allowed_values: tuple[AllowedValueSpec, ...] = ()
    #: True only when the allowed-value set is known to be exhaustive.  The
    #: UNKNOWN_ENUM_VALUE rule fires only for authoritative sets (section 26);
    #: listing the values merely observed so far must not turn every new firmware
    #: state into a data-quality error.
    allowed_values_authoritative: bool = False
    valid_min: Decimal | None = None
    valid_max: Decimal | None = None
    range_status: RangeStatus = RangeStatus.UNVERIFIED

    normalization_strategy: NormalizationStrategy = NormalizationStrategy.UNKNOWN
    storage_strategy: StorageStrategy = StorageStrategy.UNKNOWN
    aggregation_strategy: AggregationStrategy = AggregationStrategy.UNKNOWN

    ml_candidate: MlCandidate = MlCandidate.UNKNOWN
    prediction_domains: tuple[PredictionDomain, ...] = ()
    leakage_risk: LeakageRisk = LeakageRisk.UNKNOWN
    availability_semantics: AvailabilitySemantics = AvailabilitySemantics.UNKNOWN

    review_status: ReviewStatus = ReviewStatus.AUTO_CLASSIFIED
    deprecated: bool = False
    notes: str | None = None

    #: Which dictionary file or pattern produced this definition.
    origin: str = "classifier"

    @property
    def needs_domain_review(self) -> bool:
        return self.review_status is ReviewStatus.DOMAIN_REVIEW_REQUIRED

    @property
    def has_verified_range(self) -> bool:
        return self.range_status is RangeStatus.VERIFIED and (
            self.valid_min is not None or self.valid_max is not None
        )


@dataclass(frozen=True, slots=True)
class ResolvedField:
    """A field spec bound to a concrete source position."""

    spec: FieldSpec
    source_position: int
    #: True for precedence levels 1-3; False when only the classifier ran.
    is_dictionary_mapped: bool


# ---------------------------------------------------------------------------
# Supporting registries
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitRegistry:
    """Closed set of assignable units (section 12)."""

    symbols: frozenset[str]
    dimensions: Mapping[str, str]

    @classmethod
    def load(cls, path: Path) -> UnitRegistry:
        if not path.exists():
            return cls(symbols=frozenset(), dimensions={})
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = payload.get("units") or []
        symbols = {str(entry["symbol"]) for entry in entries}
        dimensions = {str(e["symbol"]): str(e.get("dimension", "")) for e in entries}
        return cls(symbols=frozenset(symbols), dimensions=dimensions)

    def validate(self, unit: str | None, *, field_name: str) -> str | None:
        """``None`` is a valid answer; an unlisted symbol is a deployment bug."""
        if unit is None:
            return None
        if unit not in self.symbols:
            raise DictionaryError(
                f"Field {field_name!r} declares unknown unit {unit!r}. "
                f"Add it to data/contracts/units.yaml or use null."
            )
        return unit


@dataclass(frozen=True, slots=True)
class MissingValueRegistry:
    """Which tokens mean absence, and which merely look like it (section 14)."""

    missing_tokens: Mapping[str, str]
    case_insensitive_tokens: Mapping[str, str]
    explicit_states: Mapping[str, str]

    @classmethod
    def load(cls, path: Path) -> MissingValueRegistry:
        if not path.exists():
            return cls({}, {}, {})
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        exact: dict[str, str] = {}
        fold: dict[str, str] = {}
        for entry in payload.get("missing_tokens") or []:
            token = str(entry.get("token", ""))
            meaning = str(entry.get("meaning", "missing"))
            if entry.get("case_insensitive"):
                fold[token.casefold()] = meaning
            else:
                exact[token] = meaning
        states = {
            str(e["token"]): str(e.get("meaning", "state"))
            for e in payload.get("explicit_states") or []
        }
        return cls(missing_tokens=exact, case_insensitive_tokens=fold, explicit_states=states)

    def is_missing(self, value: str | None) -> bool:
        """A value is missing only if the registry says so - never by appearance."""
        if value is None:
            return True
        if value in self.explicit_states:
            return False  # e.g. "Not alarm" is a state, not an absence
        if value in self.missing_tokens:
            return True
        return value.casefold() in self.case_insensitive_tokens


# ---------------------------------------------------------------------------
# YAML parsing helpers
# ---------------------------------------------------------------------------


@overload
def _enum[E: StrEnum](enum_cls: type[E], value: Any, default: E, *, field_name: str) -> E: ...


@overload
def _enum[E: StrEnum](
    enum_cls: type[E], value: Any, default: None, *, field_name: str
) -> E | None: ...


def _enum[E: StrEnum](
    enum_cls: type[E], value: Any, default: E | None, *, field_name: str
) -> E | None:
    """Coerce a YAML scalar to a known enum member, or fail loudly.

    An unrecognised value is a dictionary authoring error, so it raises rather
    than degrading to the default; ``default`` covers the absent-key case only.
    """
    if value is None:
        return default
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        allowed = ", ".join(sorted(m.value for m in enum_cls))
        raise DictionaryError(
            f"Field {field_name!r}: {value!r} is not a valid {enum_cls.__name__}. "
            f"Allowed: {allowed}"
        ) from exc


def _decimal(value: Any, *, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DictionaryError(f"Field {field_name!r}: {value!r} is not numeric") from exc


def _build_spec(raw: Mapping[str, Any], *, origin: str, units: UnitRegistry) -> FieldSpec:
    source_name = raw.get("source_name")
    if not source_name:
        raise DictionaryError(f"{origin}: every field entry needs a source_name")
    name = str(source_name)

    canonical = raw.get("canonical_name")
    if not canonical:
        raise DictionaryError(f"{origin}: field {name!r} needs a canonical_name")

    return FieldSpec(
        source_name=name,
        source_occurrence=(
            int(raw["source_occurrence"]) if raw.get("source_occurrence") is not None else None
        ),
        canonical_name=str(canonical),
        display_name=_opt_str(raw.get("display_name")),
        description=_opt_str(raw.get("description")),
        entity=_enum(FieldEntity, raw.get("entity"), FieldEntity.UNKNOWN, field_name=name),
        field_class=_enum(FieldClass, raw.get("field_class"), FieldClass.UNKNOWN, field_name=name),
        category=_enum(FieldCategory, raw.get("category"), FieldCategory.UNKNOWN, field_name=name),
        sub_category=_opt_str(raw.get("sub_category")),
        data_type=_enum(
            CanonicalDataType, raw.get("data_type"), CanonicalDataType.UNKNOWN, field_name=name
        ),
        unit=units.validate(_opt_str(raw.get("unit")), field_name=name),
        nullable=bool(raw.get("nullable", True)),
        required=bool(raw.get("required", False)),
        sentinel_values=tuple(
            SentinelSpec(value=str(item["value"]), meaning=_opt_str(item.get("meaning")))
            for item in raw.get("sentinel_values") or []
        ),
        allowed_values=tuple(
            AllowedValueSpec(value=str(item["value"]), meaning=_opt_str(item.get("meaning")))
            for item in raw.get("allowed_values") or []
        ),
        allowed_values_authoritative=bool(raw.get("allowed_values_authoritative", False)),
        valid_min=_decimal(raw.get("valid_min"), field_name=name),
        valid_max=_decimal(raw.get("valid_max"), field_name=name),
        range_status=_enum(
            RangeStatus, raw.get("range_status"), RangeStatus.UNVERIFIED, field_name=name
        ),
        normalization_strategy=_enum(
            NormalizationStrategy,
            raw.get("normalization_strategy"),
            NormalizationStrategy.UNKNOWN,
            field_name=name,
        ),
        storage_strategy=_enum(
            StorageStrategy, raw.get("storage_strategy"), StorageStrategy.UNKNOWN, field_name=name
        ),
        aggregation_strategy=_enum(
            AggregationStrategy,
            raw.get("aggregation_strategy"),
            AggregationStrategy.UNKNOWN,
            field_name=name,
        ),
        ml_candidate=_enum(
            MlCandidate, raw.get("ml_candidate"), MlCandidate.UNKNOWN, field_name=name
        ),
        # An empty YAML list entry yields None and is dropped - a null domain
        # carries no meaning and must not become a tuple member.
        prediction_domains=tuple(
            domain
            for domain in (
                _enum(PredictionDomain, item, None, field_name=name)
                for item in raw.get("prediction_domains") or []
            )
            if domain is not None
        ),
        leakage_risk=_enum(
            LeakageRisk, raw.get("leakage_risk"), LeakageRisk.UNKNOWN, field_name=name
        ),
        availability_semantics=_enum(
            AvailabilitySemantics,
            raw.get("availability_semantics"),
            AvailabilitySemantics.UNKNOWN,
            field_name=name,
        ),
        review_status=_enum(
            ReviewStatus, raw.get("review_status"), ReviewStatus.AUTO_CLASSIFIED, field_name=name
        ),
        deprecated=bool(raw.get("deprecated", False)),
        notes=_opt_str(raw.get("notes")),
        origin=origin,
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class _PatternRule:
    rule_id: str
    pattern: re.Pattern[str]
    template: FieldSpec


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class DictionaryRegistry:
    """One programmatic entry point to the whole field dictionary."""

    name: str
    revision: str
    units: UnitRegistry
    missing_values: MissingValueRegistry
    by_identity: dict[tuple[str, int], FieldSpec] = field(default_factory=dict)
    by_name: dict[str, FieldSpec] = field(default_factory=dict)
    patterns: list[_PatternRule] = field(default_factory=list)

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(
        cls,
        dictionary_dir: Path,
        *,
        contracts_dir: Path | None = None,
    ) -> DictionaryRegistry:
        dictionary_dir = Path(dictionary_dir)
        contracts = Path(contracts_dir) if contracts_dir else dictionary_dir.parent / "contracts"

        registry_path = dictionary_dir / "registry.yaml"
        if not registry_path.exists():
            raise DictionaryError(f"Dictionary registry not found: {registry_path}")

        index = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        units = UnitRegistry.load(contracts / "units.yaml")
        missing = MissingValueRegistry.load(contracts / "missing_values.yaml")

        registry = cls(
            name=str(index.get("name", "unnamed")),
            revision=str(index.get("revision", "0")),
            units=units,
            missing_values=missing,
        )

        for include in index.get("includes") or []:
            path = dictionary_dir / str(include)
            if not path.exists():
                raise DictionaryError(f"Dictionary include not found: {path}")
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for raw in payload.get("fields") or []:
                spec = _build_spec(raw, origin=str(include), units=units)
                registry._register(spec)

        for raw in index.get("patterns") or []:
            rule_id = str(raw.get("id", "unnamed-pattern"))
            expression = raw.get("match")
            if not expression:
                raise DictionaryError(f"Pattern {rule_id!r} has no match expression")
            template = _build_spec(
                {**raw, "source_name": f"<pattern:{rule_id}>", "canonical_name": "<pattern>"},
                origin=f"registry.yaml#{rule_id}",
                units=units,
            )
            registry.patterns.append(
                _PatternRule(
                    rule_id=rule_id, pattern=re.compile(str(expression)), template=template
                )
            )

        registry._validate()
        return registry

    def _register(self, spec: FieldSpec) -> None:
        if spec.source_occurrence is None:
            if spec.source_name in self.by_name:
                raise DictionaryError(
                    f"Duplicate dictionary entry for {spec.source_name!r} "
                    f"in {spec.origin} (already defined in {self.by_name[spec.source_name].origin})"
                )
            self.by_name[spec.source_name] = spec
        else:
            key = (spec.source_name, spec.source_occurrence)
            if key in self.by_identity:
                raise DictionaryError(
                    f"Duplicate dictionary entry for {spec.source_name!r} "
                    f"occurrence {spec.source_occurrence} in {spec.origin}"
                )
            self.by_identity[key] = spec

    def _validate(self) -> None:
        """Canonical names must be unique across the curated dictionary."""
        seen: dict[str, str] = {}
        for spec in [*self.by_name.values(), *self.by_identity.values()]:
            existing = seen.get(spec.canonical_name)
            if existing is not None:
                raise DictionaryError(
                    f"Canonical name {spec.canonical_name!r} is declared twice "
                    f"({existing} and {spec.source_name})"
                )
            seen[spec.canonical_name] = spec.source_name

    # -- resolution --------------------------------------------------------

    def resolve(
        self,
        source_name: str,
        *,
        occurrence: int,
        position: int,
        fallback_canonical: str,
    ) -> ResolvedField:
        """Resolve one raw source position to a complete definition."""
        explicit = self.by_identity.get((source_name, occurrence))
        if explicit is not None:
            return ResolvedField(explicit, source_position=position, is_dictionary_mapped=True)

        named = self.by_name.get(source_name)
        if named is not None:
            spec = named
            if occurrence > 1:
                # A single entry covering a repeated header cannot claim to
                # describe both occurrences; the extra ones need review.
                spec = replace(
                    spec,
                    canonical_name=f"{named.canonical_name}_occurrence_{occurrence}",
                    source_occurrence=occurrence,
                    review_status=ReviewStatus.DOMAIN_REVIEW_REQUIRED,
                    notes=(
                        f"{named.notes + ' ' if named.notes else ''}"
                        f"Occurrence {occurrence} of a repeated raw header inherits the "
                        f"occurrence-1 definition and requires domain confirmation."
                    ),
                )
            return ResolvedField(spec, source_position=position, is_dictionary_mapped=True)

        for rule in self.patterns:
            if rule.pattern.match(source_name):
                spec = replace(
                    rule.template,
                    source_name=source_name,
                    source_occurrence=occurrence,
                    canonical_name=fallback_canonical,
                    display_name=source_name,
                )
                return ResolvedField(spec, source_position=position, is_dictionary_mapped=True)

        # Level 4: the classifier. Imported lazily to keep the dependency
        # one-directional (classifier may read registry types, not vice versa).
        from pipelines.validation.classifier import classify_field

        spec = classify_field(
            source_name,
            occurrence=occurrence,
            canonical_name=fallback_canonical,
            units=self.units,
        )
        return ResolvedField(spec, source_position=position, is_dictionary_mapped=False)

    def resolve_all(
        self, header_fields: Iterable[tuple[str, int, int, str]]
    ) -> Sequence[ResolvedField]:
        """Resolve every source position.

        Each input tuple is ``(source_name, occurrence, position, canonical)``.
        """
        return [
            self.resolve(
                name, occurrence=occurrence, position=position, fallback_canonical=canonical
            )
            for name, occurrence, position, canonical in header_fields
        ]

    @property
    def curated_field_count(self) -> int:
        return len(self.by_name) + len(self.by_identity)
