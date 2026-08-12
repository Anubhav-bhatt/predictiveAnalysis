"""Bronze raw-object storage (Phase 1A section 5).

The landing zone holds the original bytes, unmodified, forever.  Two properties
matter and are enforced here rather than by convention:

* **Immutability.**  Objects are written to a temporary name, fsynced, then
  atomically renamed into place and stripped of write permission.  A partially
  written object can never be observed under its final reference.
* **Safe naming.**  The stored name is derived from the internal file id plus a
  sanitised original filename.  A hostile ``../../etc/passwd`` filename cannot
  escape the root, and the original name survives untouched in the database.

``RawObjectStorage`` is a Protocol so object storage can replace the filesystem
implementation without profiling, quality or persistence code changing.  The
only capability those layers need is ``materialize_local``, which for S3 or
Azure would download to a scratch path and clean up on exit.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, BinaryIO, Protocol
from uuid import UUID

__all__ = [
    "LocalFilesystemRawStorage",
    "RawObjectStorage",
    "StoredObject",
    "safe_storage_name",
]

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LENGTH = 128
_CHUNK_SIZE = 1024 * 1024


def _write_chunk(handle: IO[bytes], chunk: bytes) -> int:
    """Single-signature wrapper so ``to_thread`` sees a concrete callable."""
    return handle.write(chunk)


def _open_incoming(target_dir: Path) -> tuple[IO[bytes], Path]:
    """Create the temp object that a transfer streams into.

    Wrapped in a concrete function so the binary mode - and therefore the handle
    type - is unambiguous to both the reader and the type checker.
    """
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed explicitly by the caller
        mode="w+b",
        dir=target_dir,
        prefix=".incoming-",
        suffix=".part",
        delete=False,
    )
    return handle, Path(handle.name)


def safe_storage_name(original: str) -> str:
    """Reduce an untrusted filename to something safe to place on disk.

    Path separators and traversal segments are removed rather than escaped, so
    the result can never resolve outside the storage root.
    """
    name = Path(original).name  # discards any directory component
    name = name.replace("..", "_")
    name = _UNSAFE_CHARS.sub("_", name).strip("._-")
    if not name:
        name = "telemetry"
    if len(name) > _MAX_NAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        keep = _MAX_NAME_LENGTH - (len(suffix) + 1 if dot else 0)
        name = f"{stem[:keep]}.{suffix}" if dot else name[:_MAX_NAME_LENGTH]
    return name


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The outcome of landing one file in the Bronze zone."""

    storage_reference: str
    sha256: str
    size_bytes: int


class RawObjectStorage(Protocol):
    """Storage contract shared by every source adapter and pipeline stage."""

    async def store(
        self,
        chunks: AsyncIterator[bytes],
        *,
        file_id: UUID,
        original_filename: str,
        received_at: datetime | None = None,
    ) -> StoredObject:
        """Stream bytes into immutable storage, returning checksum and size."""
        ...

    def materialize_local(self, storage_reference: str) -> AbstractContextManager[Path]:
        """Context manager yielding a local path for readers such as Polars.

        Declared as a context manager rather than an ``Iterator`` so that callers
        type-check under ``with``; ``@contextmanager`` implementations satisfy it.
        """
        ...

    def open(self, storage_reference: str) -> BinaryIO: ...

    def exists(self, storage_reference: str) -> bool: ...

    def quarantine(self, storage_reference: str, *, reason: str) -> str:
        """Copy an object into the quarantine zone, returning the new reference."""
        ...

    def discard(self, storage_reference: str) -> None:
        """Remove an object that was written but never registered.

        This is the only deletion path, and it exists solely for the duplicate
        case: the bytes are provably identical to an already-registered object,
        so nothing is lost. Registered objects remain immutable.
        """
        ...


class LocalFilesystemRawStorage:
    """Development/single-node implementation of :class:`RawObjectStorage`."""

    def __init__(self, raw_root: Path, quarantine_root: Path) -> None:
        self._raw_root = Path(raw_root)
        self._quarantine_root = Path(quarantine_root)
        self._raw_root.mkdir(parents=True, exist_ok=True)
        self._quarantine_root.mkdir(parents=True, exist_ok=True)

    # -- internals ---------------------------------------------------------

    def _resolve(self, storage_reference: str, root: Path | None = None) -> Path:
        """Resolve a reference under the root, refusing to escape it."""
        base = (root or self._raw_root).resolve()
        candidate = (base / storage_reference).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError(f"Storage reference escapes the storage root: {storage_reference!r}")
        return candidate

    # -- contract ----------------------------------------------------------

    async def store(
        self,
        chunks: AsyncIterator[bytes],
        *,
        file_id: UUID,
        original_filename: str,
        received_at: datetime | None = None,
    ) -> StoredObject:
        stamp = received_at or datetime.now(UTC)
        # Partition by *receipt* date.  This is a storage-layout decision only;
        # it is deliberately unrelated to the telemetry business date, which is
        # not known until the content has been parsed.
        relative_dir = Path(f"{stamp:%Y/%m/%d}")
        target_dir = self._raw_root / relative_dir
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)

        filename = f"{file_id}__{safe_storage_name(original_filename)}"
        target = target_dir / filename

        digest = hashlib.sha256()
        size = 0

        handle, temp_path = await asyncio.to_thread(_open_incoming, target_dir)
        try:
            # Every blocking operation is offloaded: a 16 MB write must not stall
            # the event loop that the API and worker share.
            async for chunk in chunks:
                if not chunk:
                    continue
                digest.update(chunk)
                size += len(chunk)
                await asyncio.to_thread(_write_chunk, handle, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
            await asyncio.to_thread(handle.close)
            # Atomic publish: readers see either nothing or the complete object.
            await asyncio.to_thread(temp_path.replace, target)
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temp_path.unlink, True)
            raise

        await asyncio.to_thread(target.chmod, 0o444)  # immutable after registration
        return StoredObject(
            storage_reference=str(relative_dir / filename),
            sha256=digest.hexdigest(),
            size_bytes=size,
        )

    @contextmanager
    def materialize_local(self, storage_reference: str) -> Iterator[Path]:
        path = self._resolve(storage_reference)
        if not path.exists():
            raise FileNotFoundError(f"Stored object is missing: {storage_reference}")
        yield path

    def open(self, storage_reference: str) -> BinaryIO:
        return self._resolve(storage_reference).open("rb")

    def exists(self, storage_reference: str) -> bool:
        try:
            return self._resolve(storage_reference).exists()
        except ValueError:
            return False

    def quarantine(self, storage_reference: str, *, reason: str) -> str:
        source = self._resolve(storage_reference)
        target = self._quarantine_root / Path(storage_reference).name
        target.parent.mkdir(parents=True, exist_ok=True)
        # The Bronze original is never moved or deleted; quarantine holds a copy
        # so operators can inspect it without touching the immutable record.
        shutil.copy2(source, target)
        target.with_suffix(target.suffix + ".reason.txt").write_text(reason, encoding="utf-8")
        return str(target.relative_to(self._quarantine_root))

    def discard(self, storage_reference: str) -> None:
        path = self._resolve(storage_reference)
        if path.exists():
            path.chmod(0o644)  # written read-only; must be writable to unlink
            path.unlink()
