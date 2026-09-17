"""Data-operations API behaviour (Phase 1C sections 30, 45).

Covers the response envelope, filtering, pagination and - importantly - that
internal filesystem paths never reach a client.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_session
from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app
from backend.app.models.enums import ArrivalStatus, CompletenessStatus
from backend.app.repositories.fleet import FleetRepository
from backend.app.services.coverage_service import CoverageService
from tests.integration.test_reconciliation import BUSINESS_DATE, CHARGER, add_file, register

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(session: AsyncSession, settings: Settings) -> AsyncIterator[AsyncClient]:
    """An API client bound to the test session, so it sees test data."""
    get_settings.cache_clear()
    app = create_app(settings)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def seeded(
    session: AsyncSession, fleet_repo: FleetRepository, coverage_service: CoverageService
) -> None:
    """A realistic day: one complete, one partial, one missing, one unexpected."""
    await register(fleet_repo, CHARGER)
    await register(fleet_repo, "PARTIAL01")
    await register(fleet_repo, "MISSING01")

    await add_file(session, charger_id=CHARGER, count=720)
    await add_file(session, charger_id="PARTIAL01", count=400)
    await add_file(session, charger_id="GHOST01", count=100)
    await add_file(
        session,
        charger_id="LATE01",
        count=720,
        received_at=dt.datetime(2026, 8, 20, 0, 0, tzinfo=dt.UTC),
    )
    await register(fleet_repo, "LATE01")
    await coverage_service.reconcile(BUSINESS_DATE)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_daily_summary_shape_and_numbers(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        "/api/v1/data-operations/daily", params={"date": BUSINESS_DATE.isoformat()}
    )
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {"data", "meta", "error"}
    assert body["error"] is None

    data = body["data"]
    assert data["business_date"] == BUSINESS_DATE.isoformat()
    assert data["expected"] == 4
    assert data["received"] == 3
    assert data["missing"] == 1
    assert data["late"] == 1
    assert data["unexpected"] == 1
    assert data["complete"] == 2
    assert data["partial"] == 1

    # Rates must be present and internally consistent.
    assert data["fleet_delivery_rate"] == pytest.approx(75.0, abs=0.01)
    assert data["fleet_missing_rate"] == pytest.approx(25.0, abs=0.01)
    assert 0.0 <= data["fleet_coverage_percentage"] <= 100.0
    assert len(data["stages"]) == 6


async def test_daily_summary_requires_a_date(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/daily")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_daily_summary_rejects_a_malformed_date(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/daily", params={"date": "not-a-date"})
    assert response.status_code == 422


async def test_empty_date_returns_zeros_not_an_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/daily", params={"date": "2020-01-01"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["expected"] == 0
    assert data["missing"] == 0
    assert data["fleet_coverage_percentage"] == 0.0


# ---------------------------------------------------------------------------
# Charger list: filtering, ordering, pagination
# ---------------------------------------------------------------------------


async def test_charger_list_is_ordered_worst_coverage_first(
    client: AsyncClient, seeded: None
) -> None:
    response = await client.get(f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers")
    assert response.status_code == 200
    rows = response.json()["data"]

    coverages = [float(row["coverage_percentage"] or 0) for row in rows]
    assert coverages == sorted(coverages), "worst coverage must come first (section 34)"
    assert rows[0]["charger_id"] == "MISSING01"


async def test_charger_list_filters_by_arrival_status(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"arrival_status": ArrivalStatus.MISSING.value},
    )
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["charger_id"] == "MISSING01"
    assert rows[0]["arrival_status"] == "MISSING"


async def test_charger_list_filters_by_completeness_status(
    client: AsyncClient, seeded: None
) -> None:
    response = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"completeness_status": CompletenessStatus.COMPLETE.value},
    )
    rows = response.json()["data"]
    assert {row["charger_id"] for row in rows} == {CHARGER, "LATE01"}


async def test_charger_list_filters_by_charger_and_site(client: AsyncClient, seeded: None) -> None:
    by_charger = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"charger": CHARGER},
    )
    assert [row["charger_id"] for row in by_charger.json()["data"]] == [CHARGER]

    by_site = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers", params={"site": "SITE-A"}
    )
    assert len(by_site.json()["data"]) >= 3
    assert all(row["site_code"] == "SITE-A" for row in by_site.json()["data"])


async def test_charger_list_rejects_an_unknown_filter_value(
    client: AsyncClient, seeded: None
) -> None:
    response = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"arrival_status": "NOT_A_STATUS"},
    )
    assert response.status_code == 422


async def test_pagination_splits_and_reports_totals(client: AsyncClient, seeded: None) -> None:
    first = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"page": 1, "page_size": 2},
    )
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"] == {"page": 1, "page_size": 2, "total": 5, "total_pages": 3}

    second = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers",
        params={"page": 2, "page_size": 2},
    )
    assert len(second.json()["data"]) == 2

    # Pages must not overlap.
    ids = {row["charger_id"] for row in body["data"]}
    assert ids.isdisjoint({row["charger_id"] for row in second.json()["data"]})


async def test_page_size_is_capped_by_configuration(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers", params={"page_size": 500}
    )
    assert response.status_code == 200
    assert response.json()["meta"]["page_size"] <= 200


async def test_invalid_pagination_is_rejected(client: AsyncClient) -> None:
    assert (
        await client.get(
            f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers", params={"page": 0}
        )
    ).status_code == 422
    assert (
        await client.get(
            f"/api/v1/data-operations/daily/{BUSINESS_DATE}/chargers", params={"page_size": 0}
        )
    ).status_code == 422


# ---------------------------------------------------------------------------
# Missing / late tables
# ---------------------------------------------------------------------------


async def test_missing_chargers_endpoint(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"/api/v1/data-operations/daily/{BUSINESS_DATE}/missing")
    rows = response.json()["data"]
    assert len(rows) == 1

    row = rows[0]
    assert row["charger_id"] == "MISSING01"
    assert row["site_code"] == "SITE-A"
    # No prior history exists, so these are explicitly null rather than invented.
    assert row["last_successful_date"] is None
    assert row["previous_day_coverage_percentage"] is None


async def test_missing_chargers_report_prior_history_when_it_exists(
    client: AsyncClient,
    session: AsyncSession,
    fleet_repo: FleetRepository,
    coverage_service: CoverageService,
) -> None:
    await register(fleet_repo, "HYD44")
    previous = BUSINESS_DATE - dt.timedelta(days=1)

    await add_file(session, charger_id="HYD44", business_date=previous, count=720)
    await coverage_service.reconcile(previous)
    await coverage_service.reconcile(BUSINESS_DATE)  # nothing for today

    response = await client.get(f"/api/v1/data-operations/daily/{BUSINESS_DATE}/missing")
    row = response.json()["data"][0]
    assert row["last_successful_date"] == previous.isoformat()
    assert row["last_successful_coverage_percentage"] == pytest.approx(100.0)
    assert row["previous_day_coverage_percentage"] == pytest.approx(100.0)


async def test_late_endpoint(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"/api/v1/data-operations/daily/{BUSINESS_DATE}/late")
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["charger_id"] == "LATE01"
    assert rows[0]["late_by_seconds"] > 0
    assert rows[0]["received_at"] is not None


async def test_findings_endpoint_counts_by_rule(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"/api/v1/data-operations/daily/{BUSINESS_DATE}/findings")
    counts = response.json()["data"]
    assert counts["MISSING_CHARGER_DATA"] == 1
    assert counts["LATE_FILE"] == 1


# ---------------------------------------------------------------------------
# Charger-scoped endpoints
# ---------------------------------------------------------------------------


async def test_coverage_history(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/coverage",
        params={"from": "2026-08-01", "to": "2026-08-31"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["meta"]["day_count"] == 1
    assert body["data"][0]["business_date"] == BUSINESS_DATE.isoformat()


async def test_coverage_history_rejects_an_inverted_range(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/coverage",
        params={"from": "2026-08-31", "to": "2026-08-01"},
    )
    assert response.status_code == 400


async def test_coverage_history_rejects_an_excessive_range(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/chargers/{CHARGER}/coverage",
        params={"from": "2000-01-01", "to": "2026-08-31"},
    )
    assert response.status_code == 400
    assert "maximum" in response.json()["error"]["message"]


async def test_charger_gaps(
    client: AsyncClient,
    session: AsyncSession,
    fleet_repo: FleetRepository,
    coverage_service: CoverageService,
) -> None:
    await register(fleet_repo, CHARGER)
    await add_file(session, start_second=0, count=60)
    await add_file(session, start_second=60_000, count=60)
    await coverage_service.reconcile(BUSINESS_DATE)

    response = await client.get(f"/api/v1/chargers/{CHARGER}/gaps")
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] > 0
    assert rows[0]["duration_minutes"] == pytest.approx(rows[0]["duration_seconds"] / 60, abs=0.01)
    assert rows[0]["severity"] in {"MINOR", "MODERATE", "MAJOR", "CRITICAL"}


async def test_charger_day_detail_never_leaks_storage_paths(
    client: AsyncClient, seeded: None
) -> None:
    """Phase 1A section 20: internal paths must not appear in any response."""
    response = await client.get(f"/api/v1/chargers/{CHARGER}/coverage/{BUSINESS_DATE}")
    assert response.status_code == 200

    payload = response.text
    assert "storage_reference" not in payload
    assert "/raw/" not in payload

    data = response.json()["data"]
    assert data["coverage"]["charger_id"] == CHARGER
    assert len(data["files"]) == 1
    assert data["files"][0]["original_filename"]
    assert data["files"][0]["unique_timestamp_count_for_date"] == 720
    # The raw-vs-unique contrast is explicit (section 49).
    assert data["files"][0]["row_count_for_date"] > 720


async def test_charger_day_detail_404s_for_an_unknown_day(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/chargers/NOPE/coverage/{BUSINESS_DATE}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


async def test_runs_listing_is_paginated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/runs")
    assert response.status_code == 200
    assert set(response.json()["meta"]) == {"page", "page_size", "total", "total_pages"}


async def test_run_detail_rejects_a_bad_uuid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/runs/not-a-uuid")
    assert response.status_code == 400


async def test_run_detail_404s_when_absent(client: AsyncClient) -> None:
    response = await client.get("/api/v1/data-operations/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_operational_counters(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        "/api/v1/data-operations/metrics", params={"date": BUSINESS_DATE.isoformat()}
    )
    counters = response.json()["data"]
    assert counters["chargers_missing"] == 1.0
    assert counters["chargers_expected"] == 4.0
    assert "average_daily_coverage" in counters
