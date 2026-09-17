"""Frame persistence, provenance and idempotency (Phase 1D sections 62, 63, 65).

Drives the real service against a real database, because the properties that
matter here - idempotency, cross-file replay attribution and traceability back to
source rows - are properties of the *stored* state.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.data_quality_issue import DataQualityIssue
from backend.app.models.enums import (
    ChargerLifecycleStatus,
    DuplicateClassification,
    FileStatus,
    FrameStatus,
    QualityRuleScope,
    SourceType,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_frame import (
    TelemetryFrameRow,
    TelemetryFrameSource,
    TelemetrySourceFrame,
)
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.frames import FrameRepository
from backend.app.services.frame_service import FrameReconstructionService
from pipelines.frame_reconstruction.models import RECONSTRUCTION_VERSION
from tests.fixtures.builders import FixtureSpec, build_telemetry_csv

pytestmark = pytest.mark.integration

CHARGER = "D82510560390014"
BUSINESS_DATE = dt.date(2026, 7, 27)


async def register_file(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    *,
    filename: str,
    spec: FixtureSpec,
) -> TelemetryFile:
    """Land a fixture CSV in Bronze and register it, as ingestion would."""
    from pipelines.persistence.storage import LocalFilesystemRawStorage

    assert isinstance(storage, LocalFilesystemRawStorage)

    staging = settings.storage.raw_root.parent / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    source_path = staging / filename
    expectation = build_telemetry_csv(source_path, spec)

    async def chunks() -> object:
        yield source_path.read_bytes()

    from uuid import uuid4

    file_id = uuid4()
    stored = await storage.store(
        chunks(),  # type: ignore[arg-type]
        file_id=file_id,
        original_filename=filename,
    )

    telemetry_file = TelemetryFile(
        id=file_id,
        source_type=SourceType.FILESYSTEM,
        original_filename=filename,
        source_reference=str(source_path),
        storage_reference=stored.storage_reference,
        sha256=stored.sha256,
        file_size_bytes=stored.size_bytes,
        status=FileStatus.READY_FOR_NORMALIZATION,
        business_date=BUSINESS_DATE,
        # Profiling sets these during real ingestion; the helper mirrors it so the
        # raw-vs-unique contrast the API reports is populated.
        row_count=expectation.row_count,
        unique_event_timestamp_count=expectation.unique_timestamp_count,
    )
    session.add(telemetry_file)
    await session.flush()
    return telemetry_file


async def register_charger(fleet: FleetRepository) -> None:
    await fleet.upsert_charger(
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


async def count_of(session: AsyncSession, model: type) -> int:
    return int((await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one())


# ---------------------------------------------------------------------------
# End-to-end persistence
# ---------------------------------------------------------------------------


async def test_reconstruct_file_persists_frames_and_provenance(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=20, interval_seconds=121),
    )

    result = await frame_service.reconstruct_file(telemetry_file)

    assert result.succeeded
    assert result.charger_id == CHARGER
    assert result.outcome is not None
    assert result.frames_persisted > 0

    # Topology came from the registry, not a hard-coded 2x4.
    assert result.outcome.topology.expected_position_count == 8

    # The lifecycle advanced through the Phase 1D states.
    assert telemetry_file.status is FileStatus.FRAMES_RECONSTRUCTED

    frames = (await session.execute(sa.select(TelemetrySourceFrame))).scalars().all()
    assert len(frames) == result.frames_persisted
    assert all(frame.reconstruction_version == RECONSTRUCTION_VERSION for frame in frames)
    assert all(frame.business_date == BUSINESS_DATE for frame in frames)
    assert all(frame.charger_pk is not None for frame in frames), "linked to the registry"

    # Every frame has at least one source file and its rows.
    assert await count_of(session, TelemetryFrameSource) >= len(frames)
    assert await count_of(session, TelemetryFrameRow) > 0


async def test_provenance_traces_frame_to_file_to_source_rows(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """Section 11 of the report: frame -> source file -> raw rows."""
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=10, interval_seconds=121),
    )
    await frame_service.reconstruct_file(telemetry_file)

    repo = FrameRepository(session)
    complete = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame)
                .where(TelemetrySourceFrame.frame_status == FrameStatus.COMPLETE)
                .limit(1)
            )
        )
        .scalars()
        .one()
    )

    frame = await repo.get(complete.id)
    assert frame is not None

    # frame -> file
    assert len(frame.sources) == 1
    source = frame.sources[0]
    assert source.telemetry_file_id == telemetry_file.id
    assert source.is_primary_source is True
    assert source.first_source_row <= source.last_source_row

    # frame -> raw rows, with logical position and fingerprint
    assert len(frame.frame_rows) == 8
    positions = {row.logical_position for row in frame.frame_rows}
    assert positions == {f"C{c}/S{s}" for c in ("1", "2") for s in ("1", "2", "3", "4")}
    for row in frame.frame_rows:
        assert row.telemetry_file_id == telemetry_file.id
        assert row.source_row_number >= 0
        assert len(row.row_fingerprint) == 64  # sha256 hex
        assert row.connector_id and row.smr_id

    # The rows are traceable back into the file's original ordering.
    assert min(r.source_row_number for r in frame.frame_rows) == source.first_source_row


async def test_replay_frames_point_at_their_canonical_frame(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    # The builder's replay_timestamp_indexes duplicates a frame byte-identically.
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_replay.csv",
        spec=FixtureSpec(
            timestamp_count=12,
            interval_seconds=121,
            replay_timestamp_indexes=(3,),
            conflicting_timestamp_indexes=(),
        ),
    )
    await frame_service.reconstruct_file(telemetry_file)

    replays = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame).where(
                    TelemetrySourceFrame.duplicate_classification
                    == DuplicateClassification.FULL_FRAME_REPLAY
                )
            )
        )
        .scalars()
        .all()
    )

    assert replays, "the fixture contains a byte-identical replayed frame"
    for replay in replays:
        assert replay.replay_of_frame_id is not None
        assert replay.is_canonical is False

        canonical = await session.get(TelemetrySourceFrame, replay.replay_of_frame_id)
        assert canonical is not None
        # Same payload, earlier sequence, and the replay's rows still exist.
        assert canonical.frame_fingerprint == replay.frame_fingerprint
        assert canonical.frame_sequence < replay.frame_sequence
        assert canonical.event_time == replay.event_time


async def test_same_timestamp_distinct_frames_persist_as_two_canonical_rows(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """The critical case, end to end through the database."""
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_collision.csv",
        spec=FixtureSpec(
            timestamp_count=12,
            interval_seconds=121,
            replay_timestamp_indexes=(),
            conflicting_timestamp_indexes=(5,),
        ),
    )
    await frame_service.reconstruct_file(telemetry_file)

    distinct = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame).where(
                    TelemetrySourceFrame.duplicate_classification
                    == DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME
                )
            )
        )
        .scalars()
        .all()
    )
    assert distinct, "the fixture contains a differing frame at one timestamp"

    for frame in distinct:
        siblings = (
            (
                await session.execute(
                    sa.select(TelemetrySourceFrame).where(
                        TelemetrySourceFrame.charger_id == frame.charger_id,
                        TelemetrySourceFrame.event_time == frame.event_time,
                    )
                )
            )
            .scalars()
            .all()
        )

        # Both frames survive at the same event_time, separated only by sequence.
        assert len(siblings) >= 2
        assert len({s.frame_sequence for s in siblings}) == len(siblings)
        assert all(s.event_time == frame.event_time for s in siblings)
        # No fabricated sub-second component.
        assert all(s.event_time.microsecond == 0 for s in siblings)
        # Both are canonical - Phase 1E must consume both.
        assert frame.is_canonical
        assert frame.replay_of_frame_id is None


# ---------------------------------------------------------------------------
# Section 63 - idempotency
# ---------------------------------------------------------------------------


async def test_reconstruction_is_idempotent(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=15, interval_seconds=121),
    )

    first = await frame_service.reconstruct_file(telemetry_file, advance_lifecycle=False)
    counts = (
        await count_of(session, TelemetrySourceFrame),
        await count_of(session, TelemetryFrameSource),
        await count_of(session, TelemetryFrameRow),
        await count_of(session, DataQualityIssue),
    )

    for _ in range(3):
        again = await frame_service.reconstruct_file(telemetry_file, advance_lifecycle=False)
        assert (
            await count_of(session, TelemetrySourceFrame),
            await count_of(session, TelemetryFrameSource),
            await count_of(session, TelemetryFrameRow),
            await count_of(session, DataQualityIssue),
        ) == counts
        assert again.frames_persisted == first.frames_persisted
        assert again.outcome is not None and first.outcome is not None
        assert again.outcome.metrics.canonical_frames == first.outcome.metrics.canonical_frames


async def test_frame_sequences_are_stable_across_reruns(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """Section 64: deterministic sequencing for immutable input."""
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=12, interval_seconds=121),
    )

    async def fingerprints() -> list[tuple[dt.datetime, int, str]]:
        rows = await session.execute(
            sa.select(
                TelemetrySourceFrame.event_time,
                TelemetrySourceFrame.frame_sequence,
                TelemetrySourceFrame.frame_fingerprint,
            ).order_by(TelemetrySourceFrame.event_time, TelemetrySourceFrame.frame_sequence)
        )
        return [(row[0], row[1], row[2]) for row in rows.all()]

    await frame_service.reconstruct_file(telemetry_file, advance_lifecycle=False)
    before = await fingerprints()

    await frame_service.reconstruct_file(telemetry_file, advance_lifecycle=False)
    after = await fingerprints()

    assert before == after
    assert before, "the fixture produced frames"


# ---------------------------------------------------------------------------
# Section 62 - cross-file replay
# ---------------------------------------------------------------------------


async def test_identical_frames_in_two_files_share_one_canonical_frame(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """Two overlapping files carrying the same telemetry (section 23, 24).

    The second file must add a *source mapping* to the existing canonical frame,
    not a duplicate frame - otherwise overlapping daily files would double-count
    every observation they share.
    """
    await register_charger(fleet_repo)
    spec = FixtureSpec(
        timestamp_count=10,
        interval_seconds=121,
        replay_timestamp_indexes=(),
        conflicting_timestamp_indexes=(),
    )

    file_a = await register_file(session, settings, storage, filename="HYD12_A.csv", spec=spec)
    result_a = await frame_service.reconstruct_file(file_a, advance_lifecycle=False)
    frames_after_a = await count_of(session, TelemetrySourceFrame)
    assert frames_after_a == result_a.frames_persisted > 0

    # Same telemetry content, different filename.
    file_b = await register_file(session, settings, storage, filename="HYD12_B.csv", spec=spec)
    result_b = await frame_service.reconstruct_file(file_b, advance_lifecycle=False)

    # No new frames: every payload was already known.
    assert await count_of(session, TelemetrySourceFrame) == frames_after_a
    assert result_b.frames_persisted == 0
    assert result_b.frames_reused_from_other_files == frames_after_a

    # Both files are recorded as sources of the shared frames.
    sample = (await session.execute(sa.select(TelemetrySourceFrame).limit(1))).scalars().one()
    repo = FrameRepository(session)
    frame = await repo.get(sample.id)
    assert frame is not None
    file_ids = {source.telemetry_file_id for source in frame.sources}
    assert file_ids == {file_a.id, file_b.id}
    assert sum(1 for s in frame.sources if s.is_primary_source) == 1


async def test_reconstructing_one_file_does_not_destroy_a_shared_frame(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """Re-running file B must leave file A's canonical frames intact."""
    await register_charger(fleet_repo)
    spec = FixtureSpec(
        timestamp_count=8,
        interval_seconds=121,
        replay_timestamp_indexes=(),
        conflicting_timestamp_indexes=(),
    )
    file_a = await register_file(session, settings, storage, filename="HYD12_A.csv", spec=spec)
    file_b = await register_file(session, settings, storage, filename="HYD12_B.csv", spec=spec)

    await frame_service.reconstruct_file(file_a, advance_lifecycle=False)
    await frame_service.reconstruct_file(file_b, advance_lifecycle=False)
    total = await count_of(session, TelemetrySourceFrame)

    # Re-run B only.
    await frame_service.reconstruct_file(file_b, advance_lifecycle=False)

    assert await count_of(session, TelemetrySourceFrame) == total
    # A's primary sources survived.
    primaries = await session.execute(
        sa.select(sa.func.count())
        .select_from(TelemetryFrameSource)
        .where(
            TelemetryFrameSource.telemetry_file_id == file_a.id,
            TelemetryFrameSource.is_primary_source.is_(True),
        )
    )
    assert int(primaries.scalar_one()) == total


# ---------------------------------------------------------------------------
# Quality integration
# ---------------------------------------------------------------------------


async def test_frame_findings_use_the_existing_quality_framework(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=15, interval_seconds=121),
    )
    result = await frame_service.reconstruct_file(telemetry_file)

    findings = (
        (
            await session.execute(
                sa.select(DataQualityIssue).where(DataQualityIssue.scope == QualityRuleScope.FRAME)
            )
        )
        .scalars()
        .all()
    )

    assert findings, "the fixture's replays and collisions produce findings"
    assert len(findings) == result.findings_persisted
    # Aggregated per rule code, not one row per frame.
    assert len(findings) < (result.outcome.metrics.frames_reconstructed if result.outcome else 0)
    for finding in findings:
        assert finding.telemetry_file_id == telemetry_file.id
        assert finding.occurrence_count >= 1
        assert finding.entity_reference == RECONSTRUCTION_VERSION


async def test_frame_findings_do_not_clobber_file_scope_findings(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    """FRAME-scope replacement must leave Phase 1A/1B findings alone."""
    from uuid import uuid4

    from backend.app.models.enums import QualityIssueType, QualitySeverity

    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=8, interval_seconds=121),
    )

    session.add(
        DataQualityIssue(
            id=uuid4(),
            telemetry_file_id=telemetry_file.id,
            rule_code=QualityIssueType.SENTINEL_VALUE,
            scope=QualityRuleScope.FIELD,
            severity=QualitySeverity.INFO,
            message="pre-existing file-scope finding",
            occurrence_count=3,
            issue_hash="a" * 64,
        )
    )
    await session.flush()

    await frame_service.reconstruct_file(telemetry_file)

    survivor = await session.execute(
        sa.select(sa.func.count())
        .select_from(DataQualityIssue)
        .where(DataQualityIssue.scope == QualityRuleScope.FIELD)
    )
    assert int(survivor.scalar_one()) == 1, "the FIELD-scope finding must survive"


# ---------------------------------------------------------------------------
# Repository read paths
# ---------------------------------------------------------------------------


async def test_file_summary_reports_measured_counts(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=15, interval_seconds=121),
    )
    result = await frame_service.reconstruct_file(telemetry_file)

    summary = await FrameRepository(session).file_summary(telemetry_file.id)
    assert result.outcome is not None
    assert summary["frames_reconstructed"] == result.outcome.metrics.frames_reconstructed
    assert summary["canonical_frames"] == result.outcome.metrics.canonical_frames
    assert summary["expected_positions_per_frame"] == 8
    assert summary["unique_timestamps"] == result.outcome.metrics.unique_timestamps


async def test_charger_day_summary_complements_coverage(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(timestamp_count=15, interval_seconds=121),
    )
    await frame_service.reconstruct_file(telemetry_file)

    summary = await FrameRepository(session).charger_day_summary(CHARGER, BUSINESS_DATE)
    assert summary["frames_total"] > 0
    assert summary["canonical_frame_count"] > 0
    assert summary["canonical_frame_count"] <= summary["frames_total"]


async def test_frames_at_returns_a_collision_group(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_collision.csv",
        spec=FixtureSpec(
            timestamp_count=10,
            interval_seconds=121,
            replay_timestamp_indexes=(),
            conflicting_timestamp_indexes=(4,),
        ),
    )
    await frame_service.reconstruct_file(telemetry_file)

    repo = FrameRepository(session)
    collisions = await repo.collision_timestamps(CHARGER, BUSINESS_DATE)
    assert collisions, "the fixture creates one collision timestamp"

    event_time, frame_count = collisions[0]
    frames = await repo.frames_at(CHARGER, event_time)
    assert len(frames) >= frame_count
    assert [f.frame_sequence for f in frames] == sorted(f.frame_sequence for f in frames)
