"""Service assembly, shared by the API, the CLI and the tests.

The wiring lives here so the three runtimes cannot drift into building the
pipeline differently.  A subtle divergence - a different rule registry, another
dictionary root - would make the CLI's results disagree with the API's for the
same file, which is exactly the class of bug this module exists to prevent.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, get_settings
from backend.app.repositories.events import EventRepository
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.research import ResearchRepository
from backend.app.repositories.schema import SchemaRepository
from backend.app.repositories.silver import SilverRepository
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.event_service import EventReconstructionService
from backend.app.services.frame_service import FrameReconstructionService
from backend.app.services.history_service import HistoricalContinuityService
from backend.app.services.ingestion_service import IngestionService
from backend.app.services.metrics_service import MetricsService
from backend.app.services.normalization_service import NormalizationService
from backend.app.services.research_access import ResearchDataAccessLayer
from backend.app.services.research_service import ResearchService
from backend.app.services.upload_service import UploadService
from pipelines.persistence.storage import LocalFilesystemRawStorage, RawObjectStorage
from pipelines.quality.rules import build_default_registry
from pipelines.sources.filesystem import FilesystemTelemetrySource
from pipelines.validation.dictionary import DictionaryRegistry

__all__ = [
    "build_coverage_service",
    "build_event_service",
    "build_filesystem_source",
    "build_frame_service",
    "build_historical_service",
    "build_ingestion_service",
    "build_metrics_service",
    "build_normalization_service",
    "build_research_access",
    "build_research_service",
    "build_storage",
    "build_upload_service",
    "get_dictionary",
]


def _dictionary_root(settings: Settings) -> Path:
    return settings.project_root / "data" / "dictionaries"


@lru_cache(maxsize=1)
def get_dictionary() -> DictionaryRegistry:
    """Load the curated data dictionary once per process.

    The registry is immutable and its parse cost is non-trivial, so both the API
    workers and the CLI share a single cached instance.
    """
    settings = get_settings()
    return DictionaryRegistry.load(
        _dictionary_root(settings), contracts_dir=settings.project_root / "data" / "contracts"
    )


def build_storage(settings: Settings | None = None) -> RawObjectStorage:
    config = settings or get_settings()
    return LocalFilesystemRawStorage(
        raw_root=config.storage.raw_root,
        quarantine_root=config.storage.quarantine_root,
    )


def build_filesystem_source(settings: Settings | None = None) -> FilesystemTelemetrySource:
    config = settings or get_settings()
    return FilesystemTelemetrySource(
        config.filesystem_source.inbox,
        pattern=config.filesystem_source.glob,
        allowed_extensions=config.ingest.allowed_extensions,
        max_file_size_bytes=config.ingest.max_file_size_bytes,
        ack_strategy=config.filesystem_source.ack_strategy,
        archive_dir=config.filesystem_source.archive_dir,
    )


def build_ingestion_service(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    storage: RawObjectStorage | None = None,
) -> IngestionService:
    config = settings or get_settings()
    return IngestionService(
        run_repo=IngestionRunRepository(session),
        file_repo=TelemetryFileRepository(session),
        schema_repo=SchemaRepository(session),
        quality_repo=QualityRepository(session),
        storage=storage or build_storage(config),
        dictionary=get_dictionary(),
        rules=build_default_registry(),
        settings=config,
    )


def build_coverage_service(
    session: AsyncSession, *, settings: Settings | None = None
) -> CoverageService:
    config = settings or get_settings()
    return CoverageService(
        fleet_repo=FleetRepository(session),
        file_repo=TelemetryFileRepository(session),
        quality_repo=QualityRepository(session),
        settings=config,
    )


def build_frame_service(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    storage: RawObjectStorage | None = None,
) -> FrameReconstructionService:
    config = settings or get_settings()
    return FrameReconstructionService(
        frame_repo=FrameRepository(session),
        file_repo=TelemetryFileRepository(session),
        fleet_repo=FleetRepository(session),
        quality_repo=QualityRepository(session),
        storage=storage or build_storage(config),
        dictionary=get_dictionary(),
        settings=config,
    )


def build_upload_service(
    session: AsyncSession, *, settings: Settings | None = None
) -> UploadService:
    config = settings or get_settings()
    return UploadService(upload_repo=UploadRepository(session), settings=config)


def build_metrics_service(
    session: AsyncSession, *, settings: Settings | None = None
) -> MetricsService:
    config = settings or get_settings()
    return MetricsService(
        fleet_repo=FleetRepository(session),
        file_repo=TelemetryFileRepository(session),
        run_repo=IngestionRunRepository(session),
        quality_repo=QualityRepository(session),
        settings=config,
    )


def build_normalization_service(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    storage: RawObjectStorage | None = None,
) -> NormalizationService:
    config = settings or get_settings()
    return NormalizationService(
        silver_repo=SilverRepository(session),
        frame_repo=FrameRepository(session),
        file_repo=TelemetryFileRepository(session),
        quality_repo=QualityRepository(session),
        storage=storage or build_storage(config),
        dictionary=get_dictionary(),
        settings=config,
    )


def build_historical_service(
    session: AsyncSession,
) -> HistoricalContinuityService:
    return HistoricalContinuityService(
        session=session,
        silver_repo=SilverRepository(session),
    )


def build_event_service(
    session: AsyncSession,
    *,
    version: str = "v1",
) -> EventReconstructionService:
    history_svc = build_historical_service(session)
    return EventReconstructionService(
        session=session,
        history_service=history_svc,
        version=version,
    )


def build_research_access(
    session: AsyncSession,
) -> ResearchDataAccessLayer:
    history_svc = build_historical_service(session)
    event_repo = EventRepository(session)
    return ResearchDataAccessLayer(history_svc, event_repo=event_repo)


def build_research_service(
    session: AsyncSession,
) -> ResearchService:
    history_svc = build_historical_service(session)
    event_repo = EventRepository(session)
    research_repo = ResearchRepository(session)
    return ResearchService(
        session=session,
        history_service=history_svc,
        event_repo=event_repo,
        research_repo=research_repo,
    )
