"""Schema compatibility engine (Phase 1B section 23).

Compares an incoming file's raw header against a registered schema version and
returns an explicit report.  It does not decide policy: quarantining is the
orchestrator's call, and Phase 1B deliberately does not quarantine on a merely
*additional* field, because charger firmware gains fields over time and that is
normal evolution rather than corruption.

Field identity is ``(source_name, source_occurrence)`` throughout, so a header
that gains a second copy of an existing name is correctly seen as one added
field rather than as a rename.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from backend.app.models.enums import SchemaCompatibility
from pipelines.profiling.header_parser import RawHeaderParseResult

__all__ = ["RegisteredField", "SchemaComparison", "compare_schema"]


@dataclass(frozen=True, slots=True)
class RegisteredField:
    """A field as recorded on an existing schema version."""

    source_name: str
    source_occurrence: int
    source_position: int
    required: bool = False
    data_type: str | None = None

    @property
    def identity(self) -> tuple[str, int]:
        return (self.source_name, self.source_occurrence)


@dataclass(frozen=True, slots=True)
class SchemaComparison:
    """Explicit, reportable result - never a bare boolean."""

    compatibility: SchemaCompatibility
    matched_count: int = 0
    registered_count: int = 0
    incoming_count: int = 0
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    additional: tuple[str, ...] = ()
    type_changes: tuple[Mapping[str, str], ...] = ()
    reordered: bool = False
    fingerprint_match: bool = False
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_compatible(self) -> bool:
        return self.compatibility.is_compatible

    @property
    def missing_all(self) -> tuple[str, ...]:
        return (*self.missing_required, *self.missing_optional)


def _label(name: str, occurrence: int) -> str:
    """Human-readable field identity that never loses the occurrence number."""
    return name if occurrence == 1 else f"{name} (occurrence {occurrence})"


def compare_schema(
    header: RawHeaderParseResult,
    registered: Sequence[RegisteredField] | None,
    *,
    registered_fingerprint: str | None = None,
    incoming_types: Mapping[tuple[str, int], str] | None = None,
) -> SchemaComparison:
    """Compare an incoming header against a registered schema version."""
    if not registered:
        return SchemaComparison(
            compatibility=SchemaCompatibility.UNKNOWN_SCHEMA,
            incoming_count=header.field_count,
            detail={"reason": "no registered schema version matches this header"},
        )

    if registered_fingerprint and registered_fingerprint == header.header_fingerprint:
        # Identical name, order and multiplicity - by construction nothing can
        # differ structurally.
        return SchemaComparison(
            compatibility=SchemaCompatibility.EXACT_MATCH,
            matched_count=header.field_count,
            registered_count=len(registered),
            incoming_count=header.field_count,
            fingerprint_match=True,
        )

    incoming_index = {(f.source_name, f.source_occurrence): f for f in header.fields}
    registered_index = {f.identity: f for f in registered}

    incoming_keys = set(incoming_index)
    registered_keys = set(registered_index)

    matched = incoming_keys & registered_keys
    added = incoming_keys - registered_keys
    removed = registered_keys - incoming_keys

    missing_required = tuple(
        sorted(_label(*key) for key in removed if registered_index[key].required)
    )
    missing_optional = tuple(
        sorted(_label(*key) for key in removed if not registered_index[key].required)
    )
    additional = tuple(sorted(_label(*key) for key in added))

    type_changes: list[Mapping[str, str]] = []
    if incoming_types:
        for key in sorted(matched):
            declared = registered_index[key].data_type
            incoming = incoming_types.get(key)
            if declared and incoming and declared != incoming:
                type_changes.append(
                    {"field": _label(*key), "registered": declared, "incoming": incoming}
                )

    reordered = any(
        incoming_index[key].position != registered_index[key].source_position for key in matched
    )

    # Precedence: a missing required field is fatal; a type change breaks
    # downstream contracts; losing optional fields is degraded but workable;
    # gaining fields is ordinary firmware evolution.
    if missing_required:
        compatibility = SchemaCompatibility.INCOMPATIBLE_MISSING_REQUIRED
    elif type_changes:
        compatibility = SchemaCompatibility.INCOMPATIBLE_TYPE_CHANGE
    elif missing_optional:
        compatibility = SchemaCompatibility.COMPATIBLE_MISSING_OPTIONAL
    elif additional:
        compatibility = SchemaCompatibility.COMPATIBLE_ADDITION
    elif reordered:
        # Same fields, different order. Position-independent by identity, so
        # this is compatible - but worth surfacing.
        compatibility = SchemaCompatibility.COMPATIBLE_ADDITION
    else:
        compatibility = SchemaCompatibility.EXACT_MATCH

    return SchemaComparison(
        compatibility=compatibility,
        matched_count=len(matched),
        registered_count=len(registered),
        incoming_count=header.field_count,
        missing_required=missing_required,
        missing_optional=missing_optional,
        additional=additional,
        type_changes=tuple(type_changes),
        reordered=reordered,
        fingerprint_match=False,
        detail={
            "matched": len(matched),
            "added": len(added),
            "removed": len(removed),
        },
    )
