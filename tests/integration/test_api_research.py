"""API endpoint integration tests for Phase 9 Scientific Research & Pattern Discovery."""

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
from backend.app.models.discrete_events import AlarmEvent, ChargingSessionEvent
from backend.app.models.enums import AlarmSeverity, EventConfidence, TerminationClass
from backend.app.models.silver_telemetry import SilverChargerTelemetry

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


async def test_api_research_endpoints(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Verify all 7 research endpoints end-to-end via HTTP requests."""
    charger_id = "CH_API_RES_01"
    t0 = dt.datetime(2026, 9, 1, 10, 0, 0, tzinfo=dt.UTC)

    # 1. Seed telemetry data with undervoltage
    for i in range(6):
        t = t0 + dt.timedelta(minutes=i * 2)
        session.add(
            SilverChargerTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                event_time=t,
                frame_sequence=i + 1,
                frame_id=uuid4(),
                l1_n_voltage=190.0,
                l2_n_voltage=192.0,
                l3_n_voltage=191.0,
                line_1_input_current=40.0,
                line_2_input_current=41.0,
                line_3_input_current=12.0,
                cabinet_temperature=45.0,
            )
        )

    session.add(
        ChargingSessionEvent(
            id=uuid4(),
            charger_id=charger_id,
            connector_id=1,
            start_time=t0,
            end_time=t0 + dt.timedelta(minutes=10),
            duration_seconds=600.0,
            energy_delivered_kwh=15.0,
            confidence=EventConfidence.HIGH,
            has_gap=False,
            termination_class=TerminationClass.NORMAL,
            start_soc=15.0,
            end_soc=85.0,
        )
    )

    session.add(
        AlarmEvent(
            id=uuid4(),
            charger_id=charger_id,
            alarm_code="ERR_COMM",
            alarm_name="Communication Failure",
            start_time=t0,
            end_time=t0 + dt.timedelta(minutes=5),
            duration_seconds=300.0,
            confidence=EventConfidence.HIGH,
            is_open=False,
            severity=AlarmSeverity.WARNING,
        )
    )

    await session.commit()

    # 2. Test GET /api/v1/research/fleet-eda
    resp = await client.get("/api/v1/research/fleet-eda")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    data = body["data"]
    assert data["total_chargers"] >= 1
    assert data["total_observations"] >= 6
    assert data["total_sessions"] >= 1
    assert data["total_alarms"] >= 1

    # 3. Test GET /api/v1/research/data-readiness
    resp = await client.get("/api/v1/research/data-readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    data = body["data"]
    assert "overall_readiness" in data
    assert "blockers" in data
    assert "recommendations" in data

    # 4. Test GET /api/v1/research/chargers/{charger_id}/signal-stats
    resp = await client.get(f"/api/v1/research/chargers/{charger_id}/signal-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    stats = body["data"]
    assert len(stats) > 0
    stat_names = [s["signal_name"] for s in stats]
    assert "l1_n_voltage" in stat_names

    # 5. Test GET /api/v1/research/chargers/{charger_id}/correlations
    resp = await client.get(f"/api/v1/research/chargers/{charger_id}/correlations")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    corr_data = body["data"]
    assert "signal_names" in corr_data
    assert "entries" in corr_data

    # 6. Test POST /api/v1/research/chargers/{charger_id}/scan-patterns
    resp = await client.post(f"/api/v1/research/chargers/{charger_id}/scan-patterns")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    scan_outcome = body["data"]
    assert scan_outcome["charger_id"] == charger_id
    assert scan_outcome["candidates_found"] >= 1

    # 7. Test GET /api/v1/research/chargers/{charger_id}/patterns
    resp = await client.get(f"/api/v1/research/chargers/{charger_id}/patterns")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    patterns = body["data"]
    assert len(patterns) >= 1

    # Test query params filtering
    resp_filtered = await client.get(
        f"/api/v1/research/chargers/{charger_id}/patterns?min_confidence=0.1"
    )
    assert resp_filtered.status_code == 200
    filtered_patterns = resp_filtered.json()["data"]
    assert len(filtered_patterns) >= 1

    # 8. Test POST /api/v1/research/chargers/{charger_id}/build-dataset
    resp = await client.post(
        f"/api/v1/research/chargers/{charger_id}/build-dataset?grain=CHARGER_TIME"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") is None
    ds = body["data"]
    assert ds["charger_id"] == charger_id
    assert ds["grain"] == "CHARGER_TIME"
    assert ds["record_count"] >= 1
