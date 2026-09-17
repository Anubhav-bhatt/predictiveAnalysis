"""Integration tests for Silver telemetry normalization pipeline (Phase 6)."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.enums import DuplicateClassification, FileStatus, FrameStatus, SourceType
from backend.app.models.silver_telemetry import (
    SilverChargerTelemetry,
    SilverConnectorTelemetry,
    SilverObservationProvenance,
    SilverSessionObservation,
    SilverSiteMetadata,
    SilverSmrTelemetry,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_frame import (
    TelemetryFrameRow,
    TelemetryFrameSource,
    TelemetrySourceFrame,
)
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import USABLE_FILE_STATES, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.silver import SilverRepository
from backend.app.services.normalization_service import NormalizationService
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry

pytestmark = pytest.mark.integration


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def test_silver_usable_file_states() -> None:
    """Verify NORMALIZING, NORMALIZED, NORMALIZED_WITH_WARNINGS are usable for reconciliation."""
    assert FileStatus.NORMALIZING in USABLE_FILE_STATES
    assert FileStatus.NORMALIZED in USABLE_FILE_STATES
    assert FileStatus.NORMALIZED_WITH_WARNINGS in USABLE_FILE_STATES


async def test_silver_normalization_pipeline_end_to_end(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Test full file normalization into typed Silver tables with sentinels and provenance."""
    charger_id = "CH_TEST_001"
    event_time = dt.datetime(2026, 9, 16, 11, 36, 1, tzinfo=dt.UTC)
    file_id = uuid4()

    # 1. Create TelemetryFile
    csv_content = (
        "Charger Id,OCPP Id,Charging Station,Logged At Time,L1-N Voltage,"
        "Connector No,Gun Temp Dc+,Rectifier Number,Smr No.,SMR DcDc Temperature,"
        "Last Charge Session Stop Reason\n"
        f"{charger_id},OCPP_1,Station Alpha,16-09-2026 17:06:01,230.5,"
        "1,999.0,1,1,-150.0,EmergencyStop\n"
    )

    async def chunks() -> AsyncIterator[bytes]:
        yield csv_content.encode("utf-8")

    stored = await storage.store(
        chunks(),
        file_id=file_id,
        original_filename="test_silver.csv",
    )

    telemetry_file = TelemetryFile(
        id=file_id,
        original_filename="test_silver.csv",
        file_size_bytes=stored.size_bytes,
        source_type=SourceType.FILESYSTEM,
        source_reference="test_silver.csv",
        sha256=stored.sha256,
        status=FileStatus.FRAMES_RECONSTRUCTED,
        storage_reference=stored.storage_reference,
    )
    session.add(telemetry_file)
    await session.flush()

    # 2. Create Reconstructed TelemetrySourceFrame
    frame_id = uuid4()
    frame = TelemetrySourceFrame(
        id=frame_id,
        charger_id=charger_id,
        event_time=event_time,
        business_date=dt.date(2026, 9, 16),
        frame_sequence=0,
        frame_fingerprint="fp123456",
        frame_status=FrameStatus.COMPLETE,
        duplicate_classification=DuplicateClassification.UNIQUE,
        reconstruction_version="v1",
        expected_position_count=11,
        observed_position_count=11,
    )
    session.add(frame)
    await session.flush()

    frame_source = TelemetryFrameSource(
        frame_id=frame_id,
        telemetry_file_id=file_id,
        first_source_row=1,
        last_source_row=1,
        row_count=1,
        is_primary_source=True,
    )
    session.add(frame_source)

    frame_row = TelemetryFrameRow(
        frame_id=frame_id,
        telemetry_file_id=file_id,
        source_row_number=1,
        connector_id="1",
        smr_id="1",
        logical_position="C1/S1",
        row_fingerprint="rowfp123",
    )
    session.add(frame_row)
    await session.flush()

    # 3. Execute Normalization Service
    service = NormalizationService(
        silver_repo=SilverRepository(session),
        frame_repo=FrameRepository(session),
        file_repo=TelemetryFileRepository(session),
        quality_repo=QualityRepository(session),
        storage=storage,
        dictionary=dictionary,
        settings=settings,
    )

    result = await service.normalize_file(telemetry_file)
    await session.flush()

    assert result.frames_normalized == 1
    assert result.records_created > 0
    assert result.sentinels_masked == 2  # Gun temp (999.0) and SMR temp (-150.0)
    assert telemetry_file.status == FileStatus.NORMALIZED

    # 4. Verify Silver records in DB
    # Site metadata
    site_stmt = sa.select(SilverSiteMetadata).where(SilverSiteMetadata.frame_id == frame_id)
    site = (await session.execute(site_stmt)).scalars().first()
    assert site is not None
    assert site.charging_station == "Station Alpha"

    # Charger telemetry
    charger_stmt = sa.select(SilverChargerTelemetry).where(
        SilverChargerTelemetry.frame_id == frame_id
    )
    charger_rec = (await session.execute(charger_stmt)).scalars().first()
    assert charger_rec is not None
    assert charger_rec.l1_n_voltage == 230.5

    # Connector telemetry with gun temp sentinel masked
    conn_stmt = sa.select(SilverConnectorTelemetry).where(
        SilverConnectorTelemetry.frame_id == frame_id
    )
    conn_rec = (await session.execute(conn_stmt)).scalars().first()
    assert conn_rec is not None
    assert conn_rec.connector_id == 1
    assert conn_rec.gun_temp_dc_positive is None  # Sentinel masked!
    assert conn_rec.gun_temp_dc_positive_raw == 999.0  # Raw preserved!
    assert conn_rec.gun_temp_dc_positive_masked is True

    # SMR telemetry with probe sentinel masked
    smr_stmt = sa.select(SilverSmrTelemetry).where(SilverSmrTelemetry.frame_id == frame_id)
    smr_rec = (await session.execute(smr_stmt)).scalars().first()
    assert smr_rec is not None
    assert smr_rec.smr_id == 1
    assert smr_rec.smr_dc_dc_temperature is None  # Sentinel masked!
    assert smr_rec.smr_dc_dc_temperature_raw == -150.0  # Raw preserved!
    assert smr_rec.smr_dc_dc_temperature_masked is True

    # Session observation
    sess_stmt = sa.select(SilverSessionObservation).where(
        SilverSessionObservation.frame_id == frame_id
    )
    sess_rec = (await session.execute(sess_stmt)).scalars().first()
    assert sess_rec is not None
    assert sess_rec.stop_reason == "EmergencyStop"

    # Provenance tracking
    prov_stmt = sa.select(SilverObservationProvenance).where(
        SilverObservationProvenance.frame_id == frame_id
    )
    prov_rows = list((await session.execute(prov_stmt)).scalars().all())
    assert len(prov_rows) > 0
    masked_prov = [p for p in prov_rows if p.masked_sentinel]
    assert len(masked_prov) == 2

    # 5. Verify Idempotency: Re-running normalization replaces records without duplicates
    result_rerun = await service.normalize_file(telemetry_file)
    await session.flush()
    assert result_rerun.frames_normalized == 1

    site_count_stmt = (
        sa.select(sa.func.count())
        .select_from(SilverSiteMetadata)
        .where(SilverSiteMetadata.frame_id == frame_id)
    )
    count = (await session.execute(site_count_stmt)).scalar()
    assert count == 1  # Not duplicated!
