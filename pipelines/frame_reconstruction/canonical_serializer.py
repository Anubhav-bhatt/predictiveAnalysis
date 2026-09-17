"""Schema-aware canonical serialization (Phase 1D sections 12, 13).

Fingerprints are only as trustworthy as the text they hash, so this module is the
single place that decides what "the same value" means. Three rules govern it:

**Never hash a Python repr.** ``repr`` is not a stable contract - it varies with
type, version and locale. Every value is rendered through an explicit rule.

**Nulls are one token.** The source expresses absence as an empty field, a
whitespace-only field, or a configured null literal. All of them canonicalise to a
single sentinel, so two rows that both mean "no reading" fingerprint identically.
Crucially, that sentinel is *not* ``0`` - a missing sensor and a zero reading are
different observations (Phase 1B missing-value semantics).

**Numeric equality follows the declared type.** Whether ``1`` and ``1.0`` are the
same value is a schema question, not a string question. For a field the dictionary
types as numeric they canonicalise identically; for a STRING field they do not,
because there the characters *are* the value.

What is deliberately excluded from every fingerprint: database ids, ingestion
timestamps, storage references, file ids and quality-issue ids. Identical telemetry
arriving in a second overlapping file must fingerprint identically, and it cannot
do that if the file's identity is baked in (section 13).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from backend.app.models.enums import CanonicalDataType

__all__ = [
    "CanonicalSerializer",
    "FieldTypeMap",
    "NULL_TOKEN",
    "canonical_number",
]

#: Single canonical rendering of absence. Chosen as a token that cannot collide
#: with a legitimate source value.
NULL_TOKEN = "\x00NULL"  # noqa: S105 - a serialization sentinel, not a credential

#: Unit separator between values, and record separator between fields. Both are
#: control characters that cannot appear in the CSV's text fields.
_VALUE_SEP = "\x1f"
_FIELD_SEP = "\x1e"

#: Field name -> semantic type, from the Phase 1B dictionary.
FieldTypeMap = Mapping[str, CanonicalDataType]


def canonical_number(raw: str) -> str | None:
    """Render a numeric literal in one canonical form, or None if not numeric.

    Uses Decimal rather than float so that values which are exact in the source
    text stay exact: ``float("0.1")`` introduces representation error that could
    make two identical source strings hash differently after arithmetic.

    ``1``, ``1.0``, ``1.000`` and ``+1`` all collapse to ``1``; ``-0`` collapses to
    ``0`` so a signed zero cannot masquerade as a distinct reading.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if value.is_nan() or value.is_infinite():
        return None
    if value == 0:
        return "0"
    # normalize() strips trailing zeros; the exponent dance turns 1E+3 back into
    # 1000 so the canonical form stays human-readable and comparable.
    normalized = value.normalize()
    sign, digits, exponent = normalized.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    text_out = format(normalized, "f")
    if "." in text_out:
        text_out = text_out.rstrip("0").rstrip(".")
    return text_out or "0"


@dataclass(frozen=True, slots=True)
class CanonicalSerializer:
    """Turns raw source text into deterministic canonical text.

    ``null_literals`` are the configured source spellings of absence (Phase 1B
    missing-value contract), compared case-insensitively after stripping.
    """

    field_types: FieldTypeMap
    null_literals: frozenset[str] = frozenset()
    #: Fields excluded from every fingerprint - internal metadata only.
    excluded_fields: frozenset[str] = frozenset()

    def canonical_value(self, field_name: str, raw: object) -> str:
        """Canonicalise one field value."""
        if raw is None:
            return NULL_TOKEN

        if isinstance(raw, float) and math.isnan(raw):
            return NULL_TOKEN

        text = str(raw).strip()
        if not text:
            return NULL_TOKEN
        if text.casefold() in self.null_literals:
            return NULL_TOKEN

        declared = self.field_types.get(field_name, CanonicalDataType.UNKNOWN)

        if declared is CanonicalDataType.BOOLEAN:
            return self._canonical_boolean(text)

        if declared.is_numeric:
            # A numeric field holding non-numeric text keeps its text form: the
            # value is preserved for reporting rather than coerced to null here.
            # Type-conversion policy is Phase 1E's decision, not the
            # fingerprinter's.
            return canonical_number(text) or text

        if declared in {
            CanonicalDataType.STRING,
            CanonicalDataType.ENUM,
            CanonicalDataType.IDENTIFIER,
            CanonicalDataType.DATETIME,
            CanonicalDataType.DURATION,
        }:
            # Text fields keep their characters. Whitespace is already stripped;
            # case is preserved because "Available" and "AVAILABLE" may be
            # genuinely different source states until Phase 1E maps them.
            return text

        # UNKNOWN type: prefer a numeric reading when the text clearly is one, so
        # 1 and 1.0 from an unclassified column still compare equal.
        return canonical_number(text) or text

    @staticmethod
    def _canonical_boolean(text: str) -> str:
        lowered = text.casefold()
        if lowered in {"1", "true", "t", "yes", "y", "on"}:
            return "TRUE"
        if lowered in {"0", "false", "f", "no", "n", "off"}:
            return "FALSE"
        return text

    def canonical_row(self, field_names: Sequence[str], values: Sequence[object]) -> str:
        """Canonical text for one raw row.

        Field names are included alongside values so that a schema change which
        reorders columns cannot make two different rows collide.
        """
        parts: list[str] = []
        for name, value in zip(field_names, values, strict=False):
            if name in self.excluded_fields:
                continue
            parts.append(f"{name}={self.canonical_value(name, value)}")
        return _VALUE_SEP.join(parts)

    def row_fingerprint(self, field_names: Sequence[str], values: Sequence[object]) -> str:
        return hashlib.sha256(self.canonical_row(field_names, values).encode("utf-8")).hexdigest()

    @staticmethod
    def frame_fingerprint(position_fingerprints: Mapping[str, str]) -> str:
        """Fingerprint a frame from its positions' row fingerprints.

        Keyed by logical position and sorted, so the frame's identity does not
        depend on the order its rows happened to appear in the file. Two frames
        with the same payload therefore match even when their rows were
        interleaved differently (section 14).
        """
        payload = _FIELD_SEP.join(
            f"{position}={fingerprint}"
            for position, fingerprint in sorted(position_fingerprints.items())
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
