"""Frame diagnostics API (Phase 1D sections 45-48).

Exercised against genuinely reconstructed data, and asserting the two safety rules:
no raw telemetry payload and no internal storage paths in any response.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_session
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app
from backend.app.models.enums import DuplicateClassification
from backend.app.models.telemetry_frame import TelemetrySourceFrame
from backend.app.repositories.fleet import FleetRepository
from backend.app.services.frame_service import FrameReconstructionService
from tests.fixtures.builders import FixtureSpec
from tests.integration.test_frame_persistence import (
    BUSINESS_DATE,
    CHARGER,
    register_charger,
    register_file,
)

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


@pytest_asyncio.fixture
async def reconstructed(
    session: AsyncSession,
    settings: Settings,
    storage: object,
    fleet_repo: FleetRepository,
    frame_service: FrameReconstructionService,
) -> dict[str, object]:
    """A file with replays and a collision, reconstructed and persisted."""
    await register_charger(fleet_repo)
    telemetry_file = await register_file(
        session,
        settings,
        storage,
        filename="HYD12_28-07-2026.csv",
        spec=FixtureSpec(
            timestamp_count=12,
            interval_seconds=121,
            replay_timestamp_indexes=(3,),
            conflicting_timestamp_indexes=(6,),
        ),
    )
    result = await frame_service.reconstruct_file(telemetry_file)
    return {"file": telemetry_file, "result": result}


# ---------------------------------------------------------------------------
# Section 45
# ---------------------------------------------------------------------------


async def test_file_reconstruction_summary(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    telemetry_file = reconstructed["file"]
    response = await client.get(
        f"/api/v1/ingestion/files/{telemetry_file.id}/reconstruction"  # type: ignore[attr-defined]
    )
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["original_filename"] == "HYD12_28-07-2026.csv"
    assert data["expected_positions_per_frame"] == 8
    assert data["frames_reconstructed"] > 0
    assert data["canonical_frames"] > 0
    assert data["unique_timestamps"] == 12

    # Replay and collision counts are surfaced separately, never merged.
    assert data["full_replays"] >= 1
    assert data["same_timestamp_distinct_frames"] >= 1
    assert data["collision_timestamps"] >= 1

    # The raw-grain multiplier is explicit, so raw rows cannot be mistaken for
    # observations.
    assert data["rows_per_unique_timestamp"] is not None
    assert data["rows_per_unique_timestamp"] > 1
    assert 0.0 <= data["frame_completeness_percentage"] <= 100.0


async def test_file_reconstruction_404s_for_unknown_file(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/ingestion/files/00000000-0000-0000-0000-000000000000/reconstruction"
    )
    assert response.status_code == 404


async def test_file_reconstruction_rejects_bad_uuid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ingestion/files/not-a-uuid/reconstruction")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Section 46
# ---------------------------------------------------------------------------


async def test_charger_frames_are_ordered_and_paginated(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    response = await client.get(f"/api/v1/chargers/{CHARGER}/frames", params={"page_size": 100})
    assert response.status_code == 200

    body = response.json()
    rows = body["data"]
    assert rows
    assert set(body["meta"]) == {"page", "page_size", "total", "total_pages"}

    # event_time ASC then frame_sequence ASC - same-second frames keep their order.
    keys = [(row["event_time"], row["frame_sequence"]) for row in rows]
    assert keys == sorted(keys)

    for row in rows:
        assert row["frame_fingerprint"]
        assert row["fingerprint_short"] == row["frame_fingerprint"][:12]
        assert isinstance(row["is_canonical"], bool)


async def test_charger_frames_filter_by_classification(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/frames",
        params={"duplicate_classification": "FULL_FRAME_REPLAY", "page_size": 100},
    )
    rows = response.json()["data"]
    assert rows
    assert all(row["duplicate_classification"] == "FULL_FRAME_REPLAY" for row in rows)
    assert all(row["is_canonical"] is False for row in rows)


async def test_charger_frames_canonical_only_excludes_replays(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    """What Phase 1E will consume."""
    everything = await client.get(f"/api/v1/chargers/{CHARGER}/frames", params={"page_size": 200})
    canonical = await client.get(
        f"/api/v1/chargers/{CHARGER}/frames",
        params={"canonical_only": "true", "page_size": 200},
    )

    all_rows = everything.json()["data"]
    canonical_rows = canonical.json()["data"]
    assert 0 < len(canonical_rows) < len(all_rows)
    assert all(row["is_canonical"] for row in canonical_rows)
    assert {row["duplicate_classification"] for row in canonical_rows} <= {
        "UNIQUE",
        "SAME_TIMESTAMP_DISTINCT_FRAME",
    }


async def test_charger_frames_rejects_inverted_range(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/frames",
        params={"from": "2026-07-31", "to": "2026-07-01"},
    )
    assert response.status_code == 400


async def test_charger_frames_rejects_unknown_status(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/frames", params={"frame_status": "NOPE"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Section 50 - collisions
# ---------------------------------------------------------------------------


async def test_collision_explorer_lists_same_timestamp_frames(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/frames/collisions",
        params={"date": BUSINESS_DATE.isoformat()},
    )
    assert response.status_code == 200

    groups = response.json()["data"]
    assert groups, "the fixture creates a collision timestamp"

    group = groups[0]
    assert group["canonical_count"] >= 2
    assert len(group["frames"]) >= 2
    # All frames in a group share the event time and differ only by sequence.
    assert len({frame["event_time"] for frame in group["frames"]}) == 1
    sequences = [frame["frame_sequence"] for frame in group["frames"]]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


# ---------------------------------------------------------------------------
# Section 47 - frame detail
# ---------------------------------------------------------------------------


async def test_frame_detail_exposes_provenance_but_no_telemetry(
    client: AsyncClient, session: AsyncSession, reconstructed: dict[str, object]
) -> None:
    frame = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame)
                .where(
                    TelemetrySourceFrame.duplicate_classification == DuplicateClassification.UNIQUE
                )
                .limit(1)
            )
        )
        .scalars()
        .one()
    )

    response = await client.get(f"/api/v1/frames/{frame.id}")
    assert response.status_code == 200

    payload = response.text
    # Section 69: no internal paths, and no raw telemetry values.
    assert "storage_reference" not in payload
    assert "/raw/" not in payload
    assert "cabinet_temperature" not in payload

    data = response.json()["data"]
    assert data["frame"]["charger_id"] == CHARGER
    assert data["frame"]["reconstruction_version"]

    # frame -> source file -> source rows
    assert len(data["sources"]) == 1
    assert data["sources"][0]["is_primary_source"] is True
    assert data["sources"][0]["original_filename"] == "HYD12_28-07-2026.csv"
    assert len(data["rows"]) == 8
    assert sorted(data["observed_positions"]) == sorted(
        f"C{c}/S{s}" for c in ("1", "2") for s in ("1", "2", "3", "4")
    )
    for row in data["rows"]:
        assert len(row["row_fingerprint"]) == 64
        assert row["source_row_number"] >= 0


async def test_frame_detail_reports_replays_of_a_canonical_frame(
    client: AsyncClient, session: AsyncSession, reconstructed: dict[str, object]
) -> None:
    """Section 52: "this frame appeared N times"."""
    replay = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame)
                .where(
                    TelemetrySourceFrame.duplicate_classification
                    == DuplicateClassification.FULL_FRAME_REPLAY
                )
                .limit(1)
            )
        )
        .scalars()
        .one()
    )
    assert replay.replay_of_frame_id is not None

    response = await client.get(f"/api/v1/frames/{replay.replay_of_frame_id}")
    data = response.json()["data"]

    assert data["replay_count"] >= 1
    assert data["replays"]
    # Both full and partial replays point at the canonical frame - a partial
    # retransmission is still a replay of it, so the view lists both kinds.
    assert all(
        item["duplicate_classification"] in {"FULL_FRAME_REPLAY", "PARTIAL_FRAME_REPLAY"}
        for item in data["replays"]
    )
    assert any(item["duplicate_classification"] == "FULL_FRAME_REPLAY" for item in data["replays"])
    assert all(item["is_canonical"] is False for item in data["replays"])
    # The canonical frame also lists its same-timestamp siblings.
    assert data["siblings"]


async def test_frame_detail_404s_for_unknown_frame(client: AsyncClient) -> None:
    response = await client.get("/api/v1/frames/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Section 48 - frame diff
# ---------------------------------------------------------------------------


async def test_frame_diff_reports_which_positions_changed(
    client: AsyncClient, session: AsyncSession, reconstructed: dict[str, object]
) -> None:
    distinct = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame)
                .where(
                    TelemetrySourceFrame.duplicate_classification
                    == DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME
                )
                .limit(1)
            )
        )
        .scalars()
        .one()
    )

    siblings = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame).where(
                    TelemetrySourceFrame.charger_id == distinct.charger_id,
                    TelemetrySourceFrame.event_time == distinct.event_time,
                    TelemetrySourceFrame.id != distinct.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert siblings

    other = siblings[0]
    response = await client.get(f"/api/v1/frames/{other.id}/diff/{distinct.id}")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["same_event_time"] is True
    assert data["identical_payload"] is False
    assert data["differing_position_count"] > 0
    assert data["differing_positions"]
    # Positions are reported, not telemetry values.
    assert all(p.startswith("C") for p in data["differing_positions"])
    assert "cabinet_temperature" not in response.text


async def test_frame_diff_of_identical_frames_reports_no_differences(
    client: AsyncClient, session: AsyncSession, reconstructed: dict[str, object]
) -> None:
    replay = (
        (
            await session.execute(
                sa.select(TelemetrySourceFrame)
                .where(
                    TelemetrySourceFrame.duplicate_classification
                    == DuplicateClassification.FULL_FRAME_REPLAY
                )
                .limit(1)
            )
        )
        .scalars()
        .one()
    )
    assert replay.replay_of_frame_id is not None

    response = await client.get(f"/api/v1/frames/{replay.replay_of_frame_id}/diff/{replay.id}")
    data = response.json()["data"]

    assert data["identical_payload"] is True
    assert data["differing_positions"] == []
    assert len(data["matching_positions"]) == 8


async def test_frame_diff_rejects_cross_charger_comparison(
    client: AsyncClient, session: AsyncSession, reconstructed: dict[str, object]
) -> None:
    from uuid import uuid4

    frame = (await session.execute(sa.select(TelemetrySourceFrame).limit(1))).scalars().one()

    other = TelemetrySourceFrame(
        id=uuid4(),
        charger_id="SOME_OTHER_CHARGER",
        event_time=frame.event_time,
        business_date=frame.business_date,
        frame_sequence=0,
        frame_fingerprint="f" * 64,
        frame_status=frame.frame_status,
        duplicate_classification=DuplicateClassification.UNIQUE,
        expected_position_count=8,
        observed_position_count=8,
        missing_position_count=0,
        unexpected_position_count=0,
        reconstruction_version=frame.reconstruction_version,
    )
    session.add(other)
    await session.flush()

    response = await client.get(f"/api/v1/frames/{frame.id}/diff/{other.id}")
    assert response.status_code == 400
    assert "different chargers" in response.json()["error"]["message"]


async def test_phase_1c_endpoints_still_work(
    client: AsyncClient, reconstructed: dict[str, object]
) -> None:
    """Section 65: Phase 1D must not disturb the Phase 1C API surface."""
    summary = await client.get(
        "/api/v1/data-operations/daily", params={"date": BUSINESS_DATE.isoformat()}
    )
    assert summary.status_code == 200
    assert summary.json()["error"] is None

    coverage = await client.get(
        f"/api/v1/chargers/{CHARGER}/coverage",
        params={"from": "2026-07-01", "to": "2026-07-31"},
    )
    assert coverage.status_code == 200
