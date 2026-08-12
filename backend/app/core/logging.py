"""Structured logging (section 19).

Every ingestion operation carries ``ingestion_run_id``, ``telemetry_file_id``
and - when the work was initiated through the API - ``request_id``.  Those are
bound to structlog context variables rather than threaded through every call
signature, so a log line emitted deep inside the profiler still carries them.

Telemetry row contents are never logged.  ``safe_preview`` is the only
sanctioned way to put a source-derived value into a log line, and it truncates.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import structlog

_MAX_PREVIEW_CHARS = 64

_CONTEXT_KEYS = ("request_id", "ingestion_run_id", "telemetry_file_id")


def safe_preview(value: object, *, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    """Render a source-derived value for logging without leaking a whole row."""
    if value is None:
        return "<null>"
    text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...<truncated {len(text) - max_chars} chars>"


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configure structlog + stdlib logging once, for whichever runtime we are."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        # A stdlib factory, not PrintLoggerFactory: ``add_logger_name`` reads
        # ``logger.name``, which structlog's PrintLogger does not have. Pairing the
        # two raises AttributeError on the first WARNING - a failure that hides
        # itself whenever the level filters INFO out. Emission still lands on
        # stderr via the basicConfig below.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=numeric_level,
        force=True,
    )
    # asyncpg / sqlalchemy chatter stays out of the ingestion narrative.
    for noisy in ("sqlalchemy.engine", "asyncpg", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def _stringify(value: object) -> object:
    return str(value) if isinstance(value, UUID) else value


def bind_log_context(**values: object) -> None:
    """Bind correlation identifiers for the current task/request."""
    structlog.contextvars.bind_contextvars(
        **{key: _stringify(val) for key, val in values.items() if val is not None}
    )


def clear_log_context(*keys: str) -> None:
    structlog.contextvars.unbind_contextvars(*(keys or _CONTEXT_KEYS))


@contextmanager
def log_context(**values: object) -> Iterator[None]:
    """Scope correlation identifiers to a block, restoring the prior state."""
    tokens = structlog.contextvars.bind_contextvars(
        **{key: _stringify(val) for key, val in values.items() if val is not None}
    )
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
