"""FastAPI application factory.

The app is deliberately thin: it wires configuration, logging, CORS, error
handling and the v1 router, and owns no business logic.  Every request-scoped
dependency is resolved through ``api.deps``, so the same services back the API,
the CLI and the tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1 import api_router
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
)
from backend.app.db.session import dispose_engine
from backend.app.schemas.common import ApiError, Envelope

logger = get_logger(__name__)

__all__ = ["create_app"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "api.startup",
        environment=settings.environment.value,
        source_timezone=settings.fleet.default_source_timezone,
    )
    try:
        yield
    finally:
        # Pooled connections must be released or a reload leaves them dangling.
        await dispose_engine()
        logger.info("api.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    configure_logging(config.log_level, json_output=config.log_format.value == "json")

    app = FastAPI(
        title="Charger Predictive Intelligence Platform",
        version="0.1.0",
        summary="Phase 1 operational data platform for EV charger telemetry.",
        description=(
            "Phase 1A-1C: telemetry ingestion, the charger data dictionary and "
            "quality engine, and daily fleet coverage, completeness and telemetry "
            "gap detection. No predictive endpoints exist yet by design."
        ),
        lifespan=_lifespan,
    )
    app.state.settings = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _correlate(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        """Attach a request id to every log line and response header."""
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        bind_log_context(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            clear_log_context("request_id")
        response.headers["x-request-id"] = request_id
        return response

    # -- error handling: one envelope shape, including for failures -------

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        envelope = Envelope[None](
            data=None,
            meta={"path": request.url.path},
            error=ApiError(code=f"HTTP_{exc.status_code}", message=str(exc.detail)),
        )
        return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        envelope = Envelope[None](
            data=None,
            meta={"path": request.url.path},
            error=ApiError(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details={"errors": exc.errors()},
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable(envelope),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The message is deliberately generic: internal detail stays in the logs.
        logger.exception("api.unhandled_error", path=request.url.path)
        envelope = Envelope[None](
            data=None,
            meta={"path": request.url.path},
            error=ApiError(code="INTERNAL_ERROR", message="Internal server error"),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": config.environment.value}

    app.include_router(api_router)
    return app


def jsonable(envelope: Envelope[None]) -> dict[str, object]:
    """Serialise an envelope whose ``details`` may hold non-JSON primitives."""
    from fastapi.encoders import jsonable_encoder

    return dict(jsonable_encoder(envelope))


app = create_app()
