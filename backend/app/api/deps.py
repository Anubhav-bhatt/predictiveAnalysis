"""FastAPI dependencies.

Routes never construct repositories or open sessions themselves; they ask for a
service.  That keeps the API/service/repository boundary intact and makes the
same wiring reusable from the CLI (see ``services.factory``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_session_factory
from backend.app.repositories.base import PageRequest
from backend.app.repositories.events import EventRepository
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.silver import SilverRepository
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.event_service import EventReconstructionService
from backend.app.services.factory import (
    build_coverage_service,
    build_event_service,
    build_historical_service,
    build_metrics_service,
    build_normalization_service,
    build_research_access,
    build_research_service,
    build_upload_service,
)
from backend.app.services.history_service import HistoricalContinuityService
from backend.app.services.metrics_service import MetricsService
from backend.app.services.normalization_service import NormalizationService
from backend.app.services.research_access import ResearchDataAccessLayer
from backend.app.services.research_service import ResearchService
from backend.app.services.upload_service import UploadService

__all__ = [
    "CoverageServiceDep",
    "EventRepoDep",
    "EventServiceDep",
    "FleetRepoDep",
    "FrameRepoDep",
    "HistoricalServiceDep",
    "MetricsServiceDep",
    "NormalizationServiceDep",
    "PageDep",
    "ResearchAccessDep",
    "ResearchServiceDep",
    "RunRepoDep",
    "SessionDep",
    "SettingsDep",
    "SilverRepoDep",
    "UploadRepoDep",
    "UploadServiceDep",
    "WriteSessionDep",
    "get_page_request",
    "get_write_session",
]


async def get_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped **read** session.

    Read endpoints do not commit; a rollback on exit releases the connection
    without leaving an idle transaction open.

    A writing endpoint must not use this - the rollback would discard its work
    while any side effect outside the database (staged upload bytes) survived.
    Use :func:`get_write_session`.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def get_write_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped **write** session, committed on a clean response.

    Separate from :func:`get_session` so that writing is deliberate rather than
    ambient: almost every endpoint here is a read, and a factory that committed by
    default would make an accidental write silent.

    The commit happens before the response is serialised, so a 202 that says
    "queued" is backed by a durable batch the worker can actually find.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
WriteSessionDep = Annotated[AsyncSession, Depends(get_write_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_page_request(
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1, description="1-indexed page number.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PageRequest:
    """Normalise pagination against the configured maximum."""
    return PageRequest(page=page, page_size=page_size).normalised(
        max_page_size=settings.api.max_page_size
    )


PageDep = Annotated[PageRequest, Depends(get_page_request)]


def get_fleet_repo(session: SessionDep) -> FleetRepository:
    return FleetRepository(session)


def get_file_repo(session: SessionDep) -> TelemetryFileRepository:
    return TelemetryFileRepository(session)


def get_run_repo(session: SessionDep) -> IngestionRunRepository:
    return IngestionRunRepository(session)


def get_quality_repo(session: SessionDep) -> QualityRepository:
    return QualityRepository(session)


def get_frame_repo(session: SessionDep) -> FrameRepository:
    return FrameRepository(session)


def get_upload_repo(session: SessionDep) -> UploadRepository:
    return UploadRepository(session)


def get_upload_service(session: WriteSessionDep, settings: SettingsDep) -> UploadService:
    """The one writing dependency in the API: staging an upload batch."""
    return build_upload_service(session, settings=settings)


def get_metrics_service(session: SessionDep, settings: SettingsDep) -> MetricsService:
    return build_metrics_service(session, settings=settings)


def get_coverage_service(session: SessionDep, settings: SettingsDep) -> CoverageService:
    return build_coverage_service(session, settings=settings)


def get_silver_repo(session: SessionDep) -> SilverRepository:
    return SilverRepository(session)


def get_normalization_service(
    session: WriteSessionDep, settings: SettingsDep
) -> NormalizationService:
    return build_normalization_service(session, settings=settings)


FleetRepoDep = Annotated[FleetRepository, Depends(get_fleet_repo)]
FileRepoDep = Annotated[TelemetryFileRepository, Depends(get_file_repo)]
RunRepoDep = Annotated[IngestionRunRepository, Depends(get_run_repo)]
QualityRepoDep = Annotated[QualityRepository, Depends(get_quality_repo)]
FrameRepoDep = Annotated[FrameRepository, Depends(get_frame_repo)]
UploadRepoDep = Annotated[UploadRepository, Depends(get_upload_repo)]
UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]
MetricsServiceDep = Annotated[MetricsService, Depends(get_metrics_service)]
CoverageServiceDep = Annotated[CoverageService, Depends(get_coverage_service)]
SilverRepoDep = Annotated[SilverRepository, Depends(get_silver_repo)]
NormalizationServiceDep = Annotated[NormalizationService, Depends(get_normalization_service)]


def get_historical_service(session: SessionDep) -> HistoricalContinuityService:
    return build_historical_service(session)


def get_research_access(session: SessionDep) -> ResearchDataAccessLayer:
    return build_research_access(session)


HistoricalServiceDep = Annotated[HistoricalContinuityService, Depends(get_historical_service)]
ResearchAccessDep = Annotated[ResearchDataAccessLayer, Depends(get_research_access)]


def get_event_repo(session: SessionDep) -> EventRepository:
    return EventRepository(session)


def get_event_service(session: WriteSessionDep) -> EventReconstructionService:
    return build_event_service(session)


EventRepoDep = Annotated[EventRepository, Depends(get_event_repo)]
EventServiceDep = Annotated[EventReconstructionService, Depends(get_event_service)]


def get_research_service(session: WriteSessionDep) -> ResearchService:
    return build_research_service(session)


ResearchServiceDep = Annotated[ResearchService, Depends(get_research_service)]
