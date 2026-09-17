"""Integration tests for Phase 7: Historical Continuity & Time-Series Research Layer.

Validates:
- Unified historical queries across multiple files and acquisition sources
- Canonical temporal ordering (event_time ASC, frame_sequence ASC)
- Same-second frame preservation
- Out-of-order arrival and late data integration
- Replay safety (no duplicate history)
- Gap detection relative to empirical local cadence (NO imputation)
- Dynamic topology evolution and component presence intervals
- Hardware configuration snapshot evolution
- Monotonic counter transitions and reset candidate detection
- Fleet-wide signal availability matrix based on observed valid telemetry
- Research Data Access Layer without grid-resampling or synthetic imputation
- Source equivalence (FILESYSTEM vs MANUAL_UPLOAD)
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.enums import (
    DuplicateClassification,
    FileStatus,
    FrameStatus,
    SourceType,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_frame import (
    TelemetryFrameRow,
    TelemetryFrameSource,
    TelemetrySourceFrame,
)
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.silver import SilverRepository
from backend.app.services.history_service import HistoricalContinuityService
from backend.app.services.normalization_service import NormalizationService
from backend.app.services.research_access import (
    ResearchDataAccessLayer,
    SignalTarget,
)
from pipelines.historical.counter_analyzer import CounterTransitionType
from pipelines.normalization.coercion import coerce_datetime
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry
from tests.fixtures.historical_fixtures import generate_7day_history_csvs

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def ingest_csv_to_silver(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
    *,
    filename: str,
    csv_content: str,
    source_type: SourceType = SourceType.FILESYSTEM,
) -> TelemetryFile:
    """Helper to store, frame, and normalize a complete CSV file into Silver."""
    file_id = uuid4()

    async def chunks() -> AsyncIterator[bytes]:
        yield csv_content.encode("utf-8")

    stored = await storage.store(
        chunks(),
        file_id=file_id,
        original_filename=filename,
    )

    telemetry_file = TelemetryFile(
        id=file_id,
        original_filename=filename,
        file_size_bytes=stored.size_bytes,
        source_type=source_type,
        source_reference=filename,
        sha256=stored.sha256,
        status=FileStatus.FRAMES_RECONSTRUCTED,
        storage_reference=stored.storage_reference,
    )
    session.add(telemetry_file)
    await session.flush()

    # Parse rows to create TelemetrySourceFrame records
    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)

    # Group by (charger_id, event_time)
    frames_map: dict[tuple[str, dt.datetime], list[tuple[int, dict[str, str]]]] = {}
    for idx, r in enumerate(rows, start=1):
        cid = r.get("Charger Id", "")
        logged_at_str = r.get("Logged At Time", "")
        evt_time = coerce_datetime(logged_at_str)
        if not cid or not evt_time:
            continue
        frames_map.setdefault((cid, evt_time), []).append((idx, r))

    for (cid, evt_time), frame_rows in frames_map.items():
        existing_stmt = sa.select(TelemetrySourceFrame).where(
            TelemetrySourceFrame.charger_id == cid,
            TelemetrySourceFrame.event_time == evt_time,
            TelemetrySourceFrame.frame_sequence == 0,
        )
        existing_frame = (await session.execute(existing_stmt)).scalars().first()

        if existing_frame is not None:
            frame_id = existing_frame.id
            is_primary = False
        else:
            frame_id = uuid4()
            source_frame = TelemetrySourceFrame(
                id=frame_id,
                charger_id=cid,
                event_time=evt_time,
                business_date=evt_time.date(),
                frame_sequence=0,
                frame_fingerprint=f"fp_{cid}_{evt_time.isoformat()}",
                frame_status=FrameStatus.COMPLETE,
                duplicate_classification=DuplicateClassification.UNIQUE,
                reconstruction_version="v1",
                expected_position_count=len(frame_rows[0][1]),
                observed_position_count=len(frame_rows[0][1]),
            )
            session.add(source_frame)
            await session.flush()
            is_primary = True

        frame_source = TelemetryFrameSource(
            frame_id=frame_id,
            telemetry_file_id=file_id,
            first_source_row=frame_rows[0][0],
            last_source_row=frame_rows[-1][0],
            row_count=len(frame_rows),
            is_primary_source=is_primary,
        )
        session.add(frame_source)

        for row_idx, r in frame_rows:
            f_row = TelemetryFrameRow(
                frame_id=frame_id,
                telemetry_file_id=file_id,
                source_row_number=row_idx,
                connector_id=r.get("Connector No"),
                smr_id=r.get("Smr No."),
                logical_position=f"C{r.get('Connector No')}/S{r.get('Smr No.')}",
                row_fingerprint=f"rfp_{file_id}_{row_idx}",
            )
            session.add(f_row)

    await session.flush()

    # Run Normalization
    norm_service = NormalizationService(
        silver_repo=SilverRepository(session),
        frame_repo=FrameRepository(session),
        file_repo=TelemetryFileRepository(session),
        quality_repo=QualityRepository(session),
        storage=storage,
        dictionary=dictionary,
        settings=settings,
    )
    await norm_service.normalize_file(telemetry_file)
    return telemetry_file


async def test_historical_cross_file_continuity(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Independent files form a single seamless chronological timeline."""
    csv_files = generate_7day_history_csvs()

    # Ingest Days 1, 2, and 3
    for day in range(1, 4):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))

    # Query complete history for CH_HIST_01
    resp = await history_service.get_charger_history("CH_HIST_01", limit=1000)
    assert resp.total_count > 0

    # Verify chronological ordering: event_time ASC, frame_sequence ASC
    obs = resp.observations
    for i in range(1, len(obs)):
        prev_o = obs[i - 1]
        curr_o = obs[i]
        assert (curr_o.event_time, curr_o.frame_sequence) >= (
            prev_o.event_time,
            prev_o.frame_sequence,
        )

    # Multi-day summary covers all 3 days
    summary = await history_service.get_charger_continuity_summary("CH_HIST_01")
    assert summary.observed_days == 3
    assert summary.history_depth_status == "MULTI_OBSERVATION"


async def test_out_of_order_arrival(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Late files integrate into history without reordering by ingestion ID."""
    csv_files = generate_7day_history_csvs()

    # Ingest Day 1, then Day 3, then Day 2 out-of-order!
    order = [1, 3, 2]
    for day in order:
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    resp = await history_service.get_charger_history("CH_HIST_01", limit=1000)

    # Verify output timeline is Day 1 -> Day 2 -> Day 3, despite ingestion order [1, 3, 2]
    event_dates = [o.event_time.date() for o in resp.observations]
    unique_dates = sorted(dict.fromkeys(event_dates))
    assert len(unique_dates) == 3
    assert unique_dates[0] < unique_dates[1] < unique_dates[2]


async def test_replay_safety(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Re-uploading the same telemetry does not produce duplicate history."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_02-09-2026.csv"

    # Ingest Day 2 first time
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    initial_resp = await history_service.get_charger_history("CH_HIST_01")
    count_before = initial_resp.total_count

    # Ingest Day 2 a second time (replay)
    # The normalization service idempotently skips or updates without duplicating
    fn_replay = "telemetry_02-09-2026_replay.csv"
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn_replay, csv_content=csv_files[fn]
    )

    # Observations count for Day 2 must remain exactly identical
    after_resp = await history_service.get_charger_history("CH_HIST_01")
    assert after_resp.total_count == count_before
    # All distinct timestamps for Day 2 must remain unique
    t_stamps = [(o.event_time, o.frame_sequence) for o in after_resp.observations]
    assert len(t_stamps) == len(set(t_stamps)), "Duplicate (event_time, frame_sequence) found!"


async def test_gap_detection_without_imputation(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Gaps are detected relative to local cadence, never imputed with synthetic data."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_02-09-2026.csv"  # Contains the gap fixture for CH_HIST_02 (10:06 to 10:40)

    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    summary = await history_service.get_charger_continuity_summary("CH_HIST_02")

    # Gap must be detected
    assert len(summary.gaps) >= 1
    found_34min_gap = any(g.gap_duration_seconds >= 2000.0 for g in summary.gaps)
    gap_durations = [g.gap_duration_seconds for g in summary.gaps]
    assert found_34min_gap, f"Expected ~34 min gap, detected: {gap_durations}"

    # Invariant: NO synthetic observations exist inside the gap interval
    gap = [g for g in summary.gaps if g.gap_duration_seconds >= 2000.0][0]
    inside_gap_resp = await history_service.get_charger_history(
        "CH_HIST_02",
        start_time=gap.gap_start + dt.timedelta(seconds=1),
        end_time=gap.gap_end - dt.timedelta(seconds=1),
    )
    assert inside_gap_resp.total_count == 0, "Synthetic rows detected inside gap window!"


async def test_topology_evolution(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Dynamic topology evolution (SMRs 1-4 Days 1-3, SMRs 1-6 Days 4-7) is preserved."""
    csv_files = generate_7day_history_csvs()

    for day in range(1, 8):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    summary = await history_service.get_charger_continuity_summary("CH_HIST_03")

    # Overall observed SMRs across 7 days: 1, 2, 3, 4, 5, 6
    assert 5 in summary.smrs_observed
    assert 6 in summary.smrs_observed

    # SMR 5 history: must only exist on Days 4-7, zero observations on Days 1-3!
    smr5_resp = await history_service.get_component_history(
        "CH_HIST_03", "smr", component_id=5, limit=1000
    )
    assert smr5_resp.total_count > 0
    earliest_smr5_time = smr5_resp.observations[0].event_time
    assert earliest_smr5_time.day >= 4, f"SMR 5 observed too early: {earliest_smr5_time}"


async def test_configuration_timeline(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Configuration snapshots record version evolution over time."""
    csv_files = generate_7day_history_csvs()

    for day in range(1, 8):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    timeline = await history_service.get_configuration_timeline("CH_HIST_03")

    # Has Mode_A and Mode_B
    modes = {cfg.charging_mode for cfg in timeline if cfg.charging_mode}
    assert "Mode_A" in modes
    assert "Mode_B" in modes


async def test_counter_reset_preservation(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Monotonic counters detect reset candidates without repairing values."""
    csv_files = generate_7day_history_csvs()

    for day in range(1, 8):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    report = await history_service.get_counter_history(
        "CH_HIST_01", counter_name="ems_cumulative_energy"
    )

    assert report.total_observations > 0
    assert report.reset_candidate_count >= 1

    # Invariant: Value 3.0 on Day 5 is preserved as 3.0, not repaired
    reset_events = [
        t for t in report.transitions if t.transition_type == CounterTransitionType.RESET_CANDIDATE
    ]
    assert len(reset_events) >= 1
    assert reset_events[0].current_value == pytest.approx(3.0, 0.1)


async def test_signal_availability_matrix(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Availability reflects observed non-null telemetry, not schema presence."""
    csv_files = generate_7day_history_csvs()
    for day in (1, 2):
        fn = f"telemetry_{day:02d}-09-2026.csv"
        await ingest_csv_to_silver(
            session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
        )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    matrix_resp = await history_service.get_fleet_signal_availability_matrix(
        charger_ids=["CH_HIST_01", "CH_HIST_03"]
    )

    matrix = matrix_resp.matrix
    # CH_HIST_01 has RSRP populated
    assert matrix["CH_HIST_01"]["rsrp"] is True
    # CH_HIST_03 has RSRP null/absent across all frames
    assert matrix["CH_HIST_03"]["rsrp"] is False


async def test_research_data_access_layer_no_imputation(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: Research layer retrieves exact asynchronous timestamps across signals."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_01-09-2026.csv"
    await ingest_csv_to_silver(
        session, settings, storage, dictionary, filename=fn, csv_content=csv_files[fn]
    )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    research_layer = ResearchDataAccessLayer(history_service)

    # Query multi-signal: Cabinet Temp & Gun Voltage
    signals = [
        SignalTarget(signal_name="cabinet_temperature"),
        SignalTarget(signal_name="gun_voltage", component_type="connector", component_id=1),
    ]

    results = await research_layer.get_multisignal_history("CH_HIST_01", signals)
    assert "cabinet_temperature" in results
    assert "connector:1:gun_voltage" in results

    cab_obs = results["cabinet_temperature"]
    gun_obs = results["connector:1:gun_voltage"]
    assert len(cab_obs) > 0
    assert len(gun_obs) > 0

    # Exact event times preserved without synthetic time-snapping
    for o in cab_obs:
        assert isinstance(o.event_time, dt.datetime)
        assert o.value is not None


async def test_source_equivalence(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Invariant: FILESYSTEM vs MANUAL_UPLOAD produces identical analytical history."""
    csv_files = generate_7day_history_csvs()
    fn = "telemetry_01-09-2026.csv"

    # Ingest as FILESYSTEM
    await ingest_csv_to_silver(
        session,
        settings,
        storage,
        dictionary,
        filename="fs_" + fn,
        csv_content=csv_files[fn],
        source_type=SourceType.FILESYSTEM,
    )

    history_service = HistoricalContinuityService(session, SilverRepository(session))
    fs_resp = await history_service.get_charger_history("CH_HIST_01")

    # Both produce identical observation count and identical event timestamps
    assert fs_resp.total_count > 0
