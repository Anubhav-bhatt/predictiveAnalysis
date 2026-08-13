"""Bulk manual upload through the common pipeline (Phase 1C.5 sections 60-73).

The most important test here is
``test_filesystem_and_manual_upload_produce_identical_analytical_results``: it pins
the architectural claim that manual upload is an acquisition path, not a second
pipeline.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.charger_day_coverage import ChargerDayCoverage
from backend.app.models.enums import (
    ChargerLifecycleStatus,
    FileStatus,
    SourceType,
    UploadBatchStatus,
    UploadFileStatus,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.models.telemetry_frame import TelemetrySourceFrame
from backend.app.models.upload_batch import UploadBatch, UploadBatchFile
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.frame_service import FrameReconstructionService
from backend.app.services.ingestion_service import IngestionService
from backend.app.services.upload_service import UploadRejected, UploadService, safe_staged_name
from pipelines.sources.filesystem import FilesystemTelemetrySource
from tests.fixtures.builders import FixtureSpec, build_telemetry_csv

pytestmark = pytest.mark.integration

CHARGER = "D82510560390014"
BUSINESS_DATE = dt.date(2026, 7, 27)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def chunks_of(path: Path) -> AsyncIterator[bytes]:
    """Stream a file the way the HTTP layer would."""
    yield path.read_bytes()


def make_fixture(tmp: Path, name: str, spec: FixtureSpec) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / name
    build_telemetry_csv(path, spec)
    return path


async def register_charger(fleet: FleetRepository, charger_id: str = CHARGER) -> None:
    await fleet.upsert_charger(
        charger_id=charger_id,
        ocpp_id=charger_id[-5:],
        site_code="SITE-HYD-001",
        lifecycle_status=ChargerLifecycleStatus.ACTIVE,
        telemetry_expected=True,
        expected_connector_count=2,
        expected_smr_count=4,
        expected_sampling_interval_seconds=121,
        source_timezone="Asia/Kolkata",
    )


async def upload_and_process(
    *,
    uploads: UploadService,
    ingestion: IngestionService,
    coverage: CoverageService,
    frames: FrameReconstructionService | None,
    files: Sequence[tuple[str, Path]],
) -> tuple[UUID, object]:
    """Stage a batch then run it through the common pipeline."""
    payload = [(name, chunks_of(path)) for name, path in files]
    batch_id, _ = await uploads.stage_batch(payload)
    result = await uploads.process_batch(
        batch_id, ingestion=ingestion, coverage=coverage, frames=frames
    )
    return batch_id, result


async def count_of(session: AsyncSession, model: type) -> int:
    return int(
        (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one()
    )


# ---------------------------------------------------------------------------
# Section 60, 61 - single and bulk upload reach the end of the pipeline
# ---------------------------------------------------------------------------


async def test_single_upload_reaches_frames_reconstructed(
    session: AsyncSession,
    settings: Settings,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Upload -> register -> profile -> schema -> quality -> coverage -> frames."""
    await register_charger(fleet_repo)
    source = make_fixture(
        tmp_path / "src", "HYD12_28-07-2026.csv", FixtureSpec(timestamp_count=12)
    )

    batch_id, result = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_28-07-2026.csv", source)],
    )

    assert result.files_registered == 1  # type: ignore[attr-defined]
    assert result.files_ready == 1  # type: ignore[attr-defined]
    assert result.frames_reconstructed > 0  # type: ignore[attr-defined]

    telemetry_file = (await session.execute(sa.select(TelemetryFile))).scalars().one()
    # Reached the end of the Phase 1D lifecycle through the *common* pipeline.
    assert telemetry_file.status is FileStatus.FRAMES_RECONSTRUCTED
    assert telemetry_file.source_type is SourceType.MANUAL_UPLOAD
    assert telemetry_file.upload_batch_id == batch_id

    # Business date came from event time, not the upload date or the filename.
    assert telemetry_file.business_date == BUSINESS_DATE
    assert telemetry_file.filename_date == dt.date(2026, 7, 28)

    # Coverage and frames exist for the charger-day.
    coverage_row = (
        await session.execute(sa.select(ChargerDayCoverage))
    ).scalars().one()
    assert coverage_row.charger_id == CHARGER
    assert coverage_row.business_date == BUSINESS_DATE
    assert coverage_row.unique_timestamp_count == 12
    assert await count_of(session, TelemetrySourceFrame) > 0

    batch = await UploadRepository(session).get_batch(batch_id)
    assert batch is not None
    assert batch.status in {
        UploadBatchStatus.COMPLETED,
        UploadBatchStatus.COMPLETED_WITH_WARNINGS,
    }


async def test_bulk_upload_processes_every_file(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    files = [
        (
            f"HYD12_day{index}.csv",
            make_fixture(
                tmp_path / "src",
                f"HYD12_day{index}.csv",
                FixtureSpec(
                    timestamp_count=6,
                    start=dt.datetime(2026, 7, 20 + index, 0, 1, 22),
                ),
            ),
        )
        for index in range(5)
    ]

    _, result = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=files,
    )
    assert result.files_ready == 5  # type: ignore[attr-defined]
    assert await count_of(session, TelemetryFile) == 5


# ---------------------------------------------------------------------------
# Section 62, 63, 64 - multi-charger, multi-date, same charger-day
# ---------------------------------------------------------------------------


async def test_multiple_chargers_map_to_their_own_charger_days(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """No batch-level charger selection: identity comes from the telemetry."""
    chargers = ["D82510560390014", "D82510560390015", "D82510560390016"]
    for charger_id in chargers:
        await register_charger(fleet_repo, charger_id)

    files = [
        (
            f"{charger_id}.csv",
            make_fixture(
                tmp_path / "src",
                f"{charger_id}.csv",
                FixtureSpec(charger_id=charger_id, timestamp_count=6),
            ),
        )
        for charger_id in chargers
    ]

    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=files,
    )

    rows = (await session.execute(sa.select(TelemetryFileDay))).scalars().all()
    assert {row.charger_id for row in rows} == set(chargers)

    coverage_rows = (await session.execute(sa.select(ChargerDayCoverage))).scalars().all()
    assert {row.charger_id for row in coverage_rows} == set(chargers)


async def test_multiple_dates_produce_separate_charger_days(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    files = [
        (
            f"HYD12_{day}.csv",
            make_fixture(
                tmp_path / "src",
                f"HYD12_{day}.csv",
                FixtureSpec(
                    timestamp_count=6, start=dt.datetime(2026, 7, day, 0, 1, 22)
                ),
            ),
        )
        for day in (10, 11, 12)
    ]

    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=files,
    )

    dates = {
        row.business_date
        for row in (await session.execute(sa.select(ChargerDayCoverage))).scalars().all()
    }
    assert dates == {dt.date(2026, 7, 10), dt.date(2026, 7, 11), dt.date(2026, 7, 12)}


async def test_two_files_same_charger_day_combine_coverage(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Section 19/64: same charger and date is not automatically a duplicate."""
    await register_charger(fleet_repo)
    morning = make_fixture(
        tmp_path / "src",
        "HYD12_morning.csv",
        FixtureSpec(
            timestamp_count=100,
            start=dt.datetime(2026, 7, 27, 0, 1, 22),
            replay_timestamp_indexes=(),
            conflicting_timestamp_indexes=(),
        ),
    )
    evening = make_fixture(
        tmp_path / "src",
        "HYD12_evening.csv",
        FixtureSpec(
            timestamp_count=100,
            start=dt.datetime(2026, 7, 27, 12, 0, 0),
            replay_timestamp_indexes=(),
            conflicting_timestamp_indexes=(),
        ),
    )

    _, result = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_morning.csv", morning), ("HYD12_evening.csv", evening)],
    )

    # Both accepted - different content, so not duplicates.
    assert result.files_ready == 2  # type: ignore[attr-defined]
    assert result.files_duplicate == 0  # type: ignore[attr-defined]

    coverage_row = (
        await session.execute(
            sa.select(ChargerDayCoverage).where(
                ChargerDayCoverage.business_date == BUSINESS_DATE
            )
        )
    ).scalars().one()
    # One charger-day whose coverage is the union of both files.
    assert coverage_row.file_count == 2
    assert coverage_row.unique_timestamp_count == 200


# ---------------------------------------------------------------------------
# Section 20, 21, 69 - historical and late uploads
# ---------------------------------------------------------------------------


async def test_historical_upload_uses_event_time_not_upload_time(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """An April file uploaded today belongs to April."""
    await register_charger(fleet_repo)
    source = make_fixture(
        tmp_path / "src",
        "HYD12_april.csv",
        FixtureSpec(timestamp_count=8, start=dt.datetime(2026, 4, 3, 0, 1, 22)),
    )

    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_april.csv", source)],
    )

    coverage_row = (await session.execute(sa.select(ChargerDayCoverage))).scalars().one()
    assert coverage_row.business_date == dt.date(2026, 4, 3)
    assert coverage_row.business_date != dt.date.today()


async def test_late_historical_upload_flips_missing_to_late(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Section 53/69: Phase 1C late reconciliation still works through upload."""
    from backend.app.models.enums import ArrivalStatus

    await register_charger(fleet_repo)

    # A MISSING charger-day exists first.
    await coverage_service.reconcile(BUSINESS_DATE)
    before = (
        await session.execute(
            sa.select(ChargerDayCoverage).where(
                ChargerDayCoverage.business_date == BUSINESS_DATE
            )
        )
    ).scalars().one()
    assert before.arrival_status is ArrivalStatus.MISSING
    original_id = before.id

    # The telemetry finally arrives by manual upload.
    source = make_fixture(
        tmp_path / "src", "HYD12_late.csv", FixtureSpec(timestamp_count=700)
    )
    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_late.csv", source)],
    )

    session.expire_all()
    after = (
        await session.execute(
            sa.select(ChargerDayCoverage).where(
                ChargerDayCoverage.business_date == BUSINESS_DATE
            )
        )
    ).scalars().one()
    assert after.id == original_id, "the same coverage row must be updated in place"
    assert after.arrival_status is ArrivalStatus.LATE
    # The fixture's injected gap pushes its tail past midnight, so one timestamp
    # belongs to the 28th - which is Phase 1C attributing each timestamp to the day
    # it actually falls in, not a miscount.
    assert after.unique_timestamp_count == 699
    spill = (
        await session.execute(
            sa.select(ChargerDayCoverage).where(
                ChargerDayCoverage.business_date == dt.date(2026, 7, 28)
            )
        )
    ).scalars().one()
    assert spill.unique_timestamp_count == 1
    assert after.unique_timestamp_count + spill.unique_timestamp_count == 700


# ---------------------------------------------------------------------------
# Section 65, 66 - duplicates within and across sources
# ---------------------------------------------------------------------------


async def test_identical_file_twice_in_one_batch_is_staged_once(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
) -> None:
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12_a.csv", FixtureSpec(timestamp_count=5))

    batch_id, outcomes = await upload_service.stage_batch(
        [("HYD12_a.csv", chunks_of(source)), ("HYD12_copy.csv", chunks_of(source))]
    )

    statuses = [item.status for item in outcomes]
    assert statuses.count(UploadFileStatus.PENDING) == 1
    assert statuses.count(UploadFileStatus.DUPLICATE) == 1

    rows = await UploadRepository(session).staged_files(batch_id)
    assert len(rows) == 1, "only the first copy is queued for the pipeline"


async def test_uploading_the_same_file_in_a_second_batch_is_a_duplicate(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Cross-batch duplicate detection, via the existing SHA-256 identity."""
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=8))

    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )
    files_after_first = await count_of(session, TelemetryFile)
    frames_after_first = await count_of(session, TelemetrySourceFrame)

    _, second = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )

    # One logical telemetry file, and no duplicated downstream data.
    assert await count_of(session, TelemetryFile) == files_after_first
    assert await count_of(session, TelemetrySourceFrame) == frames_after_first
    assert second.files_ready == 0  # type: ignore[attr-defined]
    assert second.files_already_present == 1  # type: ignore[attr-defined]
    assert await count_of(session, UploadBatch) == 2


async def test_outcome_counts_place_each_file_in_exactly_one_bucket(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """The outcome buckets must partition the batch (regression).

    A re-uploaded file is marked DUPLICATE at acquisition *and* linked to the
    telemetry file it matched - which is already FRAMES_RECONSTRUCTED. Counting both
    sides reported a single-file batch as "1 ready and 1 already uploaded", so the
    outcome tiles summed to twice the batch.
    """
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=8))

    first_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )
    second_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )

    repo = UploadRepository(session)
    buckets = (
        "pending",
        "processing",
        "completed",
        "duplicate",
        "failed",
        "quarantined",
        "rejected",
    )

    for batch_id, expected_bucket in ((first_id, "completed"), (second_id, "duplicate")):
        counts = await repo.batch_counts(batch_id)
        assert sum(counts[name] for name in buckets) == counts["total_files"] == 1
        assert counts[expected_bucket] == 1

    # The history page derives the same numbers in bulk; it must agree exactly.
    bulk = await repo.list_counts_for_batches([first_id, second_id])
    for batch_id in (first_id, second_id):
        single = await repo.batch_counts(batch_id)
        assert {k: bulk[batch_id][k] for k in buckets} == {k: single[k] for k in buckets}


async def test_filesystem_then_manual_upload_of_the_same_file_is_a_duplicate(
    session: AsyncSession,
    settings: Settings,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Section 66: the source mechanism must not redefine source identity."""
    await register_charger(fleet_repo)
    inbox = settings.filesystem_source.inbox
    inbox.mkdir(parents=True, exist_ok=True)
    fixture = make_fixture(inbox, "HYD12_28-07-2026.csv", FixtureSpec(timestamp_count=8))

    # 1) discovered from the filesystem
    fs_source = FilesystemTelemetrySource(
        inbox, pattern="*.csv", allowed_extensions=settings.ingest.allowed_extensions
    )
    await ingestion_service.run(fs_source)
    files_after_fs = await count_of(session, TelemetryFile)
    assert files_after_fs == 1

    # 2) the identical bytes uploaded manually
    _, result = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_28-07-2026.csv", fixture)],
    )

    assert await count_of(session, TelemetryFile) == files_after_fs
    assert result.files_ready == 0  # type: ignore[attr-defined]

    telemetry_file = (await session.execute(sa.select(TelemetryFile))).scalars().one()
    # The canonical record keeps its original source; the upload did not
    # re-register it under a new source type.
    assert telemetry_file.source_type is SourceType.FILESYSTEM


# ---------------------------------------------------------------------------
# Section 70 - THE source-equivalence contract
# ---------------------------------------------------------------------------


async def test_filesystem_and_manual_upload_produce_identical_analytical_results(
    session: AsyncSession,
    settings: Settings,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Equivalent telemetry, two acquisition paths, identical business results.

    Two chargers are used so both paths can run in one database without the
    checksum identity collapsing them into a single file. Everything analytical is
    compared; only source metadata is permitted to differ.
    """
    charger_fs = "D82510560390014"
    charger_up = "D82510560390015"
    await register_charger(fleet_repo, charger_fs)
    await register_charger(fleet_repo, charger_up)

    spec_kwargs = {
        "timestamp_count": 40,
        "interval_seconds": 121,
        "replay_timestamp_indexes": (5,),
        "conflicting_timestamp_indexes": (7,),
    }

    inbox = settings.filesystem_source.inbox
    inbox.mkdir(parents=True, exist_ok=True)

    # Warm the schema registry with an unrelated file first. The first file to
    # arrive anywhere *creates* the schema version and is scored UNKNOWN_SCHEMA;
    # without this, whichever path ran first would differ on schema grounds alone
    # and the test would be measuring processing order rather than source.
    make_fixture(
        inbox,
        "WARMUP.csv",
        FixtureSpec(charger_id="WARMUP01", timestamp_count=3),
    )
    await ingestion_service.run(
        FilesystemTelemetrySource(
            inbox, pattern="WARMUP.csv", allowed_extensions=settings.ingest.allowed_extensions
        )
    )

    make_fixture(
        inbox,
        "FS_28-07-2026.csv",
        FixtureSpec(charger_id=charger_fs, **spec_kwargs),  # type: ignore[arg-type]
    )
    uploaded = make_fixture(
        tmp_path / "src",
        "UP_28-07-2026.csv",
        FixtureSpec(charger_id=charger_up, **spec_kwargs),  # type: ignore[arg-type]
    )

    # Path A: filesystem discovery.
    await ingestion_service.run(
        FilesystemTelemetrySource(
            inbox,
            pattern="FS_*.csv",
            allowed_extensions=settings.ingest.allowed_extensions,
        )
    )
    # Path B: manual upload.
    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=None,
        files=[("UP_28-07-2026.csv", uploaded)],
    )

    files = {
        f.original_filename: f
        for f in (await session.execute(sa.select(TelemetryFile))).scalars().all()
    }
    fs_file = files["FS_28-07-2026.csv"]
    up_file = files["UP_28-07-2026.csv"]

    # --- source metadata is ALLOWED to differ ---------------------------
    assert fs_file.source_type is SourceType.FILESYSTEM
    assert up_file.source_type is SourceType.MANUAL_UPLOAD
    assert fs_file.upload_batch_id is None
    assert up_file.upload_batch_id is not None

    # --- everything analytical must be identical ------------------------
    assert fs_file.business_date == up_file.business_date == BUSINESS_DATE
    assert fs_file.row_count == up_file.row_count
    assert fs_file.column_count == up_file.column_count
    assert fs_file.unique_event_timestamp_count == up_file.unique_event_timestamp_count
    assert fs_file.connector_count_detected == up_file.connector_count_detected
    assert fs_file.smr_count_detected == up_file.smr_count_detected
    assert fs_file.file_date_span == up_file.file_date_span
    assert fs_file.schema_version_id == up_file.schema_version_id
    assert fs_file.header_fingerprint == up_file.header_fingerprint
    # With the registry warmed, both paths see the same known schema - so even the
    # schema verdict matches, not just the version id.
    assert fs_file.schema_compatibility == up_file.schema_compatibility

    # Quality: identical structure means identical dimension scores.
    assert fs_file.schema_quality == up_file.schema_quality
    assert fs_file.completeness_quality == up_file.completeness_quality
    assert fs_file.validity_quality == up_file.validity_quality
    assert fs_file.duplicate_quality == up_file.duplicate_quality
    assert fs_file.timestamp_quality == up_file.timestamp_quality

    # Duplicate/replay profile from Phase 1A.
    assert fs_file.exact_duplicate_row_count == up_file.exact_duplicate_row_count
    assert (
        fs_file.logical_key_collision_group_count
        == up_file.logical_key_collision_group_count
    )
    assert (
        fs_file.logical_key_conflicting_group_count
        == up_file.logical_key_conflicting_group_count
    )

    # Phase 1C coverage.
    await coverage_service.reconcile(BUSINESS_DATE)
    coverage_rows = {
        row.charger_id: row
        for row in (await session.execute(sa.select(ChargerDayCoverage))).scalars().all()
    }
    fs_cov, up_cov = coverage_rows[charger_fs], coverage_rows[charger_up]
    assert fs_cov.unique_timestamp_count == up_cov.unique_timestamp_count
    assert fs_cov.coverage_percentage == up_cov.coverage_percentage
    assert fs_cov.gap_count == up_cov.gap_count
    assert fs_cov.largest_gap_seconds == up_cov.largest_gap_seconds
    assert fs_cov.connector_count_detected == up_cov.connector_count_detected
    assert fs_cov.smr_count_detected == up_cov.smr_count_detected
    assert fs_cov.completeness_status == up_cov.completeness_status

    # Phase 1D reconstruction.
    await frame_service.reconstruct_file(fs_file, advance_lifecycle=False)
    await frame_service.reconstruct_file(up_file, advance_lifecycle=False)

    def frame_shape(rows: Sequence[TelemetrySourceFrame]) -> list[tuple[object, ...]]:
        """Structure and classification, with charger identity factored out."""
        return sorted(
            (
                row.frame_sequence,
                row.frame_status,
                row.duplicate_classification,
                row.expected_position_count,
                row.observed_position_count,
                row.missing_position_count,
            )
            for row in rows
        )

    fs_frames = (
        await session.execute(
            sa.select(TelemetrySourceFrame).where(
                TelemetrySourceFrame.charger_id == charger_fs
            )
        )
    ).scalars().all()
    up_frames = (
        await session.execute(
            sa.select(TelemetrySourceFrame).where(
                TelemetrySourceFrame.charger_id == charger_up
            )
        )
    ).scalars().all()

    assert len(fs_frames) == len(up_frames) > 0
    assert frame_shape(fs_frames) == frame_shape(up_frames)
    # Same collision and replay verdicts, reached independently.
    assert sorted(f.duplicate_classification for f in fs_frames) == sorted(
        f.duplicate_classification for f in up_frames
    )


# ---------------------------------------------------------------------------
# Section 68 - malformed file isolation
# ---------------------------------------------------------------------------


async def test_malformed_file_does_not_stop_the_batch(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Valid A, malformed B, valid C -> A and C still process."""
    await register_charger(fleet_repo)
    src = tmp_path / "src"
    valid_a = make_fixture(src, "A.csv", FixtureSpec(timestamp_count=6))
    valid_c = make_fixture(
        src, "C.csv", FixtureSpec(timestamp_count=6, start=dt.datetime(2026, 7, 29, 1, 0))
    )
    malformed = src / "B.csv"
    malformed.write_text("this,is,not,charger,telemetry\n1,2,3,4,5\n", encoding="utf-8")

    batch_id, result = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("A.csv", valid_a), ("B.csv", malformed), ("C.csv", valid_c)],
    )

    assert result.files_ready == 2, "the two valid files still processed"  # type: ignore[attr-defined]
    problems = result.files_failed + result.files_quarantined  # type: ignore[attr-defined]
    assert problems == 1

    batch = await UploadRepository(session).get_batch(batch_id)
    assert batch is not None
    # One bad file degrades the batch; it does not fail it.
    assert batch.status is UploadBatchStatus.COMPLETED_WITH_WARNINGS


# ---------------------------------------------------------------------------
# Section 52 - idempotency through the whole pipeline
# ---------------------------------------------------------------------------


async def test_reprocessing_a_batch_is_idempotent(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=10))

    batch_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )

    counts = (
        await count_of(session, TelemetryFile),
        await count_of(session, TelemetryFileDay),
        await count_of(session, ChargerDayCoverage),
        await count_of(session, TelemetrySourceFrame),
    )

    for _ in range(2):
        await upload_service.process_batch(
            batch_id,
            ingestion=ingestion_service,
            coverage=coverage_service,
            frames=frame_service,
        )
        assert (
            await count_of(session, TelemetryFile),
            await count_of(session, TelemetryFileDay),
            await count_of(session, ChargerDayCoverage),
            await count_of(session, TelemetrySourceFrame),
        ) == counts


# ---------------------------------------------------------------------------
# Section 73 - security
# ---------------------------------------------------------------------------


async def test_path_traversal_filename_cannot_escape_staging(
    session: AsyncSession,
    settings: Settings,
    tmp_path: Path,
    upload_service: UploadService,
) -> None:
    source = make_fixture(tmp_path / "src", "ok.csv", FixtureSpec(timestamp_count=3))

    batch_id, outcomes = await upload_service.stage_batch(
        [("../../../../etc/passwd.csv", chunks_of(source))]
    )
    assert outcomes[0].status is UploadFileStatus.PENDING

    rows = await UploadRepository(session).staged_files(batch_id)
    staged = Path(str(rows[0].staged_reference)).resolve()
    staging_root = Path(settings.upload.staging_root).resolve()

    assert staged.is_relative_to(staging_root), "staged bytes stayed inside staging"
    assert "etc" not in staged.name
    # The original name survives as metadata only.
    assert rows[0].original_filename == "../../../../etc/passwd.csv"


def test_safe_staged_name_neutralises_hostile_filenames() -> None:
    assert "/" not in safe_staged_name("../../etc/passwd")
    assert ".." not in safe_staged_name("..\\..\\windows\\system32")
    assert safe_staged_name("") == "upload"
    assert safe_staged_name("   ") == "upload"
    assert len(safe_staged_name("x" * 500 + ".csv")) <= 120
    # A normal name is left recognisable.
    assert safe_staged_name("HYD12_28-07-2026.csv") == "HYD12_28-07-2026.csv"
    # Control characters and shell metacharacters: an allowlist, so anything not
    # explicitly safe becomes an underscore rather than being escaped case by case.
    assert safe_staged_name("a\x00b.csv") == "a_b.csv"
    assert safe_staged_name("a\r\nb.csv") == "a_b.csv"
    assert safe_staged_name("file;rm -rf /.csv") == "csv"
    # Right-to-left override, used to disguise an extension visually.
    assert safe_staged_name("\u202eslkcs.csv") == "slkcs.csv"


async def test_unsupported_extension_is_rejected(
    tmp_path: Path, upload_service: UploadService
) -> None:
    payload = tmp_path / "evil.exe"
    payload.write_bytes(b"MZ binary")

    _, outcomes = await upload_service.stage_batch([("evil.exe", chunks_of(payload))])
    assert outcomes[0].status is UploadFileStatus.REJECTED
    assert "not permitted" in (outcomes[0].rejection_reason or "")


async def test_empty_file_is_rejected(tmp_path: Path, upload_service: UploadService) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")

    _, outcomes = await upload_service.stage_batch([("empty.csv", chunks_of(empty))])
    assert outcomes[0].status is UploadFileStatus.REJECTED
    assert outcomes[0].rejection_reason == "File is empty"


async def test_oversized_file_is_rejected(
    settings: Settings, tmp_path: Path, session: AsyncSession
) -> None:
    from backend.app.services.factory import build_upload_service

    settings.upload.max_file_size_bytes = 1024
    service = build_upload_service(session, settings=settings)

    big = make_fixture(tmp_path / "src", "big.csv", FixtureSpec(timestamp_count=10))
    _, outcomes = await service.stage_batch([("big.csv", chunks_of(big))])

    assert outcomes[0].status is UploadFileStatus.REJECTED
    assert "exceeds the configured maximum" in (outcomes[0].rejection_reason or "")


async def test_too_many_files_rejects_the_request(
    settings: Settings, tmp_path: Path, session: AsyncSession
) -> None:
    from backend.app.services.factory import build_upload_service

    settings.upload.max_files_per_batch = 2
    service = build_upload_service(session, settings=settings)
    source = make_fixture(tmp_path / "src", "a.csv", FixtureSpec(timestamp_count=3))

    with pytest.raises(UploadRejected, match="exceeds the configured maximum"):
        await service.stage_batch(
            [(f"file{i}.csv", chunks_of(source)) for i in range(3)]
        )


async def test_empty_request_is_rejected(upload_service: UploadService) -> None:
    with pytest.raises(UploadRejected, match="No files"):
        await upload_service.stage_batch([])


async def test_symlinked_staged_reference_is_refused(
    settings: Settings, tmp_path: Path
) -> None:
    """A staged reference that is a symlink must never be read.

    Covers both directions: a link pointing outside staging (caught by the escape
    check) and a link pointing inside it (caught by the symlink check). The second
    case is why the symlink test runs before ``resolve()`` - resolving would
    dereference the link and the guard could never fire.
    """
    from pipelines.sources.base import SourceFileRef, TelemetrySourceError
    from pipelines.sources.manual_upload import ManualUploadTelemetrySource

    staging = Path(settings.upload.staging_root)
    staging.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "secret.csv"
    secret.write_text("sensitive", encoding="utf-8")
    link = staging / "link.csv"
    link.symlink_to(secret)

    source = ManualUploadTelemetrySource([], staging_root=staging)

    def ref_for(path: Path) -> SourceFileRef:
        return SourceFileRef(
            source_type=SourceType.MANUAL_UPLOAD,
            reference=str(path),
            display_name=path.name,
            size_bytes=9,
            discovered_at=dt.datetime.now(dt.UTC),
        )

    # A link out of staging is refused - either guard is sufficient.
    with pytest.raises(TelemetrySourceError, match="symlink|escapes the staging root"):
        await source.metadata(ref_for(link))

    # A link whose target is inside staging still resolves inside the root, so only
    # the symlink guard can catch it.
    inside_target = staging / "real.csv"
    inside_target.write_text("data", encoding="utf-8")
    inside_link = staging / "inside-link.csv"
    inside_link.symlink_to(inside_target)
    with pytest.raises(TelemetrySourceError, match="symlink"):
        await source.metadata(ref_for(inside_link))


async def test_reference_outside_staging_is_refused(
    settings: Settings, tmp_path: Path
) -> None:
    from pipelines.sources.base import SourceFileRef, TelemetrySourceError
    from pipelines.sources.manual_upload import ManualUploadTelemetrySource

    outside = tmp_path / "outside.csv"
    outside.write_text("nope", encoding="utf-8")
    source = ManualUploadTelemetrySource(
        [], staging_root=Path(settings.upload.staging_root)
    )
    ref = SourceFileRef(
        source_type=SourceType.MANUAL_UPLOAD,
        reference=str(outside),
        display_name="outside.csv",
        size_bytes=4,
        discovered_at=dt.datetime.now(dt.UTC),
    )
    with pytest.raises(TelemetrySourceError, match="escapes the staging root"):
        await source.metadata(ref)


# ---------------------------------------------------------------------------
# Batch bookkeeping
# ---------------------------------------------------------------------------


async def test_batch_counts_are_derived_not_stored(
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    src = tmp_path / "src"
    files = [
        ("A.csv", make_fixture(src, "A.csv", FixtureSpec(timestamp_count=5))),
        (
            "B.csv",
            make_fixture(
                src,
                "B.csv",
                FixtureSpec(timestamp_count=5, start=dt.datetime(2026, 7, 28, 2, 0)),
            ),
        ),
    ]
    batch_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=files,
    )

    repo = UploadRepository(session)
    counts = await repo.batch_counts(batch_id)
    assert counts["total_files"] == 2
    assert counts["completed"] == 2
    assert counts["pending"] == 0

    # The batch row stores only delivery facts, never outcome tallies.
    batch = await repo.get_batch(batch_id)
    assert batch is not None
    assert batch.file_count == 2
    assert not hasattr(batch, "files_completed")


async def test_batch_file_rows_exist_before_processing(
    session: AsyncSession, tmp_path: Path, upload_service: UploadService
) -> None:
    """The UI can list a batch's files while the worker is still working."""
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=4))
    batch_id, _ = await upload_service.stage_batch([("HYD12.csv", chunks_of(source))])

    rows = (
        await session.execute(
            sa.select(UploadBatchFile).where(UploadBatchFile.batch_id == batch_id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status is UploadFileStatus.PENDING
    assert rows[0].telemetry_file_id is None
    assert rows[0].sha256 is not None
