"""Charger-day reconciliation against a real database (Phase 1C sections 16, 19, 24, 41, 44).

These tests drive the actual persistence path, because the properties that matter
most - idempotency, and a late file flipping MISSING to LATE in place - are
properties of the *stored* state, not of a pure function.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.charger_day_coverage import ChargerDayCoverage
from backend.app.models.data_quality_issue import DataQualityIssue
from backend.app.models.enums import (
    ArrivalStatus,
    ChargerLifecycleStatus,
    CompletenessStatus,
    FileStatus,
    QualityIssueType,
    QualityRuleScope,
    SourceType,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.models.telemetry_gap import TelemetryGap
from backend.app.repositories.fleet import FleetRepository
from backend.app.services.coverage_service import CoverageService

pytestmark = pytest.mark.integration

BUSINESS_DATE = dt.date(2026, 8, 10)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CHARGER = "D82510560390014"


# ---------------------------------------------------------------------------
# Helpers that write realistic Bronze state
# ---------------------------------------------------------------------------


async def add_file(
    session: AsyncSession,
    *,
    charger_id: str = CHARGER,
    business_date: dt.date = BUSINESS_DATE,
    start_second: int = 0,
    count: int = 720,
    step: int = 120,
    received_at: dt.datetime | None = None,
    status: FileStatus = FileStatus.READY_FOR_NORMALIZATION,
    filename: str | None = None,
    filename_date: dt.date | None = None,
    connectors: tuple[str, ...] = ("1", "2"),
    smrs: tuple[str, ...] = ("1", "2", "3", "4"),
    rows_per_timestamp: int = 8,
) -> TelemetryFile:
    """Register a file plus its per-date contribution, as ingestion would."""
    file_id = uuid4()
    received = received_at or dt.datetime(2026, 8, 11, 2, 0, tzinfo=dt.UTC)
    name = filename or f"{charger_id}_{business_date.isoformat()}.csv"

    offsets = [start_second + i * step for i in range(count)]
    midnight = dt.datetime.combine(business_date, dt.time.min, tzinfo=IST)

    telemetry_file = TelemetryFile(
        id=file_id,
        source_type=SourceType.FILESYSTEM,
        original_filename=name,
        source_reference=f"/inbox/{name}",
        storage_reference=f"raw/{file_id}",
        sha256=uuid4().hex + uuid4().hex[:32],
        file_size_bytes=1024,
        status=status,
        received_at=received,
        discovered_at=received,
        business_date=business_date,
        filename_date=filename_date,
        row_count=count * rows_per_timestamp,
        unique_event_timestamp_count=count,
    )
    session.add(telemetry_file)
    await session.flush()

    session.add(
        TelemetryFileDay(
            id=uuid4(),
            telemetry_file_id=file_id,
            charger_id=charger_id,
            business_date=business_date,
            first_event_at=(midnight + dt.timedelta(seconds=offsets[0])).astimezone(dt.UTC),
            last_event_at=(midnight + dt.timedelta(seconds=offsets[-1])).astimezone(dt.UTC),
            unique_timestamp_count=count,
            row_count=count * rows_per_timestamp,
            event_second_offsets=offsets,
            connectors_seen=list(connectors),
            smrs_seen=list(smrs),
            source_timezone="Asia/Kolkata",
        )
    )
    await session.flush()
    return telemetry_file


async def register(
    fleet: FleetRepository,
    charger_id: str,
    *,
    lifecycle: ChargerLifecycleStatus = ChargerLifecycleStatus.ACTIVE,
    expected: bool = True,
    **extra: object,
) -> None:
    await fleet.upsert_charger(
        charger_id=charger_id,
        ocpp_id=charger_id,
        site_code="SITE-A",
        lifecycle_status=lifecycle,
        telemetry_expected=expected,
        expected_connector_count=2,
        expected_smr_count=4,
        expected_sampling_interval_seconds=120,
        source_timezone="Asia/Kolkata",
        **extra,
    )


async def coverage_for(session: AsyncSession, charger_id: str) -> ChargerDayCoverage:
    result = await session.execute(
        sa.select(ChargerDayCoverage).where(
            ChargerDayCoverage.charger_id == charger_id,
            ChargerDayCoverage.business_date == BUSINESS_DATE,
        )
    )
    return result.scalars().one()


async def count_of(session: AsyncSession, model: type) -> int:
    return int((await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one())


async def daily_rule_codes(session: AsyncSession, charger_id: str) -> set[str]:
    rows = await session.execute(
        sa.select(DataQualityIssue.rule_code).where(
            DataQualityIssue.charger_id == charger_id,
            DataQualityIssue.scope == QualityRuleScope.CHARGER_DAY,
        )
    )
    return {code.value for (code,) in rows.all()}


# ---------------------------------------------------------------------------
# Missing charger detection (section 16)
# ---------------------------------------------------------------------------


async def test_expected_charger_with_no_data_becomes_missing(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, "HYD44")
    summary = await coverage_service.reconcile(BUSINESS_DATE)

    assert summary.expected_charger_count == 1
    assert summary.missing_charger_count == 1

    row = await coverage_for(session, "HYD44")
    assert row.arrival_status is ArrivalStatus.MISSING
    assert row.completeness_status is CompletenessStatus.NO_DATA
    assert row.coverage_percentage == 0
    assert row.expected is True

    assert QualityIssueType.MISSING_CHARGER_DATA.value in await daily_rule_codes(session, "HYD44")


async def test_decommissioned_charger_is_not_missing(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Not every registered charger is expected every day (section 7)."""
    await register(fleet_repo, "OLD01", lifecycle=ChargerLifecycleStatus.DECOMMISSIONED)
    await register(fleet_repo, "TEST01", lifecycle=ChargerLifecycleStatus.TEST)
    await register(fleet_repo, "PAUSED01", lifecycle=ChargerLifecycleStatus.TEMPORARILY_INACTIVE)
    await register(fleet_repo, "DISABLED01", expected=False)

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.expected_charger_count == 0
    assert summary.missing_charger_count == 0


async def test_telemetry_window_bounds_expectation(
    fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    day = dt.timedelta(days=1)
    await register(fleet_repo, "FUTURE01", telemetry_start_date=BUSINESS_DATE + 5 * day)
    await register(fleet_repo, "RETIRED01", telemetry_end_date=BUSINESS_DATE - day)
    await register(fleet_repo, "INWINDOW", telemetry_start_date=BUSINESS_DATE)

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.expected_charger_count == 1
    assert summary.missing_charger_count == 1


async def test_unexpected_charger_is_recorded_but_excluded_from_expectation(
    session: AsyncSession, coverage_service: CoverageService
) -> None:
    """Telemetry from a charger absent from the registry (section 6)."""
    await add_file(session, charger_id="GHOST01")
    summary = await coverage_service.reconcile(BUSINESS_DATE)

    assert summary.unexpected_charger_count == 1
    assert summary.expected_charger_count == 0

    row = await coverage_for(session, "GHOST01")
    assert row.arrival_status is ArrivalStatus.UNEXPECTED
    assert row.expected is False


# ---------------------------------------------------------------------------
# Complete / partial charger-days
# ---------------------------------------------------------------------------


async def test_single_file_complete_day(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720)

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.complete_count == 1
    assert summary.received_charger_count == 1

    row = await coverage_for(session, CHARGER)
    assert row.completeness_status is CompletenessStatus.COMPLETE
    assert row.unique_timestamp_count == 720
    assert float(row.coverage_percentage or 0) == pytest.approx(100.0)
    assert row.connector_count_detected == 2
    assert row.smr_count_detected == 4
    assert row.gap_count == 0


async def test_raw_rows_never_inflate_stored_coverage(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Section 11, end to end: 8 rows per timestamp must not read as 800%."""
    await register(fleet_repo, CHARGER)
    await add_file(session, count=360, rows_per_timestamp=8)

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.unique_timestamp_count == 360
    assert float(row.coverage_percentage or 0) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Multiple files per charger-day (section 19)
# ---------------------------------------------------------------------------


async def test_two_files_combine_into_one_complete_charger_day(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, start_second=0, count=360)  # 00:00-12:00
    await add_file(session, start_second=43_200, count=360)  # 12:00-24:00

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.file_count == 2
    assert row.unique_timestamp_count == 720
    assert row.completeness_status is CompletenessStatus.COMPLETE
    assert QualityIssueType.MULTIPLE_FILES_SAME_CHARGER_DAY.value in await daily_rule_codes(
        session, CHARGER
    )


async def test_overlapping_files_are_quantified(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Section 20: overlap counted, observations not deleted."""
    await register(fleet_repo, CHARGER)
    await add_file(session, start_second=0, count=360)
    await add_file(session, start_second=21_600, count=360)  # 6h overlap

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.overlapping_timestamp_count > 0
    assert row.unique_timestamp_count == 540
    assert QualityIssueType.OVERLAPPING_FILE_COVERAGE.value in await daily_rule_codes(
        session, CHARGER
    )


async def test_quarantined_file_does_not_contribute(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Section 43: an unusable file contributes nothing, but breaks nothing."""
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, status=FileStatus.QUARANTINED)

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.missing_charger_count == 1

    row = await coverage_for(session, CHARGER)
    assert row.arrival_status is ArrivalStatus.MISSING


@pytest.mark.parametrize(
    "status",
    [
        FileStatus.READY_FOR_NORMALIZATION,
        FileStatus.FRAME_RECONSTRUCTION,
        FileStatus.FRAMES_RECONSTRUCTED,
        FileStatus.COMPLETED,
        FileStatus.PARTIAL,
    ],
)
async def test_a_processed_file_keeps_contributing_at_every_usable_state(
    session: AsyncSession,
    fleet_repo: FleetRepository,
    coverage_service: CoverageService,
    status: FileStatus,
) -> None:
    """Progress through the pipeline must not erase a charger-day (regression).

    Reconciliation is idempotent and runs again whenever late data arrives. When
    Phase 1D added FRAMES_RECONSTRUCTED without adding it here, the *second*
    reconciliation of an already-reconstructed day reported the charger MISSING with
    0% coverage - the file was intact, the file-days were intact, and the fleet view
    said nothing had arrived.

    Usability is about whether the profile can be trusted, not about how far the file
    has travelled.
    """
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, status=status)

    summary = await coverage_service.reconcile(BUSINESS_DATE)

    assert summary.received_charger_count == 1, f"{status} stopped contributing"
    assert summary.missing_charger_count == 0
    row = await coverage_for(session, CHARGER)
    assert row.arrival_status is ArrivalStatus.RECEIVED
    assert row.coverage_percentage is not None
    assert float(row.coverage_percentage) > 99.0


async def test_reconciling_after_frame_reconstruction_preserves_coverage(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """The exact production sequence that surfaced the defect.

    Ingest, reconcile, let Phase 1D advance the file, then reconcile again - which is
    what any later run does, whether triggered by a late file, another upload batch,
    or an operator recomputing a date.
    """
    await register(fleet_repo, CHARGER)
    telemetry_file = await add_file(session, count=720)

    before = await coverage_service.reconcile(BUSINESS_DATE)
    assert before.received_charger_count == 1

    # Phase 1D advances the file once its frames exist.
    telemetry_file.status = FileStatus.FRAMES_RECONSTRUCTED
    await session.flush()

    after = await coverage_service.reconcile(BUSINESS_DATE)

    assert after.received_charger_count == 1
    assert after.missing_charger_count == 0
    assert after.fleet_coverage_percentage == before.fleet_coverage_percentage
    row = await coverage_for(session, CHARGER)
    assert row.arrival_status is ArrivalStatus.RECEIVED
    assert row.completeness_status is not CompletenessStatus.NO_DATA


# ---------------------------------------------------------------------------
# Late arrival (section 17)
# ---------------------------------------------------------------------------


async def test_late_file_is_flagged_from_receipt_time(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, received_at=dt.datetime(2026, 8, 14, 9, 0, tzinfo=dt.UTC))

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.late_charger_count == 1
    assert summary.received_charger_count == 1

    row = await coverage_for(session, CHARGER)
    assert row.arrival_status is ArrivalStatus.LATE
    assert row.late_by_seconds is not None and row.late_by_seconds > 0
    assert QualityIssueType.LATE_FILE.value in await daily_rule_codes(session, CHARGER)


async def test_on_time_file_is_not_late(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, received_at=dt.datetime(2026, 8, 11, 6, 0, tzinfo=dt.UTC))

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)
    assert row.arrival_status is ArrivalStatus.RECEIVED


# ---------------------------------------------------------------------------
# Reconciliation after late arrival (section 24) - the headline behaviour
# ---------------------------------------------------------------------------


async def test_late_arrival_flips_missing_to_late_in_place(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """MISSING -> LATE with no duplicated state (sections 24, 41)."""
    await register(fleet_repo, CHARGER)

    first = await coverage_service.reconcile(BUSINESS_DATE)
    assert first.missing_charger_count == 1
    original = await coverage_for(session, CHARGER)
    original_id = original.id
    assert original.arrival_status is ArrivalStatus.MISSING
    assert await count_of(session, ChargerDayCoverage) == 1

    # The file finally turns up, days late.
    await add_file(session, count=720, received_at=dt.datetime(2026, 8, 15, 3, 0, tzinfo=dt.UTC))
    second = await coverage_service.reconcile(BUSINESS_DATE)

    assert second.missing_charger_count == 0
    assert second.late_charger_count == 1
    assert second.complete_count == 1

    session.expire_all()
    updated = await coverage_for(session, CHARGER)
    assert updated.id == original_id, "the same coverage row must be updated, not replaced"
    assert updated.arrival_status is ArrivalStatus.LATE
    assert updated.completeness_status is CompletenessStatus.COMPLETE
    assert await count_of(session, ChargerDayCoverage) == 1

    # The MISSING finding must be gone, replaced by the LATE one.
    codes = await daily_rule_codes(session, CHARGER)
    assert QualityIssueType.MISSING_CHARGER_DATA.value not in codes
    assert QualityIssueType.LATE_FILE.value in codes


# ---------------------------------------------------------------------------
# Idempotency (section 41) and gap recomputation (section 44)
# ---------------------------------------------------------------------------


async def test_reconciliation_is_idempotent(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await register(fleet_repo, "HYD44")
    await add_file(session, count=200)  # partial, so gaps and findings exist

    first = await coverage_service.reconcile(BUSINESS_DATE)
    counts = (
        await count_of(session, ChargerDayCoverage),
        await count_of(session, TelemetryGap),
        await count_of(session, DataQualityIssue),
    )

    for _ in range(3):
        again = await coverage_service.reconcile(BUSINESS_DATE)
        assert (
            await count_of(session, ChargerDayCoverage),
            await count_of(session, TelemetryGap),
            await count_of(session, DataQualityIssue),
        ) == counts
        assert again.as_dict() == first.as_dict()


async def test_gaps_are_recomputed_not_accumulated(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Section 44: a filled gap must disappear, not linger."""
    await register(fleet_repo, CHARGER)
    # Morning only, leaving a large hole for the rest of the day.
    await add_file(session, start_second=0, count=120)

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)
    assert row.gap_count == 0, "trailing absence is not an inter-sample gap"

    # A second window arrives, creating a genuine mid-day gap.
    await add_file(session, start_second=50_000, count=120)
    await coverage_service.reconcile(BUSINESS_DATE)
    session.expire_all()
    row = await coverage_for(session, CHARGER)
    assert row.gap_count == 1
    gap_total = await count_of(session, TelemetryGap)
    assert gap_total == 1

    # Now fill the middle: the gap must be gone entirely.
    await add_file(session, start_second=14_400, count=297, step=120)
    await coverage_service.reconcile(BUSINESS_DATE)
    session.expire_all()
    row = await coverage_for(session, CHARGER)
    assert row.gap_count == 0
    assert await count_of(session, TelemetryGap) == 0, "stale gap rows must not survive"


async def test_gap_rows_carry_provenance(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, start_second=0, count=60)
    await add_file(session, start_second=60_000, count=60)
    await coverage_service.reconcile(BUSINESS_DATE)

    gap = (await session.execute(sa.select(TelemetryGap))).scalars().one()
    assert gap.charger_id == CHARGER
    assert gap.business_date == BUSINESS_DATE
    assert gap.end_event_at > gap.start_event_at
    assert gap.duration_seconds > 0
    assert gap.expected_interval_seconds == 120
    assert gap.charger_pk is not None


# ---------------------------------------------------------------------------
# Topology coverage (sections 26, 27)
# ---------------------------------------------------------------------------


async def test_missing_expected_connector_is_flagged(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, connectors=("1",))

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.connector_count_detected == 1
    assert row.expected_connector_count == 2
    assert QualityIssueType.MISSING_EXPECTED_CONNECTOR.value in await daily_rule_codes(
        session, CHARGER
    )


async def test_missing_expected_smr_is_flagged(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, smrs=("1", "2", "3"))

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.smr_count_detected == 3
    assert row.expected_smr_count == 4
    assert QualityIssueType.MISSING_EXPECTED_SMR.value in await daily_rule_codes(session, CHARGER)


async def test_full_topology_raises_no_topology_findings(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720)
    await coverage_service.reconcile(BUSINESS_DATE)

    codes = await daily_rule_codes(session, CHARGER)
    assert QualityIssueType.MISSING_EXPECTED_CONNECTOR.value not in codes
    assert QualityIssueType.MISSING_EXPECTED_SMR.value not in codes


# ---------------------------------------------------------------------------
# Filename mismatch (section 29)
# ---------------------------------------------------------------------------


async def test_filename_date_mismatch_is_a_warning_not_a_failure(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(
        session,
        count=720,
        filename="HYD12_11-08-2026.csv",
        filename_date=BUSINESS_DATE + dt.timedelta(days=1),
    )

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    # The event date wins; the day is still COMPLETE.
    assert row.business_date == BUSINESS_DATE
    assert row.completeness_status is CompletenessStatus.COMPLETE

    finding = (
        (
            await session.execute(
                sa.select(DataQualityIssue).where(
                    DataQualityIssue.rule_code == QualityIssueType.EVENT_DATE_FILENAME_MISMATCH
                )
            )
        )
        .scalars()
        .one()
    )
    assert finding.severity.value in {"INFO", "WARNING"}, "must never be fatal"


async def test_matching_filename_date_raises_no_finding(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=720, filename_date=BUSINESS_DATE)
    await coverage_service.reconcile(BUSINESS_DATE)
    codes = await daily_rule_codes(session, CHARGER)
    assert QualityIssueType.EVENT_DATE_FILENAME_MISMATCH.value not in codes


# ---------------------------------------------------------------------------
# Cadence findings and fleet aggregation
# ---------------------------------------------------------------------------


async def test_abnormal_cadence_is_flagged(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, count=100, step=900)  # 15-minute cadence vs 120s expected

    await coverage_service.reconcile(BUSINESS_DATE)
    assert QualityIssueType.ABNORMAL_SAMPLING_INTERVAL.value in await daily_rule_codes(
        session, CHARGER
    )


async def test_fleet_coverage_counts_missing_chargers_as_zero(
    fleet_repo: FleetRepository, coverage_service: CoverageService, session: AsyncSession
) -> None:
    """Section 39: excluding missing chargers would flatter the fleet."""
    await register(fleet_repo, CHARGER)
    await register(fleet_repo, "HYD44")
    await add_file(session, count=720)  # one charger perfect, one silent

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert summary.expected_charger_count == 2
    assert summary.fleet_coverage_percentage == pytest.approx(50.0, abs=0.01)
    assert summary.delivery_rate == pytest.approx(50.0, abs=0.01)


async def test_charger_cadence_override_changes_expected_count(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """Section 10 precedence: the charger's own interval wins over the default."""
    await fleet_repo.upsert_charger(
        charger_id=CHARGER,
        ocpp_id=CHARGER,
        site_code="SITE-A",
        lifecycle_status=ChargerLifecycleStatus.ACTIVE,
        telemetry_expected=True,
        expected_sampling_interval_seconds=300,
        source_timezone="Asia/Kolkata",
    )
    await add_file(session, count=288, step=300)

    await coverage_service.reconcile(BUSINESS_DATE)
    row = await coverage_for(session, CHARGER)

    assert row.expected_sampling_interval_seconds == 300
    assert row.expected_timestamp_count == 86_400 // 300
    assert row.completeness_status is CompletenessStatus.COMPLETE


async def test_reconcile_dates_handles_several_days(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, business_date=BUSINESS_DATE, count=720)
    await add_file(session, business_date=BUSINESS_DATE + dt.timedelta(days=1), count=360)

    summaries = await coverage_service.reconcile_dates(
        [BUSINESS_DATE + dt.timedelta(days=1), BUSINESS_DATE]
    )
    assert [s.business_date for s in summaries] == [
        BUSINESS_DATE,
        BUSINESS_DATE + dt.timedelta(days=1),
    ], "dates are processed in ascending order regardless of input order"
    assert summaries[0].complete_count == 1
    assert summaries[1].partial_count == 1


async def test_coverage_ids_are_returned_for_every_charger_day(
    fleet_repo: FleetRepository, coverage_service: CoverageService, session: AsyncSession
) -> None:
    await register(fleet_repo, CHARGER)
    await register(fleet_repo, "HYD44")
    await add_file(session, count=10)

    summary = await coverage_service.reconcile(BUSINESS_DATE)
    assert set(summary.coverage_ids) == {CHARGER, "HYD44"}
    assert all(isinstance(value, UUID) for value in summary.coverage_ids.values())
