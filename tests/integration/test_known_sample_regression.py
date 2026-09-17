"""Known-sample regression test (Phase 1C section 46).

The real 16.5 MB production file is not committed.  Instead this test drives the
whole pipeline over a synthetic file that reproduces every *structural* property
of it that Phase 1C has to survive:

* ~449 raw source positions, one header name duplicated
* the 2 connectors x 4 SMRs = 8 rows-per-timestamp grain
* replayed frames producing 16- and 24-row timestamps
* byte-identical duplicate rows
* same-timestamp rows whose values genuinely *differ* (must not be dropped)
* a ~121-second median cadence
* a telemetry gap
* a filename date that disagrees with the telemetry date

The assertions are stated against the fixture's declared expectations rather than
numbers copied from a previous run, so a behaviour change fails the test instead
of silently rewriting the baseline.

When ``CPI_REAL_SAMPLE_PATH`` points at the genuine file, the final test also runs
against it and reports what it actually found.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.charger_day_coverage import ChargerDayCoverage
from backend.app.models.enums import (
    ArrivalStatus,
    ChargerLifecycleStatus,
    FileStatus,
    IngestionTrigger,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.repositories.fleet import FleetRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.ingestion_service import IngestionService
from pipelines.profiling.header_parser import parse_header
from pipelines.profiling.profiler import profile_file
from pipelines.sources.filesystem import FilesystemTelemetrySource
from tests.fixtures.builders import (
    DUPLICATE_HEADER_NAME,
    TOTAL_SOURCE_POSITIONS,
    FixtureSpec,
    build_telemetry_csv,
)

pytestmark = pytest.mark.integration

TELEMETRY_DATE = dt.date(2026, 7, 27)
CHARGER = "D82510560390014"
#: The filename deliberately disagrees with the telemetry inside it.
FILENAME = "HYD12_28-07-2026.csv"


@pytest.fixture
def sample_file(settings: Settings) -> tuple[Path, object]:
    """A production-shaped file placed in the configured inbox."""
    inbox = settings.filesystem_source.inbox
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / FILENAME
    expectation = build_telemetry_csv(
        path,
        FixtureSpec(
            charger_id=CHARGER,
            ocpp_id="HYD12",
            interval_seconds=121,
            timestamp_count=120,
            connectors=(1, 2),
            smrs=(1, 2, 3, 4),
            replay_timestamp_indexes=(5, 40),
            conflicting_timestamp_indexes=(7, 60),
            triple_frame_indexes=(90,),
        ),
    )
    return path, expectation


# ---------------------------------------------------------------------------
# Structural properties of the source (Phase 1A/1B, preserved)
# ---------------------------------------------------------------------------


def test_source_shape_matches_the_known_sample(sample_file: tuple[Path, object]) -> None:
    path, _ = sample_file
    header = parse_header(path)

    assert header.field_count == TOTAL_SOURCE_POSITIONS == 449
    assert header.duplicate_header_count == 1, f"{DUPLICATE_HEADER_NAME} appears twice"
    assert header.duplicated_position_count == 2


def test_profile_reproduces_the_sample_characteristics(
    sample_file: tuple[Path, object], settings: Settings
) -> None:
    path, expectation = sample_file
    profile = profile_file(
        path,
        timestamp_formats=settings.ingest.timestamp_formats,
        source_timezone=settings.fleet.default_source_timezone,
        sentinel_values=settings.ingest.global_sentinel_values,
        header=parse_header(path),
    )

    # Topology: 2 connectors x 4 SMRs.
    assert profile.connector_count == 2
    assert profile.smr_count == 4
    assert sorted(profile.connectors) == ["1", "2"]
    assert sorted(profile.smrs) == ["1", "2", "3", "4"]

    # Cadence near the observed 121 seconds.
    assert profile.timestamps.median_interval_seconds == pytest.approx(121.0, abs=1.0)

    # The 8-rows-per-timestamp grain, with replays pushing some higher.
    rows_per_timestamp = dict(profile.duplicates.rows_per_timestamp)
    assert 8 in rows_per_timestamp, "the normal frame size must dominate"
    assert max(rows_per_timestamp) > 8, "replayed timestamps carry more than 8 rows"

    # Exact duplicates exist and are counted, not silently removed.
    assert profile.duplicates.exact_duplicate_rows > 0

    # Same-timestamp rows that genuinely differ must be visible as conflicts -
    # these are the observations Phase 1D must reconcile and must never be
    # dropped by a naive drop_duplicates.
    assert profile.duplicates.conflicting_logical_groups > 0

    # Business date comes from the telemetry, not the filename.
    assert profile.timestamps.dominant_business_date == TELEMETRY_DATE


# ---------------------------------------------------------------------------
# Full pipeline: ingest -> reconcile
# ---------------------------------------------------------------------------


async def test_full_pipeline_over_the_known_sample(
    session: AsyncSession,
    settings: Settings,
    sample_file: tuple[Path, object],
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    fleet_repo: FleetRepository,
) -> None:
    _, _ = sample_file
    await fleet_repo.upsert_charger(
        charger_id=CHARGER,
        ocpp_id="HYD12",
        site_code="SITE-HYD-001",
        lifecycle_status=ChargerLifecycleStatus.ACTIVE,
        telemetry_expected=True,
        expected_connector_count=2,
        expected_smr_count=4,
        expected_sampling_interval_seconds=121,
        source_timezone="Asia/Kolkata",
    )

    source = FilesystemTelemetrySource(
        settings.filesystem_source.inbox,
        pattern="*.csv",
        allowed_extensions=settings.ingest.allowed_extensions,
    )
    run = await ingestion_service.run(source, trigger=IngestionTrigger.TEST)

    assert run.files_discovered == 1
    assert run.files_ready == 1, "a structurally valid file must reach READY"
    assert run.files_failed == 0
    assert run.files_quarantined == 0

    telemetry_file = (await session.execute(sa.select(TelemetryFile))).scalars().one()
    assert telemetry_file.status is FileStatus.READY_FOR_NORMALIZATION
    assert telemetry_file.column_count == 449
    assert telemetry_file.connector_count_detected == 2
    assert telemetry_file.smr_count_detected == 4

    # The filename/event-date disagreement is recorded, and the event date wins.
    assert telemetry_file.filename_date == dt.date(2026, 7, 28)
    assert telemetry_file.business_date == TELEMETRY_DATE

    # Per-date contribution persisted for reconciliation.
    file_day = (await session.execute(sa.select(TelemetryFileDay))).scalars().one()
    assert file_day.charger_id == CHARGER
    assert file_day.business_date == TELEMETRY_DATE
    assert file_day.unique_timestamp_count == telemetry_file.unique_event_timestamp_count
    assert file_day.row_count > file_day.unique_timestamp_count

    summary = await coverage_service.reconcile(TELEMETRY_DATE)
    assert summary.expected_charger_count == 1
    assert summary.received_charger_count == 1
    assert summary.missing_charger_count == 0

    coverage = (
        (
            await session.execute(
                sa.select(ChargerDayCoverage).where(ChargerDayCoverage.charger_id == CHARGER)
            )
        )
        .scalars()
        .one()
    )

    assert coverage.arrival_status in {ArrivalStatus.RECEIVED, ArrivalStatus.LATE}
    assert coverage.connector_count_detected == 2
    assert coverage.smr_count_detected == 4
    assert coverage.unique_timestamp_count == file_day.unique_timestamp_count

    # The single most important invariant: raw duplication cannot inflate coverage.
    assert float(coverage.coverage_percentage or 0) <= 100.0
    assert coverage.unique_timestamp_count < (telemetry_file.row_count or 0)

    # Duplication is quantified rather than resolved - Phase 1D's job.
    assert coverage.duplicate_timestamp_count >= 0
    assert coverage.logical_collision_count > 0


async def test_pipeline_is_idempotent_over_the_same_file(
    session: AsyncSession,
    settings: Settings,
    sample_file: tuple[Path, object],
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    fleet_repo: FleetRepository,
) -> None:
    """Re-presenting identical bytes must not create a second logical file."""
    await fleet_repo.upsert_charger(
        charger_id=CHARGER,
        lifecycle_status=ChargerLifecycleStatus.ACTIVE,
        telemetry_expected=True,
        source_timezone="Asia/Kolkata",
    )
    source = FilesystemTelemetrySource(
        settings.filesystem_source.inbox,
        pattern="*.csv",
        allowed_extensions=settings.ingest.allowed_extensions,
    )

    await ingestion_service.run(source, trigger=IngestionTrigger.TEST)
    await coverage_service.reconcile(TELEMETRY_DATE)

    files_after_first = len((await session.execute(sa.select(TelemetryFile))).scalars().all())
    days_after_first = len((await session.execute(sa.select(TelemetryFileDay))).scalars().all())
    coverage_after_first = len(
        (await session.execute(sa.select(ChargerDayCoverage))).scalars().all()
    )

    second = await ingestion_service.run(source, trigger=IngestionTrigger.TEST)
    await coverage_service.reconcile(TELEMETRY_DATE)

    assert second.files_ready == 0, "nothing new should be analysed"
    assert len((await session.execute(sa.select(TelemetryFile))).scalars().all()) == (
        files_after_first
    )
    assert len((await session.execute(sa.select(TelemetryFileDay))).scalars().all()) == (
        days_after_first
    )
    assert len((await session.execute(sa.select(ChargerDayCoverage))).scalars().all()) == (
        coverage_after_first
    )


# ---------------------------------------------------------------------------
# Opt-in run against the genuine production file
# ---------------------------------------------------------------------------


@pytest.mark.real_sample
@pytest.mark.skipif(
    not os.environ.get("CPI_REAL_SAMPLE_PATH"),
    reason="CPI_REAL_SAMPLE_PATH is not set; the real charger sample is unavailable.",
)
def test_real_sample_characteristics(settings: Settings) -> None:
    """Profile the genuine file and report what is actually there.

    Assertions are deliberately loose: this test exists to *measure* the real
    file, not to enforce numbers guessed in advance.
    """
    path = Path(os.environ["CPI_REAL_SAMPLE_PATH"])
    assert path.exists(), f"CPI_REAL_SAMPLE_PATH does not exist: {path}"

    header = parse_header(path)
    profile = profile_file(
        path,
        timestamp_formats=settings.ingest.timestamp_formats,
        source_timezone=settings.fleet.default_source_timezone,
        sentinel_values=settings.ingest.global_sentinel_values,
        header=header,
    )

    print("\nREAL SAMPLE PROFILE")
    print(f"  source positions:        {header.field_count}")
    print(f"  duplicate header names:  {header.duplicate_header_count}")
    print(f"  raw rows:                {profile.row_count}")
    print(f"  unique event timestamps: {profile.timestamps.unique_count}")
    print(f"  connectors:              {sorted(profile.connectors)}")
    print(f"  SMRs:                    {sorted(profile.smrs)}")
    print(f"  median cadence (s):      {profile.timestamps.median_interval_seconds}")
    print(f"  business date:           {profile.timestamps.dominant_business_date}")
    print(f"  date span:               {profile.timestamps.date_span.value}")
    print(f"  exact duplicate rows:    {profile.duplicates.exact_duplicate_rows}")
    print(f"  logical collisions:      {profile.duplicates.logical_collision_groups}")
    print(f"  conflicting collisions:  {profile.duplicates.conflicting_logical_groups}")
    print(f"  rows per timestamp:      {dict(profile.duplicates.rows_per_timestamp)}")

    assert profile.row_count > 0
    assert profile.timestamps.unique_count > 0
    assert profile.timestamps.unique_count < profile.row_count, (
        "the raw grain must be several rows per timestamp"
    )
