"""Registry coverage validation (Phase 1B sections 20 and 21).

Coverage answers one question: does every raw source position have a definition?
For the known schema that means all 449 positions, with the two occurrences of
``Last Charge Session Stop Reason`` counted separately.

A schema is only ``COMPLETE`` when nothing is unmapped.  Note that "mapped" here
means *curated* - resolved by an explicit dictionary entry or a pattern rule.
Positions that only the classifier could reach are counted as unmapped for the
purpose of production-readiness, because an inferred definition is not a
contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.app.models.enums import ReviewStatus, SchemaCoverageStatus
from pipelines.profiling.header_parser import RawHeaderParseResult
from pipelines.validation.dictionary import ResolvedField

__all__ = ["CoverageReport", "FieldInventory", "build_coverage_report", "build_inventory"]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Whether the dictionary fully covers a schema."""

    source_positions: int
    mapped: int
    unmapped: int
    duplicate_names_handled: int
    duplicate_positions: int

    verified: int = 0
    engineer_reviewed: int = 0
    auto_classified: int = 0
    domain_review_required: int = 0

    unmapped_examples: tuple[str, ...] = ()

    @property
    def status(self) -> SchemaCoverageStatus:
        return (
            SchemaCoverageStatus.COMPLETE if self.unmapped == 0 else SchemaCoverageStatus.INCOMPLETE
        )

    @property
    def coverage_percentage(self) -> float:
        if self.source_positions <= 0:
            return 0.0
        return round(100.0 * self.mapped / self.source_positions, 3)

    def render(self) -> str:
        """The section 21 summary block."""
        return (
            f"Source positions:      {self.source_positions:>6}\n"
            f"Mapped:                {self.mapped:>6}\n"
            f"Unmapped:              {self.unmapped:>6}\n"
            f"Duplicate names:       {self.duplicate_names_handled:>6} "
            f"({self.duplicate_positions} positions)\n"
            f"Verified:              {self.verified:>6}\n"
            f"Engineer reviewed:     {self.engineer_reviewed:>6}\n"
            f"Auto classified:       {self.auto_classified:>6}\n"
            f"Domain review needed:  {self.domain_review_required:>6}\n"
            f"Status:                {self.status.value}"
        )


def build_coverage_report(
    header: RawHeaderParseResult,
    resolved: Sequence[ResolvedField],
) -> CoverageReport:
    """Summarise dictionary coverage of every source position."""
    mapped = [r for r in resolved if r.is_dictionary_mapped]
    unmapped = [r for r in resolved if not r.is_dictionary_mapped]

    counts: dict[ReviewStatus, int] = dict.fromkeys(ReviewStatus, 0)
    for item in resolved:
        counts[item.spec.review_status] += 1

    return CoverageReport(
        source_positions=header.field_count,
        mapped=len(mapped),
        unmapped=len(unmapped),
        duplicate_names_handled=header.duplicate_header_count,
        duplicate_positions=header.duplicated_position_count,
        verified=counts[ReviewStatus.VERIFIED],
        engineer_reviewed=counts[ReviewStatus.ENGINEER_REVIEWED],
        auto_classified=counts[ReviewStatus.AUTO_CLASSIFIED],
        domain_review_required=counts[ReviewStatus.DOMAIN_REVIEW_REQUIRED],
        unmapped_examples=tuple(r.spec.source_name for r in unmapped[:20]),
    )


@dataclass(frozen=True, slots=True)
class FieldInventory:
    """Output of ``python -m pipelines.profiling inventory`` (section 20)."""

    total_fields: int
    registered_fields: int
    unregistered_fields: int
    duplicate_headers: int
    unknown_fields: tuple[str, ...] = ()
    missing_expected_fields: tuple[str, ...] = ()
    additional_fields: tuple[str, ...] = ()
    coverage: CoverageReport | None = field(default=None)

    def render(self) -> str:
        lines = [
            f"Total fields:            {self.total_fields}",
            f"Registered fields:       {self.registered_fields}",
            f"Unregistered fields:     {self.unregistered_fields}",
            f"Duplicate headers:       {self.duplicate_headers}",
            f"Unknown fields:          {len(self.unknown_fields)}",
            f"Missing expected fields: {len(self.missing_expected_fields)}",
            f"Additional fields:       {len(self.additional_fields)}",
        ]
        if self.unknown_fields:
            lines.append(f"  unknown examples:      {', '.join(self.unknown_fields[:5])}")
        if self.missing_expected_fields:
            lines.append(f"  missing examples:      {', '.join(self.missing_expected_fields[:5])}")
        if self.additional_fields:
            lines.append(f"  additional examples:   {', '.join(self.additional_fields[:5])}")
        return "\n".join(lines)


def build_inventory(
    header: RawHeaderParseResult,
    resolved: Sequence[ResolvedField],
    *,
    missing_expected: Sequence[str] = (),
    additional: Sequence[str] = (),
) -> FieldInventory:
    """Compare the raw header against the registered dictionary."""
    coverage = build_coverage_report(header, resolved)
    unknown = tuple(r.spec.source_name for r in resolved if not r.is_dictionary_mapped)
    return FieldInventory(
        total_fields=header.field_count,
        registered_fields=coverage.mapped,
        unregistered_fields=coverage.unmapped,
        duplicate_headers=header.duplicate_header_count,
        unknown_fields=unknown,
        missing_expected_fields=tuple(missing_expected),
        additional_fields=tuple(additional),
        coverage=coverage,
    )
