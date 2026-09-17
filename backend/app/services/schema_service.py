"""Schema registration and compatibility (Phase 1A section 8, Phase 1B 21-23).

A schema version is created the first time a given header fingerprint is seen,
and its field definitions are materialised from the data dictionary at that
moment. Later files with the same fingerprint reuse the version rather than
re-deriving it.

Pipelines stay pure: this service is where dictionary resolution meets the
database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.models.enums import SchemaCoverageStatus, SchemaVersionStatus
from backend.app.models.schema_version import SchemaVersion
from backend.app.repositories.base import PageRequest
from backend.app.repositories.schema import SchemaRepository
from pipelines.profiling.header_parser import RawHeaderParseResult
from pipelines.validation.compatibility import (
    RegisteredField,
    SchemaComparison,
    compare_schema,
)
from pipelines.validation.coverage import CoverageReport, build_coverage_report
from pipelines.validation.dictionary import DictionaryRegistry, ResolvedField

__all__ = ["SchemaResolution", "SchemaService"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SchemaResolution:
    schema_version: SchemaVersion
    resolved_fields: Sequence[ResolvedField]
    comparison: SchemaComparison
    coverage: CoverageReport
    created: bool


def _field_rows(
    resolved: Sequence[ResolvedField],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, str, str | None]],
    list[tuple[int, str, str | None]],
    list[tuple[int, str]],
]:
    """Flatten resolved dictionary entries into bulk-insertable rows."""
    fields: list[dict[str, Any]] = []
    sentinels: list[tuple[int, str, str | None]] = []
    allowed: list[tuple[int, str, str | None]] = []
    domains: list[tuple[int, str]] = []

    for item in resolved:
        spec = item.spec
        position = item.source_position
        fields.append(
            {
                "source_name": spec.source_name,
                "source_occurrence": spec.source_occurrence or 1,
                "source_position": position,
                "canonical_name": spec.canonical_name,
                "display_name": spec.display_name,
                "description": spec.description,
                "entity": spec.entity,
                "field_class": spec.field_class,
                "category": spec.category,
                "sub_category": spec.sub_category,
                "data_type": spec.data_type,
                "unit": spec.unit,
                "nullable": spec.nullable,
                "required": spec.required,
                "valid_min": spec.valid_min,
                "valid_max": spec.valid_max,
                "range_status": spec.range_status,
                "normalization_strategy": spec.normalization_strategy,
                "storage_strategy": spec.storage_strategy,
                "aggregation_strategy": spec.aggregation_strategy,
                "ml_candidate": spec.ml_candidate,
                "leakage_risk": spec.leakage_risk,
                "availability_semantics": spec.availability_semantics,
                "review_status": spec.review_status,
                "deprecated": spec.deprecated,
                "notes": spec.notes,
                "is_dictionary_mapped": item.is_dictionary_mapped,
                "dictionary_source": spec.origin,
            }
        )
        sentinels.extend((position, s.value, s.meaning) for s in spec.sentinel_values)
        allowed.extend((position, a.value, a.meaning) for a in spec.allowed_values)
        domains.extend((position, d.value) for d in spec.prediction_domains)

    return fields, sentinels, allowed, domains


class SchemaService:
    def __init__(self, repository: SchemaRepository, registry: DictionaryRegistry) -> None:
        self._repo = repository
        self._registry = registry

    async def resolve(self, header: RawHeaderParseResult) -> SchemaResolution:
        """Find or create the schema version for a header, with full coverage."""
        resolved = list(
            self._registry.resolve_all(
                (f.source_name, f.source_occurrence, f.position, f.canonical_name)
                for f in header.fields
            )
        )
        coverage = build_coverage_report(header, resolved)

        existing = await self._repo.get_by_fingerprint(header.header_fingerprint)
        if existing is not None:
            registered = [
                RegisteredField(
                    source_name=f.source_name,
                    source_occurrence=f.source_occurrence,
                    source_position=f.source_position,
                    required=f.required,
                    data_type=f.data_type.value,
                )
                for f in await self._repo.fields_for_version(existing.id)
            ]
            comparison = compare_schema(
                header, registered, registered_fingerprint=existing.header_fingerprint
            )
            return SchemaResolution(existing, resolved, comparison, coverage, created=False)

        # New fingerprint. Compare against the current ACTIVE version so drift
        # is reported rather than silently accepted as a brand-new schema.
        comparison = await self._compare_with_active(header)

        version_number = await self._repo.next_version_number()
        schema_version = SchemaVersion(
            version=version_number,
            name=f"{self._registry.name}_v{version_number}",
            header_fingerprint=header.header_fingerprint,
            field_count=header.field_count,
            duplicate_header_count=header.duplicate_header_count,
            status=SchemaVersionStatus.ACTIVE,
            coverage_status=coverage.status,
            mapped_field_count=coverage.mapped,
            unmapped_field_count=coverage.unmapped,
            dictionary_revision=self._registry.revision,
            description=(
                f"Auto-registered from a {header.field_count}-field header with "
                f"{header.duplicate_header_count} duplicated name(s)."
            ),
        )
        await self._repo.add_version(schema_version)

        fields, sentinels, allowed, domains = _field_rows(resolved)
        await self._repo.bulk_insert_fields(schema_version.id, fields, sentinels, allowed, domains)

        logger.info(
            "schema.registered",
            schema_version=schema_version.version,
            field_count=header.field_count,
            mapped=coverage.mapped,
            unmapped=coverage.unmapped,
            coverage_status=coverage.status.value,
            duplicate_headers=header.duplicate_header_count,
        )
        return SchemaResolution(schema_version, resolved, comparison, coverage, created=True)

    async def _compare_with_active(self, header: RawHeaderParseResult) -> SchemaComparison:
        """Compare an unseen header against the newest registered version."""
        page = await self._repo.list_versions(PageRequest(page=1, page_size=1))
        if not page.items:
            return compare_schema(header, None)
        newest = page.items[0]
        registered = [
            RegisteredField(
                source_name=f.source_name,
                source_occurrence=f.source_occurrence,
                source_position=f.source_position,
                required=f.required,
                data_type=f.data_type.value,
            )
            for f in await self._repo.fields_for_version(newest.id)
        ]
        return compare_schema(header, registered, registered_fingerprint=newest.header_fingerprint)

    async def refresh_coverage(
        self, schema_version: SchemaVersion, coverage: CoverageReport
    ) -> None:
        schema_version.coverage_status = coverage.status
        schema_version.mapped_field_count = coverage.mapped
        schema_version.unmapped_field_count = coverage.unmapped
        if coverage.status is SchemaCoverageStatus.INCOMPLETE:
            logger.warning(
                "schema.coverage.incomplete",
                schema_version=schema_version.version,
                unmapped=coverage.unmapped,
            )
