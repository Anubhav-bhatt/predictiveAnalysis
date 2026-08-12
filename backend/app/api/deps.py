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
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.services.coverage_service import CoverageService
from backend.app.services.factory import build_coverage_service, build_metrics_service
from backend.app.services.metrics_service import MetricsService

__all__ = [
    "CoverageServiceDep",
    "FleetRepoDep",
    "MetricsServiceDep",
    "PageDep",
    "RunRepoDep",
    "SessionDep",
    "SettingsDep",
    "get_page_request",
]


async def get_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped session.

    Read endpoints do not commit; a rollback on exit releases the connection
    without leaving an idle transaction open.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
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


def get_metrics_service(session: SessionDep, settings: SettingsDep) -> MetricsService:
    return build_metrics_service(session, settings=settings)


def get_coverage_service(session: SessionDep, settings: SettingsDep) -> CoverageService:
    return build_coverage_service(session, settings=settings)


FleetRepoDep = Annotated[FleetRepository, Depends(get_fleet_repo)]
FileRepoDep = Annotated[TelemetryFileRepository, Depends(get_file_repo)]
RunRepoDep = Annotated[IngestionRunRepository, Depends(get_run_repo)]
QualityRepoDep = Annotated[QualityRepository, Depends(get_quality_repo)]
MetricsServiceDep = Annotated[MetricsService, Depends(get_metrics_service)]
CoverageServiceDep = Annotated[CoverageService, Depends(get_coverage_service)]
