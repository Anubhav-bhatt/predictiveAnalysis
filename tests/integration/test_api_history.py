"""API endpoint integration tests for Phase 7 Historical Continuity (history endpoints)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_session
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry
from tests.fixtures.historical_fixtures import generate_7day_history_csvs
from tests.integration.test_historical_continuity import ingest_csv_to_silver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(session: AsyncSession, settings: Settings) -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    app = create_app(settings)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_settings] = lambda: settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def test_api_charger_history_and_summary(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Verify charger history and summary endpoints."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_01-09-2026.csv"
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    # 1. GET history
    resp = await client.get("/api/v1/chargers/CH_HIST_01/history")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["charger_id"] == "CH_HIST_01"
    assert data["total_count"] > 0
    assert len(data["observations"]) > 0

    # 2. GET summary
    sum_resp = await client.get("/api/v1/chargers/CH_HIST_01/summary")
    assert sum_resp.status_code == 200
    sum_data = sum_resp.json()["data"]
    assert sum_data["charger_id"] == "CH_HIST_01"
    assert sum_data["observation_count"] > 0
    assert "sampling_profile" in sum_data
    assert "pattern_eligibility" in sum_data

    # 3. GET pattern-eligibility
    pe_resp = await client.get("/api/v1/chargers/CH_HIST_01/pattern-eligibility")
    assert pe_resp.status_code == 200
    pe_data = pe_resp.json()["data"]
    assert pe_data["charger_id"] == "CH_HIST_01"
    assert isinstance(pe_data["pattern_research_ready"], bool)


async def test_api_component_and_signal_history(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Verify component and canonical signal historical endpoints."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_01-09-2026.csv"
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    # Component history (SMR 3)
    smr_resp = await client.get("/api/v1/chargers/CH_HIST_01/components/smr/3/history")
    assert smr_resp.status_code == 200
    smr_data = smr_resp.json()["data"]
    assert smr_data["total_count"] > 0

    # Signal history (Cabinet Temperature)
    sig_resp = await client.get("/api/v1/chargers/CH_HIST_01/signals/cabinet_temperature/history")
    assert sig_resp.status_code == 200
    sig_data = sig_resp.json()["data"]
    assert sig_data["signal_name"] == "cabinet_temperature"
    assert sig_data["observation_count"] > 0

    # Invalid component type returns 400
    bad_comp = await client.get("/api/v1/chargers/CH_HIST_01/components/inverter/1/history")
    assert bad_comp.status_code == 400

    # Invalid time range returns 400
    bad_time = await client.get(
        "/api/v1/chargers/CH_HIST_01/history?start_time=2026-09-02T00:00:00Z&end_time=2026-09-01T00:00:00Z"
    )
    assert bad_time.status_code == 400


async def test_api_fleet_signal_matrix(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Verify fleet-wide signal availability matrix endpoint."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_01-09-2026.csv"
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    resp = await client.get(
        "/api/v1/fleet/signal-matrix",
        params=[("charger_ids", "CH_HIST_01"), ("charger_ids", "CH_HIST_03")],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "signals" in data
    assert "matrix" in data
    matrix = data["matrix"]
    assert "CH_HIST_01" in matrix
    assert "CH_HIST_03" in matrix
