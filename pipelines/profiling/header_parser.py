"""Raw CSV header parsing.

This module reads the *original* header line before any DataFrame library sees
the file, and it is the sole authority on field identity.  That ordering matters:
Pandas would silently rewrite the second ``Last Charge Session Stop Reason`` to
``Last Charge Session Stop Reason.1`` and Polars would raise on the duplicate.
Either way the raw identity would be lost or the load would fail.

Field identity here is the pair ``(source_name, source_occurrence)``.  Canonical
names are derived mechanically and deterministically from the source name; a
curated data dictionary may later *override* a canonical name with a better
semantic one, but the mechanical name is always well-defined so that no source
position is ever without an identity.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

__all__ = [
    "HeaderParseError",
    "RawHeaderField",
    "RawHeaderParseResult",
    "canonicalise",
    "parse_header",
    "parse_header_text",
]

#: Separator used when hashing header names.  Chosen because it cannot appear in
#: a CSV header, so the fingerprint is unambiguous with respect to name
#: boundaries and preserves both order and duplication.
_FINGERPRINT_SEPARATOR: Final = "\x1f"

#: Refuse to read an unbounded "header".  A legitimate 449-field header is a few
#: tens of kilobytes; anything vastly larger is malformed or hostile.
MAX_HEADER_BYTES: Final = 4 * 1024 * 1024

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")


class HeaderParseError(RuntimeError):
    """The header could not be read at all - the file cannot be ingested."""


def canonicalise(source_name: str, *, position: int) -> str:
    """Mechanically derive a stable snake_case identifier from a raw header.

    Deterministic and dependency-free: the same raw name always produces the
    same canonical name, independent of what else is in the file.  Uniqueness
    across the whole header is resolved separately by :func:`parse_header_text`,
    because it is a property of the header as a whole rather than of one name.

    >>> canonicalise("Cabinet Temperature", position=0)
    'cabinet_temperature'
    >>> canonicalise("SMR RectifierinternalTemp", position=1)
    'smr_rectifierinternal_temp'
    """
    text = source_name.strip().lstrip("﻿")
    if not text:
        return f"unnamed_field_{position}"

    # Split camelCase and ACRONYMWord boundaries before flattening separators,
    # so "RectifierinternalTemp" becomes two words rather than one run.
    text = _CAMEL_BOUNDARY.sub("_", text)
    text = _ACRONYM_BOUNDARY.sub("_", text)
    text = _NON_ALNUM.sub("_", text)
    text = _MULTI_UNDERSCORE.sub("_", text).strip("_").lower()

    if not text:
        return f"unnamed_field_{position}"
    if text[0].isdigit():
        # Keep the name usable as an identifier in downstream engines.
        text = f"f_{text}"
    return text


@dataclass(frozen=True, slots=True)
class RawHeaderField:
    """One source position, with its raw and canonical identity."""

    position: int
    source_name: str
    source_occurrence: int
    canonical_name: str
    #: True when this raw name appears more than once in the header.
    is_duplicate_name: bool = False
    #: True when the canonical name had to be disambiguated, which means a human
    #: should confirm the semantics rather than trusting the mechanical name.
    requires_review: bool = False
    review_reason: str | None = None

    @property
    def identity(self) -> tuple[str, int]:
        return (self.source_name, self.source_occurrence)


@dataclass(frozen=True, slots=True)
class RawHeaderParseResult:
    """Everything knowable from the header alone."""

    field_count: int
    fields: tuple[RawHeaderField, ...]
    header_fingerprint: str
    #: Raw name -> occurrence count, restricted to names appearing more than once.
    duplicate_names: dict[str, int] = field(default_factory=dict)
    empty_name_count: int = 0
    has_bom: bool = False
    encoding: str = "utf-8"

    @property
    def duplicate_header_count(self) -> int:
        """Number of *distinct* raw names that repeat."""
        return len(self.duplicate_names)

    @property
    def duplicated_position_count(self) -> int:
        """Number of source positions involved in a duplicate name."""
        return sum(self.duplicate_names.values())

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(f.source_name for f in self.fields)

    @property
    def canonical_names(self) -> tuple[str, ...]:
        return tuple(f.canonical_name for f in self.fields)

    def by_identity(self, source_name: str, occurrence: int = 1) -> RawHeaderField | None:
        for item in self.fields:
            if item.source_name == source_name and item.source_occurrence == occurrence:
                return item
        return None

    def review_required_fields(self) -> tuple[RawHeaderField, ...]:
        return tuple(f for f in self.fields if f.requires_review)


def compute_fingerprint(source_names: list[str]) -> str:
    """SHA256 over the ordered, duplicate-preserving list of raw names.

    Two files share a fingerprint exactly when their headers are identical in
    name, order and multiplicity - which is precisely the condition under which
    one field dictionary applies to both.
    """
    joined = _FINGERPRINT_SEPARATOR.join(source_names)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def parse_header_text(
    header_row: list[str], *, encoding: str = "utf-8", has_bom: bool = False
) -> RawHeaderParseResult:
    """Build the parse result from an already-split header row."""
    if not header_row:
        raise HeaderParseError("CSV header row is empty")

    cleaned: list[str] = []
    empty_name_count = 0
    for index, raw in enumerate(header_row):
        name = raw.strip()
        if index == 0:
            name = name.lstrip("﻿")
        if not name:
            empty_name_count += 1
        cleaned.append(name)

    name_totals = Counter(cleaned)
    duplicate_names = {name: count for name, count in name_totals.items() if count > 1}

    seen: Counter[str] = Counter()
    used_canonical: set[str] = set()
    fields: list[RawHeaderField] = []

    for position, source_name in enumerate(cleaned):
        seen[source_name] += 1
        occurrence = seen[source_name]
        is_duplicate = name_totals[source_name] > 1

        base = canonicalise(source_name, position=position)
        canonical = base
        requires_review = False
        reason: str | None = None

        if is_duplicate and occurrence > 1:
            # Controlled temporary canonical form.  The raw identity is fully
            # preserved by (source_name, source_occurrence); this suffix exists
            # only so the canonical namespace stays unique until a domain expert
            # tells us what actually distinguishes the two columns.
            canonical = f"{base}_occurrence_{occurrence}"
            requires_review = True
            reason = (
                f"Raw header {source_name!r} appears {name_totals[source_name]} times; "
                "occurrences are not yet semantically distinguished"
            )

        if canonical in used_canonical:
            # Two *different* raw names collapsed onto the same canonical form
            # (e.g. "Temp (C)" and "Temp C").  Disambiguate positionally and
            # flag it - guessing which one is which would be fabrication.
            suffix = 2
            while f"{canonical}_{suffix}" in used_canonical:
                suffix += 1
            collided = canonical
            canonical = f"{canonical}_{suffix}"
            requires_review = True
            reason = (
                f"Canonical name {collided!r} collides with a different raw header; "
                "disambiguated by position"
            )

        used_canonical.add(canonical)
        fields.append(
            RawHeaderField(
                position=position,
                source_name=source_name,
                source_occurrence=occurrence,
                canonical_name=canonical,
                is_duplicate_name=is_duplicate,
                requires_review=requires_review,
                review_reason=reason,
            )
        )

    return RawHeaderParseResult(
        field_count=len(fields),
        fields=tuple(fields),
        header_fingerprint=compute_fingerprint(cleaned),
        duplicate_names=duplicate_names,
        empty_name_count=empty_name_count,
        has_bom=has_bom,
        encoding=encoding,
    )


def _detect_encoding(path: Path) -> tuple[str, bool]:
    """Return (encoding, has_bom).

    We never *trust* the file, so decoding falls back to latin-1, which cannot
    raise.  Mojibake is preferable to an unreadable header, and the raw bytes
    remain immutable in the Bronze layer regardless.
    """
    with path.open("rb") as handle:
        prefix = handle.read(4)
    if prefix.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", True
    return "utf-8", False


def parse_header(path: Path, *, delimiter: str = ",") -> RawHeaderParseResult:
    """Read and parse only the header line of a CSV file.

    The full file is never loaded.  ``csv.reader`` is used rather than a naive
    ``split(",")`` so that quoted headers containing commas or newlines are
    handled correctly.
    """
    if not path.exists():
        raise HeaderParseError(f"File does not exist: {path.name}")

    encoding, has_bom = _detect_encoding(path)

    for candidate in (encoding, "latin-1"):
        try:
            with path.open("r", encoding=candidate, newline="") as handle:
                reader = csv.reader(handle, delimiter=delimiter)
                try:
                    row = next(reader)
                except StopIteration as exc:
                    raise HeaderParseError("File contains no header row") from exc
                consumed = sum(len(cell) for cell in row)
                if consumed > MAX_HEADER_BYTES:
                    raise HeaderParseError(
                        f"Header exceeds the {MAX_HEADER_BYTES} byte safety limit"
                    )
                return parse_header_text(row, encoding=candidate, has_bom=has_bom)
        except UnicodeDecodeError:
            continue

    raise HeaderParseError("Header could not be decoded with any supported encoding")
