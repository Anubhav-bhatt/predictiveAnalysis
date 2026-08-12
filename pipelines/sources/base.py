"""Telemetry source contract (Phase 1A section 4).

Downstream stages - profiling, schema validation, quality, persistence - must
never know where a file came from.  They receive bytes and metadata, nothing
else.  That is why :meth:`TelemetrySource.fetch` yields chunks rather than
returning a path: a path is a filesystem concept, and committing to it here
would leak the local filesystem into every later stage and make SFTP, S3, Azure
Blob or an HTTP API impossible to add without rewriting them.

An adapter has four responsibilities:

``discover``     enumerate what is available right now
``fetch``        stream one file's bytes
``metadata``     report what the source knows about a file, without reading it
``acknowledge``  tell the source how processing ended, so it can advance state
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

from backend.app.models.enums import SourceType

__all__ = [
    "AcknowledgeOutcome",
    "SourceFileMetadata",
    "SourceFileRef",
    "TelemetrySource",
    "TelemetrySourceError",
]


class TelemetrySourceError(RuntimeError):
    """The source itself failed - not the file's content."""


class AcknowledgeOutcome(StrEnum):
    """How the pipeline finished with a file, reported back to the source."""

    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SourceFileRef:
    """An opaque handle to one file at a source.

    ``reference`` is meaningful only to the adapter that produced it.  Nothing
    downstream parses it, and it is never exposed through the public API.
    """

    source_type: SourceType
    reference: str
    display_name: str
    size_bytes: int
    discovered_at: dt.datetime
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceFileMetadata:
    """What the source can say about a file without transferring it."""

    size_bytes: int
    modified_at: dt.datetime | None = None
    content_type: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)


class TelemetrySource(ABC):
    """Base class for every telemetry source adapter."""

    source_type: ClassVar[SourceType]

    @abstractmethod
    async def discover(self) -> Sequence[SourceFileRef]:
        """List files currently available for ingestion."""

    @abstractmethod
    def fetch(self, ref: SourceFileRef) -> AsyncIterator[bytes]:
        """Stream a file's bytes.

        Streaming rather than returning the whole payload keeps memory bounded
        regardless of file size, and lets the checksum be computed in the same
        pass that writes to Bronze storage.
        """

    @abstractmethod
    async def metadata(self, ref: SourceFileRef) -> SourceFileMetadata:
        """Return source-side metadata. Treated as untrusted (section 20)."""

    @abstractmethod
    async def acknowledge(self, ref: SourceFileRef, outcome: AcknowledgeOutcome) -> None:
        """Report the processing outcome so the source can advance its state."""

    def describe(self) -> str:
        return f"{type(self).__name__}({self.source_type.value})"
