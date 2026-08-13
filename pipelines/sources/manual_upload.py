"""Manual upload source adapter (Phase 1C.5 sections 3, 4).

**Manual upload is the initial POC acquisition path. It is not a separate
analytical workflow.** This adapter's entire job is to hand already-staged bytes to
the common ingestion pipeline. It contains no profiling, no schema rules, no quality
rules, no coverage logic and no frame reconstruction — those belong to the shared
pipeline, which cannot tell how a file arrived.

The split that makes source independence real:

``HTTP request``
    Streams uploaded bytes into a staging directory, records one
    ``upload_batch_file`` row per file, returns a batch id. Cheap and bounded.

``Worker``
    Constructs this adapter over the staged files and runs *exactly* the same
    ``IngestionService.run`` that the filesystem source uses. From that point on
    nothing branches on source type.

Staging is deliberately distinct from Bronze. A staged file has not yet been
accepted as a telemetry file: it has no checksum identity in the platform, and if
it turns out to be a duplicate it never becomes one. Bronze remains the immutable
record of files the platform *did* accept.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import ClassVar

from backend.app.core.logging import get_logger
from backend.app.models.enums import SourceType
from pipelines.sources.base import (
    AcknowledgeOutcome,
    SourceFileMetadata,
    SourceFileRef,
    TelemetrySource,
    TelemetrySourceError,
)

__all__ = ["ManualUploadTelemetrySource", "StagedUpload"]

logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024


class StagedUpload:
    """One file already written to the staging area.

    ``original_filename`` is metadata only. It is never used to build a path, and
    it is never trusted to indicate a telemetry date - the event timestamps inside
    the file remain authoritative (Phase 1C section 8).
    """

    __slots__ = ("original_filename", "size_bytes", "staged_path", "staged_at")

    def __init__(
        self,
        *,
        staged_path: Path,
        original_filename: str,
        size_bytes: int,
        staged_at: dt.datetime | None = None,
    ) -> None:
        self.staged_path = staged_path
        self.original_filename = original_filename
        self.size_bytes = size_bytes
        self.staged_at = staged_at or dt.datetime.now(dt.UTC)


class ManualUploadTelemetrySource(TelemetrySource):
    """Presents staged uploads through the standard source contract."""

    source_type: ClassVar[SourceType] = SourceType.MANUAL_UPLOAD

    def __init__(
        self,
        staged: Sequence[StagedUpload],
        *,
        staging_root: Path,
        max_size_bytes: int | None = None,
        delete_on_success: bool = True,
    ) -> None:
        self._staged = list(staged)
        # Resolved once; every path is checked against it so a crafted reference
        # cannot read outside the staging area.
        self._staging_root = Path(staging_root).resolve()
        self._max_size = max_size_bytes
        self._delete_on_success = delete_on_success
        self._by_reference = {
            str(item.staged_path.resolve()): item for item in self._staged
        }

    # -- discovery ---------------------------------------------------------

    async def discover(self) -> Sequence[SourceFileRef]:
        """Enumerate the staged files of this batch.

        Unlike the filesystem source this does not scan a directory: the batch's
        membership was fixed when the upload request completed, so discovery is a
        listing of what was staged rather than of whatever happens to be on disk.
        That keeps two concurrent batches from stealing each other's files.
        """
        refs: list[SourceFileRef] = []
        for item in self._staged:
            resolved = item.staged_path.resolve()
            if not self._is_inside_staging(resolved):
                # Defensive: a reference outside staging is a bug or an attack,
                # never a file to ingest.
                logger.warning(
                    "manual_upload.reference_outside_staging",
                    original_filename=item.original_filename,
                )
                continue
            if not resolved.exists():
                logger.warning(
                    "manual_upload.staged_file_missing",
                    original_filename=item.original_filename,
                )
                continue
            refs.append(
                SourceFileRef(
                    source_type=self.source_type,
                    reference=str(resolved),
                    display_name=item.original_filename,
                    size_bytes=item.size_bytes,
                    discovered_at=item.staged_at,
                    extra={"acquisition": "manual_upload"},
                )
            )
        return refs

    # -- transfer ----------------------------------------------------------

    def fetch(self, ref: SourceFileRef) -> AsyncIterator[bytes]:
        """Stream a staged file's bytes.

        Matches the base contract exactly (returns the iterator, not a coroutine),
        so ``IngestionService`` consumes filesystem and uploaded files with the
        same code path.
        """
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
                        f"Staged file exceeds the configured maximum of "
                        f"{self._max_size} bytes"
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
            extra={"acquisition": "manual_upload"},
        )

    async def acknowledge(self, ref: SourceFileRef, outcome: AcknowledgeOutcome) -> None:
        """Release staged bytes once the pipeline has taken responsibility.

        A processed or duplicate file is safe to remove: Bronze holds the accepted
        copy, and a duplicate's content is provably already stored. Failures and
        quarantines are **kept** so an operator can inspect what was actually
        uploaded before deciding to retry.
        """
        if not self._delete_on_success:
            return
        if outcome in {AcknowledgeOutcome.FAILED, AcknowledgeOutcome.QUARANTINED}:
            return

        path = self._validated_path(ref)
        try:
            await asyncio.to_thread(path.unlink, True)
        except OSError as exc:  # pragma: no cover - best-effort cleanup
            logger.warning(
                "manual_upload.staged_cleanup_failed",
                original_filename=ref.display_name,
                error=str(exc),
            )

    # -- safety ------------------------------------------------------------

    def _is_inside_staging(self, candidate: Path) -> bool:
        return candidate.is_relative_to(self._staging_root)

    def _validated_path(self, ref: SourceFileRef) -> Path:
        """Resolve a reference, refusing anything outside the staging root.

        The reference is produced by this adapter, but it round-trips through the
        pipeline, so it is re-validated rather than trusted.
        """
        if ref.source_type is not self.source_type:
            raise TelemetrySourceError(
                f"Reference belongs to {ref.source_type.value}, not "
                f"{self.source_type.value}"
            )

        raw = Path(ref.reference)
        # Checked *before* resolving: resolve() dereferences the link, so asking
        # the resolved path whether it is a symlink can never be true. Staged files
        # are written by the platform and are never links, so a link here means the
        # reference was tampered with.
        if raw.is_symlink():
            raise TelemetrySourceError("Staged reference is a symlink and was refused")

        candidate = raw.resolve()
        if not self._is_inside_staging(candidate):
            raise TelemetrySourceError(
                "Staged reference escapes the staging root and was refused"
            )
        if not candidate.is_file():
            raise TelemetrySourceError(f"Staged file no longer exists: {ref.display_name}")
        return candidate

    def staged_for(self, ref: SourceFileRef) -> StagedUpload | None:
        return self._by_reference.get(str(Path(ref.reference).resolve()))

    def describe(self) -> str:
        return f"{type(self).__name__}({self.source_type.value}, {len(self._staged)} staged)"
