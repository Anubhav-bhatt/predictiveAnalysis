"""Per-field observations for one file (section 24).

These are statements about *this file on this day only*.  A field that is
all-null here may simply be an alarm that did not fire; that is why the
classification enum is named ``ALL_NULL_IN_SAMPLE`` and never anything that
sounds like a global judgement (section 29).

Statistics are computed only where they mean something: no mean of a charger id,
no standard deviation of a timestamp.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, UUIDPrimaryKeyMixin, enum_column
from backend.app.models.enums import VariabilityClass

if TYPE_CHECKING:
    from backend.app.models.telemetry_file import TelemetryFile

#: Cap on how many distinct values are retained for a categorical field.
MAX_OBSERVED_VALUES = 50
#: Cap on example values kept for any field.
MAX_EXAMPLE_VALUES = 5


class FieldProfile(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "field_profile"

    telemetry_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("field_definition.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source_name: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    source_occurrence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    source_position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    null_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    null_percentage: Mapped[Decimal] = mapped_column(
        sa.Numeric(6, 3), nullable=False, default=Decimal(0)
    )
    unique_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)

    variability_class: Mapped[VariabilityClass] = mapped_column(
        enum_column(VariabilityClass), nullable=False, default=VariabilityClass.VARIABLE_IN_SAMPLE
    )

    # Textual min/max are safe for any type; numeric statistics are populated
    # only when the semantic type is numeric and parsing actually succeeded.
    min_value: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    max_value: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    numeric_valid_count: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    mean_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    median_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    stddev_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    sentinel_hit_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)

    example_values: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    observed_values: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    telemetry_file: Mapped[TelemetryFile] = relationship(back_populates="field_profiles")

    __table_args__ = (
        sa.UniqueConstraint(
            "telemetry_file_id", "source_position", name="uq_field_profile_file_position"
        ),
        sa.Index("ix_field_profile_variability", "variability_class"),
        sa.CheckConstraint("null_count >= 0", name="null_count_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<FieldProfile {self.source_name}#{self.source_occurrence} {self.variability_class}>"
        )
