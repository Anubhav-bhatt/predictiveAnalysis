"""Upload API behaviour (Phase 1C.5 sections 10, 11, 29-31).

The key assertion is that the upload endpoint **returns before processing**: it
answers 202 with a batch id, and the batch is REGISTERED (staged and queued), not
COMPLETED. Holding the connection open through profiling would time out a real
backfill.

These tests deliberately use **independent sessions per request**, with the same
read/write commit semantics as production, rather than one shared session for the
whole test. A shared session hides the failure that matters most here: an upload
that answers 202 while its transaction is later rolled back, leaving staged bytes on
disk and no batch for the worker to find. That bug shipped past a shared-session
suite once; this fixture is why it cannot again.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.app.api.deps import get_session, get_write_session
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.frame_service import FrameReconstructionService
from backend.app.services.ingestion_service import IngestionService
from backend.app.services.upload_service import UploadService
from tests.fixtures.builders import FixtureSpec, build_telemetry_csv
from tests.integration.test_manual_upload import (
    CHARGER,
    make_fixture,
    register_charger,
    upload_and_process,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings) -> AsyncIterator[AsyncClient]:
    """A client whose session lifecycle matches the deployed application.

    Only the engine is swapped for the test SQLite file; the rollback-on-read and
    commit-on-write behaviour is the real behaviour.
    """
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def csv_bytes(tmp_path: Path, name: str, spec: FixtureSpec) -> bytes:
    path = tmp_path / name
    tmp_path.mkdir(parents=True, exist_ok=True)
    build_telemetry_csv(path, spec)
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------


async def test_upload_returns_202_and_does_not_wait_for_processing(
    client: AsyncClient, tmp_path: Path
) -> None:
    payload = csv_bytes(tmp_path, "HYD12.csv", FixtureSpec(timestamp_count=5))

    response = await client.post(
        "/api/v1/ingestion/uploads",
        files=[("files", ("HYD12.csv", payload, "text/csv"))],
    )
    assert response.status_code == 202

    data = response.json()["data"]
    assert data["upload_batch_id"]
    assert data["file_count"] == 1
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 0
    # Staged and queued - explicitly NOT processed yet.
    assert data["status"] == "REGISTERED"
    assert "queued" in response.json()["meta"]["note"]


async def test_upload_accepts_many_files_in_one_request(
    client: AsyncClient, tmp_path: Path
) -> None:
    files = [
        (
            "files",
            (
                f"HYD12_{index}.csv",
                csv_bytes(
                    tmp_path,
                    f"HYD12_{index}.csv",
                    FixtureSpec(
                        timestamp_count=3,
                        start=dt.datetime(2026, 7, 10 + index, 1, 0),
                    ),
                ),
                "text/csv",
            ),
        )
        for index in range(6)
    ]
    response = await client.post("/api/v1/ingestion/uploads", files=files)
    assert response.status_code == 202
    assert response.json()["data"]["accepted_count"] == 6


async def test_upload_reports_rejected_files_without_failing_the_batch(
    client: AsyncClient, tmp_path: Path
) -> None:
    good = csv_bytes(tmp_path, "good.csv", FixtureSpec(timestamp_count=3))

    response = await client.post(
        "/api/v1/ingestion/uploads",
        files=[
            ("files", ("good.csv", good, "text/csv")),
            ("files", ("bad.exe", b"MZ", "application/octet-stream")),
            ("files", ("empty.csv", b"", "text/csv")),
        ],
    )
    assert response.status_code == 202

    data = response.json()["data"]
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 2

    by_name = {item["original_filename"]: item for item in data["staged"]}
    assert by_name["bad.exe"]["status"] == "REJECTED"
    assert "not permitted" in by_name["bad.exe"]["reason"]
    assert by_name["empty.csv"]["reason"] == "File is empty"
    assert by_name["good.csv"]["status"] == "PENDING"


async def test_upload_with_no_files_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/ingestion/uploads", files=[])
    assert response.status_code in {400, 422}


async def test_upload_response_never_leaks_internal_paths(
    client: AsyncClient, tmp_path: Path
) -> None:
    payload = csv_bytes(tmp_path, "HYD12.csv", FixtureSpec(timestamp_count=3))
    response = await client.post(
        "/api/v1/ingestion/uploads",
        files=[("files", ("HYD12.csv", payload, "text/csv"))],
    )
    body = response.text
    assert "staged_reference" not in body
    assert "/uploads/" not in body.replace("/api/v1/ingestion/uploads", "")


async def test_staged_batch_survives_the_request_that_created_it(
    client: AsyncClient, engine: AsyncEngine, tmp_path: Path
) -> None:
    """A 202 must be backed by a committed batch (regression).

    The upload endpoint is the only writing endpoint in the API. It originally
    inherited the read-only session dependency, which rolls back on exit: the
    response carried a batch id, the staged bytes were on disk, and the batch
    itself was gone - so the worker could never find it and the operator got a
    404 on a batch they had just been given.

    Reading through a session opened *after* the request is what makes this
    detectable; anything sharing the request's transaction would see the doomed
    rows and pass.
    """
    payload = csv_bytes(tmp_path, "HYD12.csv", FixtureSpec(timestamp_count=4))
    created = await client.post(
        "/api/v1/ingestion/uploads",
        files=[("files", ("HYD12.csv", payload, "text/csv"))],
    )
    batch_id = created.json()["data"]["upload_batch_id"]

    # Straight to the database, in a transaction that started later.
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as fresh:
        batch = await UploadRepository(fresh).get_batch(UUID(batch_id))
        assert batch is not None, "the 202 was not backed by a committed batch"
        assert batch.file_count == 1
        files = await UploadRepository(fresh).staged_files(UUID(batch_id))
        assert len(files) == 1

    # And it is reachable over HTTP, which is what the operator actually does next.
    assert (await client.get(f"/api/v1/ingestion/uploads/{batch_id}")).status_code == 200


async def test_limits_are_published_from_settings(client: AsyncClient, settings: Settings) -> None:
    """The UI pre-checks files, so it must read the real limits, not its own copy."""
    response = await client.get("/api/v1/ingestion/uploads/limits")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["max_files_per_batch"] == settings.upload.max_files_per_batch
    assert data["max_file_size_bytes"] == settings.upload.max_file_size_bytes
    assert data["max_batch_size_bytes"] == settings.upload.max_batch_size_bytes
    assert data["allowed_extensions"] == settings.upload.allowed_extensions
    # The staging root is deployment-internal and must not be published.
    assert "staging_root" not in data


async def test_limits_route_is_not_shadowed_by_the_batch_route(
    client: AsyncClient,
) -> None:
    """Regression: /limits must resolve before /{batch_id} claims it."""
    response = await client.get("/api/v1/ingestion/uploads/limits")
    assert response.status_code == 200
    assert "max_file_size_bytes" in response.json()["data"]


# ---------------------------------------------------------------------------
# Batch detail and history
# ---------------------------------------------------------------------------


async def test_batch_detail_reports_derived_counts(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=6))
    batch_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )
    # The worker commits when it finishes; the API reads in its own transaction.
    await session.commit()

    response = await client.get(f"/api/v1/ingestion/uploads/{batch_id}")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["batch"]["file_count"] == 1
    assert data["counts"]["total_files"] == 1
    assert data["counts"]["completed"] == 1
    assert data["counts"]["progress_percentage"] == 100.0
    assert data["batch"]["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}


async def test_batch_files_lists_processing_state_from_the_telemetry_file(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12_28-07-2026.csv", FixtureSpec(timestamp_count=6))
    batch_id, _ = await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12_28-07-2026.csv", source)],
    )
    await session.commit()

    response = await client.get(f"/api/v1/ingestion/uploads/{batch_id}/files")
    assert response.status_code == 200

    rows = response.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["original_filename"] == "HYD12_28-07-2026.csv"
    assert row["status"] == "REGISTERED"
    # Real processing state is read from the telemetry file, not duplicated.
    assert row["telemetry_status"] == "FRAMES_RECONSTRUCTED"
    assert row["business_date"] == "2026-07-27"
    assert row["unique_event_timestamp_count"] == 6
    assert row["is_duplicate"] is False
    # No internal paths.
    assert "staged_reference" not in response.text


async def test_batch_files_before_processing_show_no_fabricated_values(
    client: AsyncClient, tmp_path: Path
) -> None:
    """Section 39: an unprocessed file reports null, never a fake zero."""
    payload = csv_bytes(tmp_path, "HYD12.csv", FixtureSpec(timestamp_count=4))
    created = await client.post(
        "/api/v1/ingestion/uploads",
        files=[("files", ("HYD12.csv", payload, "text/csv"))],
    )
    batch_id = created.json()["data"]["upload_batch_id"]

    response = await client.get(f"/api/v1/ingestion/uploads/{batch_id}/files")
    row = response.json()["data"][0]

    assert row["status"] == "PENDING"
    assert row["telemetry_status"] is None
    assert row["business_date"] is None
    assert row["unique_event_timestamp_count"] is None
    assert row["quality_score"] is None


async def test_batch_files_filter_by_status(client: AsyncClient, tmp_path: Path) -> None:
    good = csv_bytes(tmp_path, "good.csv", FixtureSpec(timestamp_count=3))
    created = await client.post(
        "/api/v1/ingestion/uploads",
        files=[
            ("files", ("good.csv", good, "text/csv")),
            ("files", ("bad.exe", b"MZ", "application/octet-stream")),
        ],
    )
    batch_id = created.json()["data"]["upload_batch_id"]

    rejected = await client.get(
        f"/api/v1/ingestion/uploads/{batch_id}/files", params={"status": "REJECTED"}
    )
    rows = rejected.json()["data"]
    assert len(rows) == 1
    assert rows[0]["original_filename"] == "bad.exe"


async def test_upload_history_is_paginated_and_carries_counts(
    client: AsyncClient, tmp_path: Path
) -> None:
    for index in range(3):
        payload = csv_bytes(
            tmp_path,
            f"h{index}.csv",
            FixtureSpec(timestamp_count=3, start=dt.datetime(2026, 7, 5 + index, 1, 0)),
        )
        await client.post(
            "/api/v1/ingestion/uploads",
            files=[("files", (f"h{index}.csv", payload, "text/csv"))],
        )

    response = await client.get("/api/v1/ingestion/uploads", params={"page_size": 2})
    assert response.status_code == 200

    body = response.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 3
    assert body["meta"]["total_pages"] == 2
    # Newest first.
    stamps = [row["created_at"] for row in body["data"]]
    assert stamps == sorted(stamps, reverse=True)
    # Counts are attached per batch without an N+1.
    assert body["data"][0]["counts"]["total_files"] == 1
    assert body["data"][0]["source_type"] == "MANUAL_UPLOAD"


async def test_unknown_batch_404s(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ingestion/uploads/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_bad_batch_uuid_400s(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ingestion/uploads/not-a-uuid")
    assert response.status_code == 400


async def test_phase_1c_and_1d_endpoints_still_work(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    fleet_repo: FleetRepository,
    upload_service: UploadService,
    ingestion_service: IngestionService,
    coverage_service: CoverageService,
    frame_service: FrameReconstructionService,
) -> None:
    """Regression: uploaded telemetry appears through the existing APIs."""
    await register_charger(fleet_repo)
    source = make_fixture(tmp_path / "src", "HYD12.csv", FixtureSpec(timestamp_count=8))
    await upload_and_process(
        uploads=upload_service,
        ingestion=ingestion_service,
        coverage=coverage_service,
        frames=frame_service,
        files=[("HYD12.csv", source)],
    )
    await session.commit()

    # Phase 1C daily summary sees the uploaded charger-day.
    daily = await client.get("/api/v1/data-operations/daily", params={"date": "2026-07-27"})
    assert daily.status_code == 200
    assert daily.json()["data"]["received"] == 1

    # Phase 1D frames exist for it, through the same endpoint as any other source.
    frames = await client.get(f"/api/v1/chargers/{CHARGER}/frames", params={"page_size": 5})
    assert frames.status_code == 200
    assert frames.json()["meta"]["total"] > 0
