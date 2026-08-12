"""Deterministic field classifier - the last resort in dictionary resolution.

This runs only for source positions that no curated entry and no pattern rule
covers.  It exists so that all 449 positions always have a definition, never so
that the platform can pretend to understand a field it does not.

Two rules govern everything here:

* **Only assert what the name justifies.**  ``Cabinet Temperature`` genuinely
  implies a Celsius measurement.  ``Config Parameter 7`` implies nothing beyond
  "probably configuration", so that is all it gets.
* **Uncertainty is a recorded state, not a guess.**  When entity or semantic
  class cannot be determined, the result is ``UNKNOWN`` plus
  ``DOMAIN_REVIEW_REQUIRED`` and a note explaining what was and was not inferred.

No statistical inference happens here: classification depends only on the field
name, so it is stable across files and reproducible without data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
    RangeStatus,
    ReviewStatus,
    StorageStrategy,
)
from pipelines.validation.dictionary import FieldSpec, UnitRegistry

__all__ = ["classify_field"]


@dataclass(frozen=True, slots=True)
class _Rule[T]:
    """A keyword rule. ``all_of`` must match; ``none_of`` must not.

    Generic over the enum it yields so that ``_first_match`` returns the precise
    enum type rather than ``object`` - the classification then type-checks all
    the way into :class:`FieldSpec` with no casts.
    """

    keywords: tuple[str, ...]
    result: T
    none_of: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        if any(bad in text for bad in self.none_of):
            return False
        return any(keyword in text for keyword in self.keywords)


# --- entity -----------------------------------------------------------------
# Ordered: the first match wins, so more specific entities come first.
_ENTITY_RULES: Sequence[_Rule[FieldEntity]] = (
    _Rule(("alarm", "fault", "trip", "error code"), FieldEntity.ALARM),
    _Rule(("smr", "rectifier"), FieldEntity.SMR),
    _Rule(("session", "transaction", "charge session"), FieldEntity.SESSION),
    _Rule(("connector", "gun", "plug", "socket"), FieldEntity.CONNECTOR),
    _Rule(("site", "station"), FieldEntity.SITE),
    _Rule(("config", "setting", "parameter", "threshold", "limit"), FieldEntity.CONFIGURATION),
    _Rule(
        ("charger", "cabinet", "grid", "meter", "contactor", "fan", "cooling"), FieldEntity.CHARGER
    ),
)

# --- category ---------------------------------------------------------------
_CATEGORY_RULES: Sequence[_Rule[FieldCategory]] = (
    _Rule(("insulation", "isolation"), FieldCategory.INSULATION),
    _Rule(("temp", "thermal"), FieldCategory.THERMAL),
    _Rule(("ocpp",), FieldCategory.OCPP),
    _Rule(("ccs",), FieldCategory.CCS),
    _Rule(("ccu",), FieldCategory.CCU),
    _Rule(("plc",), FieldCategory.PLC),
    _Rule(("can bus", "canbus", "can "), FieldCategory.CAN),
    _Rule(("alarm",), FieldCategory.ALARM),
    _Rule(("fault", "trip", "error"), FieldCategory.FAULT),
    _Rule(("contactor", "relay"), FieldCategory.CONTACTOR),
    _Rule(("fan",), FieldCategory.FAN),
    _Rule(("cooling", "coolant", "pump"), FieldCategory.COOLING),
    _Rule(("meter",), FieldCategory.METER),
    _Rule(("battery", "soc", "vehicle"), FieldCategory.BATTERY),
    _Rule(("gun", "plug", "socket"), FieldCategory.GUN),
    _Rule(("firmware", "software version"), FieldCategory.FIRMWARE),
    _Rule(("hardware", "board", "pcb"), FieldCategory.HARDWARE),
    _Rule(("counter", "total", "cumulative", "lifetime"), FieldCategory.COUNTER),
    _Rule(("session", "transaction"), FieldCategory.SESSION),
    _Rule(("smr", "rectifier", "module"), FieldCategory.SMR),
    _Rule(("connector",), FieldCategory.CONNECTOR),
    _Rule(("grid", "input", "mains", "supply"), FieldCategory.ELECTRICAL_INPUT),
    _Rule(("output", "dc "), FieldCategory.ELECTRICAL_OUTPUT),
    _Rule(("signal", "network", "modem", "sim", "gsm"), FieldCategory.COMMUNICATION),
    _Rule(("state", "status", "mode"), FieldCategory.STATE_MACHINE),
    _Rule(("id", "serial", "identity"), FieldCategory.IDENTITY),
)

# --- semantic class ---------------------------------------------------------
_CLASS_RULES: Sequence[_Rule[FieldClass]] = (
    _Rule(("alarm",), FieldClass.ALARM_FLAG),
    _Rule(("fault code", "error code", "reason code"), FieldClass.FAULT_CODE),
    _Rule(("time", "date", "timestamp"), FieldClass.TIMESTAMP),
    _Rule(("counter", "total", "cumulative", "lifetime", "uptime"), FieldClass.COUNTER),
    _Rule(("status", "state", "mode", "flag"), FieldClass.STATE),
    _Rule(("id", "serial", "identity"), FieldClass.IDENTIFIER),
    _Rule(("config", "setting", "parameter", "threshold", "limit"), FieldClass.CONFIGURATION),
    _Rule(
        ("temp", "voltage", "current", "power", "energy", "frequency", "resistance", "speed"),
        FieldClass.CONTINUOUS_TELEMETRY,
    ),
)

# --- measurement type and unit ---------------------------------------------
# A unit is asserted only where the name names the measured quantity.
_UNIT_RULES: tuple[tuple[tuple[str, ...], str, CanonicalDataType], ...] = (
    (("temperature", "temp"), "°C", CanonicalDataType.FLOAT),
    (("voltage", "volt"), "V", CanonicalDataType.FLOAT),
    (("current", "ampere", "amp"), "A", CanonicalDataType.FLOAT),
    (("frequency",), "Hz", CanonicalDataType.FLOAT),
    (("energy", "kwh"), "kWh", CanonicalDataType.FLOAT),
    (("power",), "kW", CanonicalDataType.FLOAT),
    (("resistance", "insulation"), "kOhm", CanonicalDataType.FLOAT),
    (("percentage", "percent", "soc"), "percent", CanonicalDataType.FLOAT),
    (("duration", "elapsed", "uptime", "seconds"), "seconds", CanonicalDataType.DURATION),
    (("speed", "rpm"), "rpm", CanonicalDataType.INTEGER),
    (("counter", "count"), "count", CanonicalDataType.INTEGER),
)

_STORAGE_BY_ENTITY = {
    FieldEntity.CHARGER: StorageStrategy.CHARGER_TELEMETRY,
    FieldEntity.CONNECTOR: StorageStrategy.CONNECTOR_TELEMETRY,
    FieldEntity.SMR: StorageStrategy.SMR_TELEMETRY,
    FieldEntity.SESSION: StorageStrategy.SESSION_OBSERVATION,
    FieldEntity.ALARM: StorageStrategy.ALARM_EVENT,
    FieldEntity.CONFIGURATION: StorageStrategy.CONFIGURATION_SNAPSHOT,
    FieldEntity.SITE: StorageStrategy.MASTER_DATA,
    FieldEntity.FILE: StorageStrategy.RAW_ONLY,
    FieldEntity.UNKNOWN: StorageStrategy.RAW_ONLY,
}

_NORMALIZATION_BY_ENTITY = {
    FieldEntity.CHARGER: NormalizationStrategy.CHARGER_SCALAR,
    FieldEntity.CONNECTOR: NormalizationStrategy.PER_CONNECTOR,
    FieldEntity.SMR: NormalizationStrategy.PER_SMR,
    FieldEntity.SESSION: NormalizationStrategy.PER_SESSION,
    FieldEntity.ALARM: NormalizationStrategy.ALARM_EDGE,
    FieldEntity.CONFIGURATION: NormalizationStrategy.CONFIG_SNAPSHOT,
    FieldEntity.SITE: NormalizationStrategy.CHARGER_SCALAR,
    FieldEntity.FILE: NormalizationStrategy.PASSTHROUGH,
    FieldEntity.UNKNOWN: NormalizationStrategy.RAW_RETAIN,
}

_AGGREGATION_BY_CLASS = {
    FieldClass.CONTINUOUS_TELEMETRY: AggregationStrategy.MEAN,
    FieldClass.COUNTER: AggregationStrategy.MAX,
    FieldClass.STATE: AggregationStrategy.LAST,
    FieldClass.ALARM_FLAG: AggregationStrategy.ANY_TRUE,
    FieldClass.IDENTIFIER: AggregationStrategy.FIRST,
    FieldClass.TIMESTAMP: AggregationStrategy.FIRST,
    FieldClass.CONFIGURATION: AggregationStrategy.LAST,
    FieldClass.FAULT_CODE: AggregationStrategy.LAST,
}


def _first_match[T](rules: Sequence[_Rule[T]], text: str, default: T) -> T:
    for rule in rules:
        if rule.matches(text):
            return rule.result
    return default


def classify_field(
    source_name: str,
    *,
    occurrence: int,
    canonical_name: str,
    units: UnitRegistry | None = None,
) -> FieldSpec:
    """Infer a definition from a field name alone.

    The returned spec is always complete, but ``review_status`` records how much
    of it is actually knowable.
    """
    text = source_name.casefold()

    entity = _first_match(_ENTITY_RULES, text, FieldEntity.UNKNOWN)
    field_class = _first_match(_CLASS_RULES, text, FieldClass.UNKNOWN)
    category = _first_match(_CATEGORY_RULES, text, FieldCategory.UNKNOWN)

    unit: str | None = None
    data_type = CanonicalDataType.UNKNOWN
    for keywords, symbol, inferred_type in _UNIT_RULES:
        if any(keyword in text for keyword in keywords):
            unit, data_type = symbol, inferred_type
            break

    if data_type is CanonicalDataType.UNKNOWN:
        if field_class is FieldClass.TIMESTAMP:
            data_type = CanonicalDataType.DATETIME
        elif field_class is FieldClass.IDENTIFIER:
            data_type = CanonicalDataType.IDENTIFIER
        elif field_class in {FieldClass.STATE, FieldClass.ALARM_FLAG}:
            data_type = CanonicalDataType.ENUM

    # A unit that is not in the registry is dropped rather than invented.
    if unit is not None and units is not None and unit not in units.symbols:
        unit = None

    # State/identifier/timestamp fields legitimately have no unit.
    if field_class in {FieldClass.STATE, FieldClass.IDENTIFIER, FieldClass.ALARM_FLAG}:
        unit = None

    determined = entity is not FieldEntity.UNKNOWN and field_class is not FieldClass.UNKNOWN
    review = ReviewStatus.AUTO_CLASSIFIED if determined else ReviewStatus.DOMAIN_REVIEW_REQUIRED

    inferred_parts = [
        part
        for part, value in (
            ("entity", entity),
            ("class", field_class),
            ("category", category),
        )
        if str(value) != "UNKNOWN"
    ]
    note = (
        "Auto-classified from the field name. "
        + (f"Inferred: {', '.join(inferred_parts)}. " if inferred_parts else "")
        + (
            "No curated dictionary entry exists; semantics require domain confirmation "
            "before downstream use."
            if not determined
            else "No curated dictionary entry exists; review recommended before "
            "treating the classification as authoritative."
        )
    )

    return FieldSpec(
        source_name=source_name,
        source_occurrence=occurrence,
        canonical_name=canonical_name,
        display_name=source_name,
        description=None,  # never fabricate a description
        entity=entity,
        field_class=field_class,
        category=category,
        data_type=data_type,
        unit=unit,
        nullable=True,
        required=False,
        valid_min=None,
        valid_max=None,
        range_status=_range_status_for(field_class),
        normalization_strategy=_NORMALIZATION_BY_ENTITY.get(
            entity,
            NormalizationStrategy.RAW_RETAIN,
        ),
        storage_strategy=_STORAGE_BY_ENTITY.get(entity, StorageStrategy.RAW_ONLY),
        aggregation_strategy=_AGGREGATION_BY_CLASS.get(
            field_class,
            AggregationStrategy.UNKNOWN,
        ),
        ml_candidate=(
            MlCandidate.YES
            if field_class
            in {FieldClass.CONTINUOUS_TELEMETRY, FieldClass.COUNTER, FieldClass.ALARM_FLAG}
            else MlCandidate.UNKNOWN
        ),
        prediction_domains=(),
        leakage_risk=LeakageRisk.UNKNOWN,
        availability_semantics=AvailabilitySemantics.UNKNOWN,
        review_status=review,
        notes=note,
        origin="classifier",
    )


def _range_status_for(field_class: FieldClass) -> RangeStatus:
    """Ranges are never invented; only their *applicability* is inferred."""
    if field_class in {
        FieldClass.IDENTIFIER,
        FieldClass.TIMESTAMP,
        FieldClass.STATE,
        FieldClass.ALARM_FLAG,
    }:
        return RangeStatus.NOT_APPLICABLE
    return RangeStatus.UNVERIFIED
