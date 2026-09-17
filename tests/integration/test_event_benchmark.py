"""Performance benchmarks for Phase 8 Discrete Event Reconstruction.

Measures and asserts sub-second response times on:
- Complete event reconstruction for a charger
- Unified chronological event timeline retrieval
- Charging sessions query
- Alarm interval query
- Analytical telemetry-event join via ResearchDataAccessLayer
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.services.factory import build_event_service, build_research_access
from backend.app.services.research_access import SignalTarget
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


async def test_event_reconstruction_performance_benchmarks(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Benchmark event reconstruction and query operations against multi-day telemetry."""
    csv_files = generate_7day_history_csvs()

    # Ingest 3 days of telemetry for CH_HIST_01
    for day in range(1, 4):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    service = build_event_service(session)
    timings: dict[str, float] = {}

    # 1. Benchmark complete event reconstruction execution
    t0 = time.perf_counter()
    outcome = await service.reconstruct_charger_events("CH_HIST_01")
    timings["event_reconstruction_ms"] = (time.perf_counter() - t0) * 1000.0
    assert outcome.charger_id == "CH_HIST_01"
    # Target SLA: under 1000ms for full multi-day reconstruction
    assert timings["event_reconstruction_ms"] < 1000.0

    # 2. Benchmark unified event timeline query
    t0 = time.perf_counter()
    timeline = await service.get_unified_timeline("CH_HIST_01", limit=100)
    timings["unified_timeline_query_ms"] = (time.perf_counter() - t0) * 1000.0
    # Query SLA: under 200ms
    assert timings["unified_timeline_query_ms"] < 200.0
    assert timeline is not None

    # 3. Benchmark charging sessions retrieval
    t0 = time.perf_counter()
    sessions = await service.get_sessions("CH_HIST_01")
    timings["sessions_query_ms"] = (time.perf_counter() - t0) * 1000.0
    assert timings["sessions_query_ms"] < 100.0
    assert sessions is not None

    # 4. Benchmark alarms retrieval
    t0 = time.perf_counter()
    alarms = await service.get_alarms("CH_HIST_01")
    timings["alarms_query_ms"] = (time.perf_counter() - t0) * 1000.0
    assert timings["alarms_query_ms"] < 100.0
    assert alarms is not None

    # 5. Benchmark ResearchDataAccessLayer analytical join
    research = build_research_access(session)
    t0 = time.perf_counter()
    signals = [
        SignalTarget(signal_name="smr_dc_dc_temperature", component_type="smr", component_id=3)
    ]
    joined = await research.get_telemetry_with_events("CH_HIST_01", signals=signals, limit=100)
    timings["telemetry_with_events_join_ms"] = (time.perf_counter() - t0) * 1000.0
    assert timings["telemetry_with_events_join_ms"] < 300.0
    assert joined is not None

    print("\n=== Phase 8 Performance Benchmarks ===")
    for k, v in timings.items():
        print(f"  {k}: {v:.2f} ms")
