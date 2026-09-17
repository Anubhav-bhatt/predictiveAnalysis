"""Reconstructed source frames and their provenance (Phase 1D sections 25-29).

Three tables, each with a distinct job:

``telemetry_source_frame``
    One coherent charger snapshot at one event timestamp. Identity is
    ``(charger_id, event_time, frame_sequence, reconstruction_version)`` -
    deliberately **not** ``(charger_id, event_time)``, because genuinely distinct
    frames sharing one second demonstrably exist and a two-column key would make
    them collide (section 27).

``telemetry_frame_source``
    Which files a frame's rows came from. A canonical frame can legitimately be
    sourced from two overlapping daily files, so this is a separate table rather
    than a column - duplicating the frame per file would defeat the point of
    recognising it as one observation (section 24).

``telemetry_frame_row``
    Frame back to the exact source rows. It stores identity, position and a
    fingerprint - never the 449 telemetry values. Bronze remains the only copy of
    those (section 29).

No sub-second timestamp is ever fabricated. ``frame_sequence`` carries the
ordering, and it means *source order*, not proven device timing.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import (
    Base,
    JSONVariant,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
    enum_column,
    utcnow,
)
from backend.app.models.enums import DuplicateClassification, FrameStatus

if TYPE_CHECKING:
    from backend.app.models.charger import Charger
    from backend.app.models.telemetry_file import TelemetryFile


class TelemetrySourceFrame(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_source_frame"

    charger_pk: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("charger.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Denormalised so a frame from an unregistered charger is still storable.
    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    #: Authoritative telemetry time, from the source content only.
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False)
    #: Business date in the charger's source timezone, mirroring Phase 1C so
    #: charger-day queries do not need a timezone conversion at read time.
    business_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    #: 0-based ordinal among frames sharing this event timestamp.
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: SHA-256 over the frame's canonical payload; equal payloads match across
    #: files, which is what makes cross-file replay detection possible.
    frame_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    frame_status: Mapped[FrameStatus] = mapped_column(enum_column(FrameStatus), nullable=False)
    duplicate_classification: Mapped[DuplicateClassification] = mapped_column(
        enum_column(DuplicateClassification), nullable=False
    )
    #: Set when this frame replays another. Self-referential, SET NULL so removing
    #: a canonical frame cannot orphan the row.
    replay_of_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="SET NULL"), nullable=True
    )

    expected_position_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    observed_position_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    missing_position_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    unexpected_position_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    completeness_percentage: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3), nullable=True)

    #: Source row span this frame occupies, for provenance without a join.
    source_order_min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_order_max: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Algorithm version. Part of the identity so a re-reconstruction under a new
    #: version is additive and historical output stays attributable (section 32).
    reconstruction_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: Missing/unexpected positions and small diagnostics. Never telemetry values.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    charger: Mapped[Charger | None] = relationship()
    replay_of: Mapped[TelemetrySourceFrame | None] = relationship(
        remote_side="TelemetrySourceFrame.id"
    )
    sources: Mapped[list[TelemetryFrameSource]] = relationship(
        back_populates="frame", cascade="all, delete-orphan"
    )
    frame_rows: Mapped[list[TelemetryFrameRow]] = relationship(
        back_populates="frame",
        cascade="all, delete-orphan",
        order_by="TelemetryFrameRow.source_row_number",
    )

    __table_args__ = (
        # Frame identity. event_time alone is insufficient - same-second distinct
        # frames exist - and the version keeps reprocessing additive.
        sa.UniqueConstraint(
            "charger_id",
            "event_time",
            "frame_sequence",
            "reconstruction_version",
            name="uq_telemetry_source_frame_identity",
        ),
        # Charger + time range is the dominant read pattern.
        sa.Index("ix_telemetry_source_frame_charger_time", "charger_id", "event_time"),
        sa.Index("ix_telemetry_source_frame_charger_date", "charger_id", "business_date"),
        sa.Index("ix_telemetry_source_frame_business_date", "business_date"),
        # Cross-file replay lookup: find frames carrying an identical payload.
        sa.Index("ix_telemetry_source_frame_fingerprint", "charger_id", "frame_fingerprint"),
        sa.Index("ix_telemetry_source_frame_status", "frame_status"),
        sa.Index("ix_telemetry_source_frame_classification", "duplicate_classification"),
        sa.CheckConstraint("frame_sequence >= 0", name="frame_sequence_non_negative"),
        sa.CheckConstraint("observed_position_count >= 0", name="observed_position_non_negative"),
    )

    @property
    def is_canonical(self) -> bool:
        """Whether Phase 1E should consume this frame by default."""
        return self.duplicate_classification in {
            DuplicateClassification.UNIQUE,
            DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TelemetrySourceFrame {self.charger_id} {self.event_time.isoformat()}"
            f"#{self.frame_sequence} {self.frame_status}/{self.duplicate_classification}>"
        )


class TelemetryFrameSource(UUIDPrimaryKeyMixin, Base):
    """A file that contributed rows to a frame (section 28)."""

    __tablename__ = "telemetry_frame_source"

    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telemetry_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )

    first_source_row: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    last_source_row: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: 0 for the file that first carried this payload; higher for later
    #: appearances of the same frame in other files.
    source_occurrence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: The file the canonical frame is attributed to.
    is_primary_source: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)

    frame: Mapped[TelemetrySourceFrame] = relationship(back_populates="sources")
    telemetry_file: Mapped[TelemetryFile] = relationship()

    __table_args__ = (
        sa.UniqueConstraint(
            "frame_id", "telemetry_file_id", name="uq_telemetry_frame_source_identity"
        ),
        sa.Index("ix_telemetry_frame_source_file", "telemetry_file_id"),
    )


class TelemetryFrameRow(UUIDPrimaryKeyMixin, Base):
    """Frame-to-raw-row provenance (section 29).

    Deliberately narrow: identity, position and fingerprint only. Storing the 449
    telemetry values here would make this table a second copy of Bronze.
    """

    __tablename__ = "telemetry_frame_row"

    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telemetry_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Row's position in the original file, captured before any sort.
    source_row_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    #: Entity identity as strings: the source contract does not guarantee numeric
    #: connector or SMR ids. NULL where the row could not be assigned.
    connector_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    smr_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: Rendered logical position, e.g. "C1/S3".
    logical_position: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    #: Which occurrence of this logical key the row is, in source order.
    occurrence_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    row_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: True for rows retained without a resolvable entity identity (section 22).
    unassigned: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)

    frame: Mapped[TelemetrySourceFrame] = relationship(back_populates="frame_rows")
    telemetry_file: Mapped[TelemetryFile] = relationship()

    __table_args__ = (
        # One row of one file occupies one slot of one frame.
        sa.UniqueConstraint(
            "frame_id",
            "telemetry_file_id",
            "source_row_number",
            name="uq_telemetry_frame_row_identity",
        ),
        sa.Index("ix_telemetry_frame_row_file_row", "telemetry_file_id", "source_row_number"),
        sa.Index("ix_telemetry_frame_row_position", "logical_position"),
        sa.CheckConstraint("source_row_number >= 0", name="source_row_non_negative"),
    )
