"""Performance benchmarks for Phase 7 historical queries (Section 33 & 63).

Measures and asserts sub-second response times on:
- 1-day charger history
- 7-day charger history
- SMR temperature history
- Connector telemetry history
- Multi-day continuity summary
- Detected gaps retrieval
- Fleet-wide signal availability matrix
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.repositories.silver import SilverRepository
from backend.app.services.history_service import HistoricalContinuityService
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry
from tests.fixtures.historical_fixtures import generate_7day_history_csvs
from tests.integration.test_historical_continuity import ingest_csv_to_silver

if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.integration


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def test_historical_query_performance_benchmarks(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Benchmark representative historical queries and report measured timings."""
    csv_files = generate_7day_history_csvs()

    # Pre-populate 7 days of telemetry across 3 chargers
    for day in range(1, 8):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    service = HistoricalContinuityService(session, SilverRepository(session))
    timings: dict[str, float] = {}

    # 1. Benchmark 1-day charger history
    t0 = time.perf_counter()
    day1_resp = await service.get_charger_history("CH_HIST_01", limit=100)
    timings["1_day_charger_history_ms"] = (time.perf_counter() - t0) * 1000.0
    assert day1_resp.total_count > 0

    # 2. Benchmark 7-day charger history
    t0 = time.perf_counter()
    day7_resp = await service.get_charger_history("CH_HIST_01", limit=1000)
    timings["7_day_charger_history_ms"] = (time.perf_counter() - t0) * 1000.0
    assert day7_resp.total_count > 0

    # 3. Benchmark SMR temperature signal history
    t0 = time.perf_counter()
    smr_resp = await service.get_signal_history(
        "CH_HIST_01",
        "smr_dc_dc_temperature",
        component_type="smr",
        component_id=3,
    )
    timings["smr_temp_signal_history_ms"] = (time.perf_counter() - t0) * 1000.0
    assert smr_resp.observation_count > 0

    # 4. Benchmark connector component history
    t0 = time.perf_counter()
    conn_resp = await service.get_component_history("CH_HIST_01", "connector", component_id=1)
    timings["connector_history_ms"] = (time.perf_counter() - t0) * 1000.0
    assert conn_resp.total_count > 0

    # 5. Benchmark multi-day continuity summary & gap detection
    t0 = time.perf_counter()
    summary = await service.get_charger_continuity_summary("CH_HIST_02")
    timings["multi_day_summary_and_gaps_ms"] = (time.perf_counter() - t0) * 1000.0
    assert summary.observation_count > 0

    # 6. Benchmark fleet-wide signal availability matrix
    t0 = time.perf_counter()
    matrix = await service.get_fleet_signal_availability_matrix(
        charger_ids=["CH_HIST_01", "CH_HIST_02", "CH_HIST_03"]
    )
    timings["signal_availability_matrix_ms"] = (time.perf_counter() - t0) * 1000.0
    assert len(matrix.matrix) == 3

    # Log measured benchmarks
    print("\n--- Phase 7 Measured Query Performance ---")
    for q_name, ms in timings.items():
        print(f"  {q_name}: {ms:.2f} ms")
        # Assert strict sub-second performance
        assert ms < 500.0, f"Query {q_name} exceeded 500ms threshold: {ms:.2f} ms"
