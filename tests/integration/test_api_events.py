"""API endpoint integration tests for Phase 8 Discrete Event Reconstruction."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.app.api.deps import get_session, get_write_session
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app
from backend.app.models.silver_telemetry import (
    SilverAlarmObservation,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverSessionObservation,
)
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings) -> AsyncIterator[AsyncClient]:
    """An API client configured with test session factory."""
    get_settings.cache_clear()
    app = create_app(settings)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _read_session() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            try:
                yield db
            finally:
                await db.rollback()

    async def _write_session() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise
            else:
                await db.commit()

    app.dependency_overrides[get_session] = _read_session
    app.dependency_overrides[get_write_session] = _write_session
    app.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def test_api_reconstruct_and_fetch_events(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Verify end-to-end HTTP workflow: reconstruct and query timeline/sessions/alarms."""
    charger_id = "CH_API_EVT_01"
    t0 = dt.datetime(2026, 9, 1, 10, 0, 0, tzinfo=dt.UTC)

    # Seed Silver records
    # 1. Connector and Session observations for a session
    states = [
        (t0, 1, "Preparing", 0.0, 15.0),
        (t0 + dt.timedelta(minutes=5), 2, "Charging", 3.0, 35.0),
        (t0 + dt.timedelta(minutes=15), 3, "Charging", 10.0, 75.0),
        (t0 + dt.timedelta(minutes=20), 4, "Available", 10.0, 75.0),
    ]
    for event_time, seq, status_str, energy, soc in states:
        f_id = uuid4()
        session.add(
            SilverConnectorTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                connector_status=status_str,
                plug_status="Connected" if status_str != "Available" else "Disconnected",
            )
        )
        session.add(
            SilverSessionObservation(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                session_id=2001.0,
                session_consumed_energy=energy,
                start_soc=soc if seq == 1 else None,
                stop_soc=soc if status_str == "Available" else None,
                stop_reason="Local" if status_str == "Available" else None,
            )
        )

    # 2. Alarm observation (smoke_alarm)
    session.add(
        SilverAlarmObservation(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=5),
            frame_sequence=2,
            frame_id=uuid4(),
            smoke_alarm="1",
        )
    )
    session.add(
        SilverAlarmObservation(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=3,
            frame_id=uuid4(),
            smoke_alarm="0",
        )
    )

    # 3. Config snapshot
    session.add(
        SilverConfigurationSnapshot(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0,
            frame_sequence=1,
            frame_id=uuid4(),
            config_hash="HASH_CFG_01",
            raw_config_json={"power_limit": 60},
        )
    )
    session.add(
        SilverConfigurationSnapshot(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=12),
            frame_sequence=3,
            frame_id=uuid4(),
            config_hash="HASH_CFG_02",
            raw_config_json={"power_limit": 120},
        )
    )

    await session.commit()

    # 1. POST /api/v1/chargers/{charger_id}/reconstruct-events
    recon_resp = await client.post(f"/api/v1/chargers/{charger_id}/reconstruct-events")
    assert recon_resp.status_code == 200
    recon_data = recon_resp.json()["data"]
    assert recon_data["charger_id"] == charger_id
    assert recon_data["sessions_reconstructed"] == 1
    assert recon_data["alarms_reconstructed"] == 1
    assert recon_data["configuration_changes_reconstructed"] == 1

    # 2. GET /api/v1/chargers/{charger_id}/event-timeline
    tl_resp = await client.get(f"/api/v1/chargers/{charger_id}/event-timeline")
    assert tl_resp.status_code == 200
    tl_data = tl_resp.json()["data"]
    assert tl_data["charger_id"] == charger_id
    assert tl_data["total_count"] >= 3
    assert len(tl_data["events"]) >= 3

    # 3. GET /api/v1/chargers/{charger_id}/events (alias endpoint)
    alias_resp = await client.get(f"/api/v1/chargers/{charger_id}/events")
    assert alias_resp.status_code == 200
    assert alias_resp.json()["data"]["total_count"] == tl_data["total_count"]

    # 4. GET /api/v1/chargers/{charger_id}/sessions
    sess_resp = await client.get(f"/api/v1/chargers/{charger_id}/sessions")
    assert sess_resp.status_code == 200
    sess_data = sess_resp.json()["data"]
    assert sess_data["total_count"] == 1
    session_item = sess_data["sessions"][0]
    assert session_item["connector_id"] == 1
    assert session_item["energy_delivered_kwh"] == 10.0
    assert session_item["confidence"] == "HIGH"

    # 5. GET /api/v1/chargers/{charger_id}/alarms
    alarm_resp = await client.get(f"/api/v1/chargers/{charger_id}/alarms")
    assert alarm_resp.status_code == 200
    alarm_data = alarm_resp.json()["data"]
    assert alarm_data["total_count"] == 1
    alarm_item = alarm_data["alarms"][0]
    assert alarm_item["alarm_code"] == "smoke_alarm"
    assert alarm_item["severity"] == "CRITICAL"
    assert alarm_item["is_open"] is False


async def test_api_event_endpoints_validation(client: AsyncClient) -> None:
    """Verify query parameter validation on event endpoints."""
    # Invalid window: start_time > end_time
    start = "2026-09-02T10:00:00Z"
    end = "2026-09-01T10:00:00Z"

    resp = await client.get(
        f"/api/v1/chargers/CH_TEST/event-timeline?start_time={start}&end_time={end}"
    )
    assert resp.status_code == 400
    assert "start_time must not be greater than end_time" in resp.json()["error"]["message"]

    resp = await client.get(f"/api/v1/chargers/CH_TEST/sessions?start_time={start}&end_time={end}")
    assert resp.status_code == 400
    assert "start_time must not be greater than end_time" in resp.json()["error"]["message"]

    resp = await client.get(f"/api/v1/chargers/CH_TEST/alarms?start_time={start}&end_time={end}")
    assert resp.status_code == 400
    assert "start_time must not be greater than end_time" in resp.json()["error"]["message"]

    resp = await client.post(
        f"/api/v1/chargers/CH_TEST/reconstruct-events?start_time={start}&end_time={end}"
    )
    assert resp.status_code == 400
    assert "start_time must not be greater than end_time" in resp.json()["error"]["message"]
