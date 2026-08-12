"""Schema-version and field-definition persistence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from backend.app.models.enums import (
    FieldCategory,
    FieldClass,
    FieldEntity,
    MlCandidate,
    ReviewStatus,
    StorageStrategy,
)
from backend.app.models.field_definition import (
    FieldAllowedValue,
    FieldDefinition,
    FieldPredictionDomain,
    FieldSentinelValue,
)
from backend.app.models.schema_version import SchemaVersion
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["SchemaRepository"]


class SchemaRepository(Repository):
    async def get_by_fingerprint(self, fingerprint: str) -> SchemaVersion | None:
        stmt = sa.select(SchemaVersion).where(SchemaVersion.header_fingerprint == fingerprint)
        return (await self.session.execute(stmt)).scalars().first()

    async def get(self, schema_id: UUID) -> SchemaVersion | None:
        return await self.session.get(SchemaVersion, schema_id)

    async def next_version_number(self) -> int:
        current = (
            await self.session.execute(sa.select(sa.func.max(SchemaVersion.version)))
        ).scalar()
        return int(current or 0) + 1

    async def add_version(self, version: SchemaVersion) -> SchemaVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def bulk_insert_fields(
        self,
        schema_version_id: UUID,
        field_rows: Sequence[dict[str, Any]],
        sentinel_rows: Sequence[tuple[int, str, str | None]],
        allowed_rows: Sequence[tuple[int, str, str | None]],
        domain_rows: Sequence[tuple[int, str]],
    ) -> None:
        """Insert a whole schema's fields in a handful of statements.

        449 fields must never become 449 round-trips (section 40). The child
        rows are keyed by source position so their parent ids can be resolved
        without re-querying.
        """
        if not field_rows:
            return

        ids_by_position: dict[int, UUID] = {}
        prepared: list[dict[str, Any]] = []
        for row in field_rows:
            field_id = uuid4()
            ids_by_position[int(row["source_position"])] = field_id
            prepared.append({**row, "id": field_id, "schema_version_id": schema_version_id})

        await self.session.execute(sa.insert(FieldDefinition), prepared)

        if sentinel_rows:
            await self.session.execute(
                sa.insert(FieldSentinelValue),
                [
                    {
                        "id": uuid4(),
                        "field_definition_id": ids_by_position[position],
                        "value": value,
                        "meaning": meaning,
                    }
                    for position, value, meaning in sentinel_rows
                    if position in ids_by_position
                ],
            )
        if allowed_rows:
            await self.session.execute(
                sa.insert(FieldAllowedValue),
                [
                    {
                        "id": uuid4(),
                        "field_definition_id": ids_by_position[position],
                        "value": value,
                        "meaning": meaning,
                    }
                    for position, value, meaning in allowed_rows
                    if position in ids_by_position
                ],
            )
        if domain_rows:
            await self.session.execute(
                sa.insert(FieldPredictionDomain),
                [
                    {
                        "id": uuid4(),
                        "field_definition_id": ids_by_position[position],
                        "domain": domain,
                    }
                    for position, domain in domain_rows
                    if position in ids_by_position
                ],
            )

    async def list_versions(self, request: PageRequest) -> Page[SchemaVersion]:
        stmt = sa.select(SchemaVersion).order_by(SchemaVersion.version.desc())
        return await paginate(self.session, stmt, request)

    async def fields_for_version(self, schema_version_id: UUID) -> Sequence[FieldDefinition]:
        stmt = (
            sa.select(FieldDefinition)
            .where(FieldDefinition.schema_version_id == schema_version_id)
            .order_by(FieldDefinition.source_position)
            .options(
                selectinload(FieldDefinition.sentinel_values),
                selectinload(FieldDefinition.allowed_values),
                selectinload(FieldDefinition.prediction_domains),
            )
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def get_field(self, field_id: UUID) -> FieldDefinition | None:
        stmt = (
            sa.select(FieldDefinition)
            .where(FieldDefinition.id == field_id)
            .options(
                selectinload(FieldDefinition.sentinel_values),
                selectinload(FieldDefinition.allowed_values),
                selectinload(FieldDefinition.prediction_domains),
            )
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_fields(
        self,
        request: PageRequest,
        *,
        schema_version_id: UUID | None = None,
        entity: FieldEntity | None = None,
        category: FieldCategory | None = None,
        field_class: FieldClass | None = None,
        review_status: ReviewStatus | None = None,
        ml_candidate: MlCandidate | None = None,
        storage_strategy: StorageStrategy | None = None,
        search: str | None = None,
    ) -> Page[FieldDefinition]:
        stmt = sa.select(FieldDefinition).order_by(FieldDefinition.source_position)
        filters = [
            (FieldDefinition.schema_version_id == schema_version_id, schema_version_id),
            (FieldDefinition.entity == entity, entity),
            (FieldDefinition.category == category, category),
            (FieldDefinition.field_class == field_class, field_class),
            (FieldDefinition.review_status == review_status, review_status),
            (FieldDefinition.ml_candidate == ml_candidate, ml_candidate),
            (FieldDefinition.storage_strategy == storage_strategy, storage_strategy),
        ]
        for clause, value in filters:
            if value is not None:
                stmt = stmt.where(clause)
        if search:
            pattern = f"%{search.lower()}%"
            stmt = stmt.where(
                sa.or_(
                    sa.func.lower(FieldDefinition.source_name).like(pattern),
                    sa.func.lower(FieldDefinition.canonical_name).like(pattern),
                )
            )
        return await paginate(self.session, stmt, request)

    async def field_breakdown(self, schema_version_id: UUID) -> dict[str, dict[str, int]]:
        """Grouped counts for the coverage visualisation (section 37).

        Four aggregated queries rather than pulling 449 rows into Python.
        """
        breakdown: dict[str, dict[str, int]] = {}
        for label, column in (
            ("entity", FieldDefinition.entity),
            ("category", FieldDefinition.category),
            ("field_class", FieldDefinition.field_class),
            ("review_status", FieldDefinition.review_status),
            ("storage_strategy", FieldDefinition.storage_strategy),
            ("ml_candidate", FieldDefinition.ml_candidate),
        ):
            rows = await self.session.execute(
                sa.select(column, sa.func.count())
                .where(FieldDefinition.schema_version_id == schema_version_id)
                .group_by(column)
            )
            breakdown[label] = {str(key.value): int(count) for key, count in rows.all()}
        return breakdown
