"""Shared test fixtures.

The suite is hermetic: every test gets its own SQLite database and its own
storage roots, created from the SQLAlchemy metadata.  Nothing touches a
PostgreSQL instance, and nothing leaks state between tests.

The models are deliberately built from portable types (see ``db/base``), so the
same schema that Alembic produces on PostgreSQL also materialises here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.models import Charger  # noqa: F401 - registers every table
from backend.app.models.enums import ChargerLifecycleStatus
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.factory import build_ingestion_service, get_dictionary
from backend.app.services.metrics_service import MetricsService
from pipelines.persistence.storage import LocalFilesystemRawStorage

#: The fixture builder's default telemetry date. Deliberately *not* the date in
#: the filenames the tests use - that mismatch is a behaviour under test.
FIXTURE_BUSINESS_DATE = dt.date(2026, 7, 27)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings and the dictionary are process-cached; reset around every test."""
    get_settings.cache_clear()
    get_dictionary.cache_clear()
    yield
    get_settings.cache_clear()
    get_dictionary.cache_clear()


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path, project_root: Path) -> Settings:
    """Isolated settings pointed at per-test storage roots."""
    return Settings(
        project_root=project_root,
        database={"url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"},  # type: ignore[arg-type]
        storage={  # type: ignore[arg-type]
            "raw_root": tmp_path / "raw",
            "quarantine_root": tmp_path / "quarantine",
            "processed_root": tmp_path / "processed",
        },
        filesystem_source={"inbox": tmp_path / "inbox"},  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def session(settings: Settings) -> AsyncIterator[AsyncSession]:
    """A session against a freshly created schema."""
    engine = create_async_engine(settings.database.async_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest.fixture
def storage(settings: Settings) -> LocalFilesystemRawStorage:
    return LocalFilesystemRawStorage(
        raw_root=settings.storage.raw_root, quarantine_root=settings.storage.quarantine_root
    )


@pytest.fixture
def fleet_repo(session: AsyncSession) -> FleetRepository:
    return FleetRepository(session)


@pytest.fixture
def file_repo(session: AsyncSession) -> TelemetryFileRepository:
    return TelemetryFileRepository(session)


@pytest.fixture
def quality_repo(session: AsyncSession) -> QualityRepository:
    return QualityRepository(session)


@pytest.fixture
def coverage_service(
    session: AsyncSession, settings: Settings
) -> CoverageService:
    return CoverageService(
        fleet_repo=FleetRepository(session),
        file_repo=TelemetryFileRepository(session),
        quality_repo=QualityRepository(session),
        settings=settings,
    )


@pytest.fixture
def metrics_service(session: AsyncSession, settings: Settings) -> MetricsService:
    return MetricsService(
        fleet_repo=FleetRepository(session),
        file_repo=TelemetryFileRepository(session),
        run_repo=IngestionRunRepository(session),
        quality_repo=QualityRepository(session),
        settings=settings,
    )


@pytest.fixture
def ingestion_service(
    session: AsyncSession, settings: Settings, storage: LocalFilesystemRawStorage
) -> object:
    return build_ingestion_service(session, settings=settings, storage=storage)


@pytest_asyncio.fixture
async def registered_charger(fleet_repo: FleetRepository) -> Charger:
    """The charger the default fixture file reports as."""
    return await fleet_repo.upsert_charger(
        charger_id="D82510560390014",
        ocpp_id="HYD12",
        site_code="SITE-HYD-001",
        lifecycle_status=ChargerLifecycleStatus.ACTIVE,
        telemetry_expected=True,
        expected_connector_count=2,
        expected_smr_count=4,
        expected_sampling_interval_seconds=120,
        source_timezone="Asia/Kolkata",
    )
