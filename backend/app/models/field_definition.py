"""The enterprise data contract: one row per raw source position.

Identity is ``(schema_version, source_name, source_occurrence)``.  That triple is
what lets the two occurrences of ``Last Charge Session Stop Reason`` coexist
without ever resorting to Pandas-style ``.1`` mangling (sections 9 and 10).

Multi-valued attributes - sentinel values, allowed values, prediction domains -
are separate tables rather than JSON columns, because the quality engine and the
field API filter on them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from backend.app.models.enums import (
    AggregationStrategy,
    AvailabilitySemantics,
    CanonicalDataType,
    FieldCategory,
    FieldClass,
    FieldEntity,
    LeakageRisk,
    MlCandidate,
    NormalizationStrategy,
    PredictionDomain,
    RangeStatus,
    ReviewStatus,
    StorageStrategy,
)

if TYPE_CHECKING:
    from backend.app.models.schema_version import SchemaVersion


class FieldDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "field_definition"

    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("schema_version.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # --- raw source identity ---------------------------------------------
    source_name: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    source_occurrence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    source_position: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    # --- canonical identity ----------------------------------------------
    canonical_name: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # --- semantic classification -----------------------------------------
    entity: Mapped[FieldEntity] = mapped_column(
        enum_column(FieldEntity), nullable=False, default=FieldEntity.UNKNOWN
    )
    field_class: Mapped[FieldClass] = mapped_column(
        enum_column(FieldClass), nullable=False, default=FieldClass.UNKNOWN
    )
    category: Mapped[FieldCategory] = mapped_column(
        enum_column(FieldCategory), nullable=False, default=FieldCategory.UNKNOWN
    )
    sub_category: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    # --- typing and units -------------------------------------------------
    data_type: Mapped[CanonicalDataType] = mapped_column(
        enum_column(CanonicalDataType), nullable=False, default=CanonicalDataType.UNKNOWN
    )
    unit: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    nullable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    # --- validity ---------------------------------------------------------
    valid_min: Mapped[Decimal | None] = mapped_column(sa.Numeric(24, 6), nullable=True)
    valid_max: Mapped[Decimal | None] = mapped_column(sa.Numeric(24, 6), nullable=True)
    range_status: Mapped[RangeStatus] = mapped_column(
        enum_column(RangeStatus), nullable=False, default=RangeStatus.UNVERIFIED
    )

    # --- downstream intent (metadata only in Phase 1B) --------------------
    normalization_strategy: Mapped[NormalizationStrategy] = mapped_column(
        enum_column(NormalizationStrategy), nullable=False, default=NormalizationStrategy.UNKNOWN
    )
    storage_strategy: Mapped[StorageStrategy] = mapped_column(
        enum_column(StorageStrategy), nullable=False, default=StorageStrategy.UNKNOWN
    )
    aggregation_strategy: Mapped[AggregationStrategy] = mapped_column(
        enum_column(AggregationStrategy), nullable=False, default=AggregationStrategy.UNKNOWN
    )

    # --- future-ML metadata (no features are built) -----------------------
    ml_candidate: Mapped[MlCandidate] = mapped_column(
        enum_column(MlCandidate), nullable=False, default=MlCandidate.UNKNOWN
    )
    leakage_risk: Mapped[LeakageRisk] = mapped_column(
        enum_column(LeakageRisk), nullable=False, default=LeakageRisk.UNKNOWN
    )
    availability_semantics: Mapped[AvailabilitySemantics] = mapped_column(
        enum_column(AvailabilitySemantics), nullable=False, default=AvailabilitySemantics.UNKNOWN
    )

    # --- governance -------------------------------------------------------
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus), nullable=False, default=ReviewStatus.AUTO_CLASSIFIED
    )
    deprecated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # True when an explicit dictionary entry matched this source position;
    # False when the definition came only from the deterministic classifier.
    is_dictionary_mapped: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    dictionary_source: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    schema_version: Mapped[SchemaVersion] = relationship(back_populates="field_definitions")
    sentinel_values: Mapped[list[FieldSentinelValue]] = relationship(
        back_populates="field_definition", cascade="all, delete-orphan"
    )
    allowed_values: Mapped[list[FieldAllowedValue]] = relationship(
        back_populates="field_definition", cascade="all, delete-orphan"
    )
    prediction_domains: Mapped[list[FieldPredictionDomain]] = relationship(
        back_populates="field_definition", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "schema_version_id",
            "source_name",
            "source_occurrence",
            name="uq_field_definition_source_identity",
        ),
        sa.UniqueConstraint(
            "schema_version_id", "source_position", name="uq_field_definition_position"
        ),
        sa.UniqueConstraint(
            "schema_version_id", "canonical_name", name="uq_field_definition_canonical_name"
        ),
        sa.Index("ix_field_definition_entity", "entity"),
        sa.Index("ix_field_definition_category", "category"),
        sa.Index("ix_field_definition_field_class", "field_class"),
        sa.Index("ix_field_definition_review_status", "review_status"),
        sa.Index("ix_field_definition_storage_strategy", "storage_strategy"),
        sa.CheckConstraint("source_occurrence >= 1", name="source_occurrence_positive"),
        sa.CheckConstraint("source_position >= 0", name="source_position_non_negative"),
    )

    @property
    def position(self) -> int:
        """Phase 1A alias for :attr:`source_position`."""
        return self.source_position

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<FieldDefinition {self.canonical_name} "
            f"({self.source_name}#{self.source_occurrence}) {self.entity}/{self.field_class}>"
        )


class FieldSentinelValue(UUIDPrimaryKeyMixin, Base):
    """A field-specific value that encodes "no reading" rather than a measurement.

    Sentinel rules are deliberately per-field (section 13): ``-150`` on an SMR
    internal temperature is a dead sensor, but ``-150`` on a power setpoint may
    be perfectly valid.
    """

    __tablename__ = "field_sentinel_value"

    field_definition_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("field_definition.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    meaning: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    field_definition: Mapped[FieldDefinition] = relationship(back_populates="sentinel_values")

    __table_args__ = (
        sa.UniqueConstraint("field_definition_id", "value", name="uq_field_sentinel_value"),
    )


class FieldAllowedValue(UUIDPrimaryKeyMixin, Base):
    """Authoritative known values for a state-like field (section 16).

    Presence of rows here is what makes ``UNKNOWN_ENUM_VALUE`` meaningful; when
    no authoritative set exists the rule does not fire at all.
    """

    __tablename__ = "field_allowed_value"

    field_definition_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("field_definition.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(sa.String(256), nullable=False)
    meaning: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    field_definition: Mapped[FieldDefinition] = relationship(back_populates="allowed_values")

    __table_args__ = (
        sa.UniqueConstraint("field_definition_id", "value", name="uq_field_allowed_value"),
    )


class FieldPredictionDomain(UUIDPrimaryKeyMixin, Base):
    """Future prediction problems a field may inform.  Metadata only."""

    __tablename__ = "field_prediction_domain"

    field_definition_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("field_definition.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[PredictionDomain] = mapped_column(enum_column(PredictionDomain), nullable=False)

    field_definition: Mapped[FieldDefinition] = relationship(back_populates="prediction_domains")

    __table_args__ = (
        sa.UniqueConstraint("field_definition_id", "domain", name="uq_field_prediction_domain"),
    )
