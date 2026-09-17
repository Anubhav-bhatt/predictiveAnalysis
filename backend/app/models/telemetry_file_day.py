"""One file's contribution to one telemetry business date (Phase 1C sections 8, 19).

This table exists because of a hard requirement that nothing else in the schema
satisfies: **a charger-day must be rebuildable without re-reading the raw CSV.**

Three Phase 1C rules force that:

* A file may span several dates (section 8), so "one file = one business date" is
  wrong.  Each *actual* telemetry date gets its own row here.
* Several files may combine into one charger-day (section 19), so coverage is the
  union of their timestamp sets - not any single file's view.
* Reconciliation must be idempotent and cheap (section 24), so a late file
  arriving days later has to be merged with what is already known without
  re-parsing 16.5 MB per charger-day.

``event_second_offsets`` is what makes that possible.  It stores the *unique*
event timestamps of this file on this date as seconds from local midnight in the
charger's source timezone - sorted, de-duplicated, delta-free integers.  For a
120-second cadence that is ~720 small integers per charger-day, which is cheap to
store and exact enough to recompute coverage, cadence and every gap boundary.

Deliberately *not* stored here: the raw telemetry values.  Bronze already owns
those, and duplicating them would make this table enormous for no gain.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, JSONVariant, TimestampMixin, UtcDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.telemetry_file import TelemetryFile


class TelemetryFileDay(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_file_day"

    telemetry_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Denormalised from the file's identifiers so reconciliation can group by
    #: charger without joining through telemetry_file_identifier.
    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    #: Derived from event timestamps in the charger's source timezone. Never from
    #: the filename, received_at or processing time (section 8).
    business_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    first_event_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_event_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    #: Distinct event timestamps this file contributes to this date. This is the
    #: coverage signal - never row_count (section 11).
    unique_timestamp_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: Raw rows belonging to this date. Retained for the raw-vs-unique contrast
    #: that the daily report has to make explicit, never used as coverage.
    row_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: Seconds from local midnight for each unique timestamp, sorted ascending.
    #: The exact input to gap detection on re-reconciliation.
    event_second_offsets: Mapped[list[int]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )

    #: Topology observed in the source file. Values are strings because the
    #: source contract does not guarantee numeric connector/SMR ids (section 26).
    connectors_seen: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    smrs_seen: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)

    #: Duplication quantified, never resolved - that is Phase 1D's job.
    duplicate_timestamp_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    logical_collision_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    exact_duplicate_row_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: Timezone the offsets were computed in, so a later configuration change is
    #: detectable rather than silently reinterpreting stored offsets.
    source_timezone: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="UTC")

    telemetry_file: Mapped[TelemetryFile] = relationship(back_populates="file_days")

    __table_args__ = (
        # Recomputing a file's contribution replaces this row rather than adding
        # a second one - the basis of reconciliation idempotency (section 41).
        sa.UniqueConstraint(
            "telemetry_file_id", "business_date", name="uq_telemetry_file_day_identity"
        ),
        sa.Index("ix_telemetry_file_day_charger_date", "charger_id", "business_date"),
        sa.Index("ix_telemetry_file_day_business_date", "business_date"),
        sa.CheckConstraint("unique_timestamp_count >= 0", name="unique_timestamp_non_negative"),
        sa.CheckConstraint("row_count >= 0", name="row_count_non_negative"),
    )

    def timestamps_utc(self) -> list[dt.datetime]:
        """Rehydrate the stored offsets into UTC-aware timestamps.

        The inverse of what the builder wrote: local midnight of the business
        date in the recorded source timezone, plus each offset.
        """
        from pipelines.profiling.event_time import resolve_timezone

        tzinfo = resolve_timezone(self.source_timezone)
        midnight = dt.datetime.combine(self.business_date, dt.time.min, tzinfo=tzinfo)
        return [
            (midnight + dt.timedelta(seconds=int(offset))).astimezone(dt.UTC)
            for offset in self.event_second_offsets
        ]

    def as_dict(self) -> dict[str, Any]:  # pragma: no cover - diagnostics helper
        return {
            "telemetry_file_id": str(self.telemetry_file_id),
            "charger_id": self.charger_id,
            "business_date": self.business_date.isoformat(),
            "unique_timestamp_count": self.unique_timestamp_count,
            "row_count": self.row_count,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TelemetryFileDay {self.charger_id} {self.business_date} "
            f"unique={self.unique_timestamp_count} rows={self.row_count}>"
        )
