"""Silver telemetry repository for persistence, idempotency, and queries (Phase 6)."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from backend.app.models.silver_telemetry import (
    SilverAlarmObservation,
    SilverChargerTelemetry,
    SilverCommunicationObservation,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverContactorObservation,
    SilverLifecycleCounterObservation,
    SilverNormalizationRun,
    SilverObservationProvenance,
    SilverRectifierTelemetry,
    SilverSessionObservation,
    SilverSiteMetadata,
    SilverSmrTelemetry,
)
from backend.app.repositories.base import Repository

__all__ = ["SilverRepository"]

_ALL_SILVER_MODELS = (
    SilverSiteMetadata,
    SilverChargerTelemetry,
    SilverConnectorTelemetry,
    SilverRectifierTelemetry,
    SilverSmrTelemetry,
    SilverContactorObservation,
    SilverAlarmObservation,
    SilverSessionObservation,
    SilverLifecycleCounterObservation,
    SilverCommunicationObservation,
    SilverConfigurationSnapshot,
)


class SilverRepository(Repository):
    """Encapsulates all Silver table persistence, idempotency, and retrieval."""

    async def delete_for_frames(self, frame_ids: list[UUID]) -> None:
        """Idempotently delete any existing Silver records and provenance for frames."""
        if not frame_ids:
            return

        # Delete from provenance first
        await self.session.execute(
            sa.delete(SilverObservationProvenance).where(
                SilverObservationProvenance.frame_id.in_(frame_ids)
            )
        )

        # Delete from all 11 domain tables
        for model in _ALL_SILVER_MODELS:
            await self.session.execute(sa.delete(model).where(model.frame_id.in_(frame_ids)))

    async def create_normalization_run(
        self,
        *,
        file_id: UUID,
        status: str = "STARTED",
    ) -> SilverNormalizationRun:
        """Create a new normalization run record."""
        run = SilverNormalizationRun(
            file_id=file_id,
            status=status,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_normalization_run(self, file_id: UUID) -> SilverNormalizationRun | None:
        stmt = (
            sa.select(SilverNormalizationRun)
            .where(SilverNormalizationRun.file_id == file_id)
            .order_by(SilverNormalizationRun.started_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def insert_records(self, records: list[Any]) -> None:
        """Insert Silver records into the session."""
        if records:
            self.session.add_all(records)
            await self.session.flush()

    async def insert_provenance(
        self, provenance_records: list[SilverObservationProvenance]
    ) -> None:
        """Insert provenance lineage records into the session."""
        if provenance_records:
            self.session.add_all(provenance_records)
            await self.session.flush()

    async def get_latest_charger_telemetry(self, charger_id: str) -> SilverChargerTelemetry | None:
        """Query the latest cabinet telemetry observation for a charger."""
        stmt = (
            sa.select(SilverChargerTelemetry)
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.desc(),
                SilverChargerTelemetry.frame_sequence.desc(),
            )
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_charger_history(
        self,
        charger_id: str,
        *,
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        limit: int = 100,
    ) -> list[SilverChargerTelemetry]:
        """Query chronological cabinet telemetry for a charger."""
        stmt = (
            sa.select(SilverChargerTelemetry)
            .where(SilverChargerTelemetry.charger_id == charger_id)
            .order_by(
                SilverChargerTelemetry.event_time.asc(),
                SilverChargerTelemetry.frame_sequence.asc(),
            )
            .limit(limit)
        )
        if date_from:
            stmt = stmt.where(SilverChargerTelemetry.event_time >= date_from)
        if date_to:
            stmt = stmt.where(SilverChargerTelemetry.event_time <= date_to)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_connectors_for_charger(
        self, charger_id: str, *, limit: int = 100
    ) -> list[SilverConnectorTelemetry]:
        stmt = (
            sa.select(SilverConnectorTelemetry)
            .where(SilverConnectorTelemetry.charger_id == charger_id)
            .order_by(
                SilverConnectorTelemetry.event_time.desc(),
                SilverConnectorTelemetry.connector_id.asc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_smrs_for_charger(
        self, charger_id: str, *, limit: int = 100
    ) -> list[SilverSmrTelemetry]:
        stmt = (
            sa.select(SilverSmrTelemetry)
            .where(SilverSmrTelemetry.charger_id == charger_id)
            .order_by(
                SilverSmrTelemetry.event_time.desc(),
                SilverSmrTelemetry.smr_id.asc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_rectifiers_for_charger(
        self, charger_id: str, *, limit: int = 100
    ) -> list[SilverRectifierTelemetry]:
        stmt = (
            sa.select(SilverRectifierTelemetry)
            .where(SilverRectifierTelemetry.charger_id == charger_id)
            .order_by(
                SilverRectifierTelemetry.event_time.desc(),
                SilverRectifierTelemetry.rectifier_id.asc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
