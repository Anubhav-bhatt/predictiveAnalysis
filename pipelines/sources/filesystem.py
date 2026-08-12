"""Local filesystem telemetry source - the only adapter implemented in Phase 1A.

Everything here is deliberately confined to this module.  No other part of the
pipeline imports ``pathlib`` for source access, so replacing this with an SFTP
or S3 adapter requires no changes elsewhere.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import ClassVar

from backend.app.core.config import AcknowledgeStrategy
from backend.app.core.logging import get_logger
from backend.app.models.enums import SourceType
from pipelines.sources.base import (
    AcknowledgeOutcome,
    SourceFileMetadata,
    SourceFileRef,
    TelemetrySource,
    TelemetrySourceError,
)

__all__ = ["FilesystemTelemetrySource"]

logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024


class FilesystemTelemetrySource(TelemetrySource):
    """Discovers telemetry files in a local inbox directory."""

    source_type: ClassVar[SourceType] = SourceType.FILESYSTEM

    def __init__(
        self,
        inbox: Path,
        *,
        pattern: str = "*.csv",
        allowed_extensions: Sequence[str] = (".csv",),
        max_file_size_bytes: int | None = None,
        ack_strategy: AcknowledgeStrategy = AcknowledgeStrategy.NONE,
        archive_dir: Path | None = None,
    ) -> None:
        self._inbox = Path(inbox)
        self._pattern = pattern
        self._allowed = {ext.lower() for ext in allowed_extensions}
        self._max_size = max_file_size_bytes
        self._ack_strategy = ack_strategy
        self._archive_dir = Path(archive_dir) if archive_dir else None

    # -- discovery ---------------------------------------------------------

    async def discover(self) -> Sequence[SourceFileRef]:
        if not self._inbox.exists():
            return []

        def _scan() -> list[SourceFileRef]:
            found: list[SourceFileRef] = []
            now = dt.datetime.now(dt.UTC)
            for path in sorted(self._inbox.glob(self._pattern)):
                if not path.is_file():
                    continue
                # Extension is an untrusted hint, but it is still the cheapest
                # first filter; content is validated later regardless.
                if self._allowed and path.suffix.lower() not in self._allowed:
                    logger.debug("source.skip.extension", filename=path.name)
                    continue
                stat = path.stat()
                found.append(
                    SourceFileRef(
                        source_type=self.source_type,
                        reference=str(path.resolve()),
                        display_name=path.name,
                        size_bytes=stat.st_size,
                        discovered_at=now,
                        extra={
                            "modified_at": dt.datetime.fromtimestamp(
                                stat.st_mtime, tz=dt.UTC
                            ).isoformat()
                        },
                    )
                )
            return found

        return await asyncio.to_thread(_scan)

    # -- transfer ----------------------------------------------------------

    def fetch(self, ref: SourceFileRef) -> AsyncIterator[bytes]:
        # Matches the base contract exactly: returns the async iterator itself,
        # so callers use ``async for`` and never ``await`` the call.
        return self._stream(ref)

    async def _stream(self, ref: SourceFileRef) -> AsyncIterator[bytes]:
        path = self._validated_path(ref)

        def _read(handle: object) -> bytes:
            return handle.read(_CHUNK_SIZE)  # type: ignore[attr-defined,no-any-return]

        transferred = 0
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(_read, handle)
                if not chunk:
                    break
                transferred += len(chunk)
                if self._max_size is not None and transferred > self._max_size:
                    raise TelemetrySourceError(
                        f"File exceeds the configured maximum of {self._max_size} bytes"
                    )
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def metadata(self, ref: SourceFileRef) -> SourceFileMetadata:
        path = self._validated_path(ref)
        stat = await asyncio.to_thread(path.stat)
        return SourceFileMetadata(
            size_bytes=stat.st_size,
            modified_at=dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC),
            content_type=None,
        )

    async def acknowledge(self, ref: SourceFileRef, outcome: AcknowledgeOutcome) -> None:
        if self._ack_strategy is AcknowledgeStrategy.NONE:
            return
        if outcome is AcknowledgeOutcome.FAILED:
            # Leave failures in the inbox so they can be retried after a fix.
            return
        if self._archive_dir is None:
            return

        def _move() -> None:
            source = Path(ref.reference)
            if not source.exists():
                return
            self._archive_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            target = self._archive_dir / source.name  # type: ignore[operator]
            if target.exists():
                stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%f")
                target = target.with_name(f"{target.stem}.{stamp}{target.suffix}")
            source.replace(target)

        await asyncio.to_thread(_move)

    # -- internals ---------------------------------------------------------

    def _validated_path(self, ref: SourceFileRef) -> Path:
        """Confine a reference to the configured inbox.

        A reference is data, and data is untrusted; without this check a crafted
        reference could read arbitrary files.
        """
        path = Path(ref.reference).resolve()
        inbox = self._inbox.resolve()
        if not path.is_relative_to(inbox):
            raise TelemetrySourceError(
                f"Reference escapes the configured inbox: {ref.display_name}"
            )
        if not path.is_file():
            raise TelemetrySourceError(f"Source file no longer exists: {ref.display_name}")
        return path
