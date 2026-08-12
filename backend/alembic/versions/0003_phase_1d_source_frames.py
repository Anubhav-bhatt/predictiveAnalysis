"""Phase 1D: reconstructed source frames and their provenance.

Three new tables plus two new ingestion lifecycle states.

Frame identity is ``(charger_id, event_time, frame_sequence,
reconstruction_version)``. The sequence column is what makes genuinely distinct
same-second frames storable; a ``(charger_id, event_time)`` key would collide on
exactly the data this phase exists to preserve.

``reconstruction_version`` is part of the identity so re-running a newer algorithm
is additive rather than destructive, and historical output stays attributable to
the code that produced it.

The two new ingestion lifecycle states need **no DDL**. ``enum_column`` builds
``sa.Enum(..., native_enum=False)`` and SQLAlchemy 2.0 defaults
``create_constraint=False``, so the status columns are plain VARCHARs with the
permitted values enforced in Python. Verified against the live schema: the only
CHECK on ``telemetry_file`` is ``file_size_non_negative``. Adding a state is
therefore a code change, not a migration - which is exactly the property the
string-backed-enum decision in ``db/base`` was made to buy.

Revision ID: c7a4e2b91d38
Revises: b3f1c07d5a24
Create Date: 2026-08-12 17:02:44.913204
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a4e2b91d38"
down_revision: str | None = "b3f1c07d5a24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FRAME_STATUSES = ("COMPLETE", "PARTIAL", "SEVERELY_INCOMPLETE", "MALFORMED", "AMBIGUOUS")
_DUPLICATE_CLASSIFICATIONS = (
    "UNIQUE",
    "EXACT_ROW_DUPLICATE",
    "FULL_FRAME_REPLAY",
    "PARTIAL_FRAME_REPLAY",
    "SAME_TIMESTAMP_DISTINCT_FRAME",
    "AMBIGUOUS",
)


def _enum(values: Sequence[str], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=48)



def upgrade() -> None:
    op.create_table(
        "telemetry_source_frame",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("charger_pk", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("charger_id", sa.String(length=128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("frame_sequence", sa.Integer(), nullable=False),
        sa.Column("frame_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frame_status", _enum(_FRAME_STATUSES, "framestatus"), nullable=False),
        sa.Column(
            "duplicate_classification",
            _enum(_DUPLICATE_CLASSIFICATIONS, "duplicateclassification"),
            nullable=False,
        ),
        sa.Column("replay_of_frame_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("expected_position_count", sa.Integer(), nullable=False),
        sa.Column("observed_position_count", sa.Integer(), nullable=False),
        sa.Column("missing_position_count", sa.Integer(), nullable=False),
        sa.Column("unexpected_position_count", sa.Integer(), nullable=False),
        sa.Column("completeness_percentage", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("source_order_min", sa.Integer(), nullable=True),
        sa.Column("source_order_max", sa.Integer(), nullable=True),
        sa.Column("reconstruction_version", sa.String(length=64), nullable=False),
        sa.Column(
            "detail",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "frame_sequence >= 0",
            name=op.f("ck_telemetry_source_frame_frame_sequence_non_negative"),
        ),
        sa.CheckConstraint(
            "observed_position_count >= 0",
            name=op.f("ck_telemetry_source_frame_observed_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["charger_pk"],
            ["charger.id"],
            name=op.f("fk_telemetry_source_frame_charger_pk_charger"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replay_of_frame_id"],
            ["telemetry_source_frame.id"],
            name=op.f(
                "fk_telemetry_source_frame_replay_of_frame_id_telemetry_source_frame"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_source_frame")),
        sa.UniqueConstraint(
            "charger_id",
            "event_time",
            "frame_sequence",
            "reconstruction_version",
            name="uq_telemetry_source_frame_identity",
        ),
    )
    op.create_index(
        "ix_telemetry_source_frame_charger_time",
        "telemetry_source_frame",
        ["charger_id", "event_time"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_source_frame_charger_date",
        "telemetry_source_frame",
        ["charger_id", "business_date"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_source_frame_business_date",
        "telemetry_source_frame",
        ["business_date"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_source_frame_fingerprint",
        "telemetry_source_frame",
        ["charger_id", "frame_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_source_frame_status",
        "telemetry_source_frame",
        ["frame_status"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_source_frame_classification",
        "telemetry_source_frame",
        ["duplicate_classification"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telemetry_source_frame_charger_pk"),
        "telemetry_source_frame",
        ["charger_pk"],
        unique=False,
    )

    op.create_table(
        "telemetry_frame_source",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("frame_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telemetry_file_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("first_source_row", sa.Integer(), nullable=False),
        sa.Column("last_source_row", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("source_occurrence", sa.Integer(), nullable=False),
        sa.Column("is_primary_source", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["frame_id"],
            ["telemetry_source_frame.id"],
            name=op.f("fk_telemetry_frame_source_frame_id_telemetry_source_frame"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["telemetry_file_id"],
            ["telemetry_file.id"],
            name=op.f("fk_telemetry_frame_source_telemetry_file_id_telemetry_file"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_frame_source")),
        sa.UniqueConstraint(
            "frame_id", "telemetry_file_id", name="uq_telemetry_frame_source_identity"
        ),
    )
    op.create_index(
        op.f("ix_telemetry_frame_source_frame_id"),
        "telemetry_frame_source",
        ["frame_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telemetry_frame_source_telemetry_file_id"),
        "telemetry_frame_source",
        ["telemetry_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_frame_source_file",
        "telemetry_frame_source",
        ["telemetry_file_id"],
        unique=False,
    )

    op.create_table(
        "telemetry_frame_row",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("frame_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telemetry_file_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.String(length=64), nullable=True),
        sa.Column("smr_id", sa.String(length=64), nullable=True),
        sa.Column("logical_position", sa.String(length=128), nullable=True),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("row_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("unassigned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_row_number >= 0",
            name=op.f("ck_telemetry_frame_row_source_row_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["frame_id"],
            ["telemetry_source_frame.id"],
            name=op.f("fk_telemetry_frame_row_frame_id_telemetry_source_frame"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["telemetry_file_id"],
            ["telemetry_file.id"],
            name=op.f("fk_telemetry_frame_row_telemetry_file_id_telemetry_file"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_frame_row")),
        sa.UniqueConstraint(
            "frame_id",
            "telemetry_file_id",
            "source_row_number",
            name="uq_telemetry_frame_row_identity",
        ),
    )
    op.create_index(
        op.f("ix_telemetry_frame_row_frame_id"),
        "telemetry_frame_row",
        ["frame_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telemetry_frame_row_telemetry_file_id"),
        "telemetry_frame_row",
        ["telemetry_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_frame_row_file_row",
        "telemetry_frame_row",
        ["telemetry_file_id", "source_row_number"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_frame_row_position",
        "telemetry_frame_row",
        ["logical_position"],
        unique=False,
    )


def downgrade() -> None:
    # Files parked in a Phase 1D state are moved back to a state the Phase 1C
    # code understands. Not required by any constraint - the status column is a
    # plain VARCHAR - but leaving unknown values behind would make the older code
    # raise on read, so the downgrade is made genuinely reversible.
    op.execute(
        sa.text(
            "UPDATE telemetry_file SET status = 'READY_FOR_NORMALIZATION' "
            "WHERE status IN ('FRAME_RECONSTRUCTION', 'FRAMES_RECONSTRUCTED')"
        )
    )

    op.drop_index("ix_telemetry_frame_row_position", table_name="telemetry_frame_row")
    op.drop_index("ix_telemetry_frame_row_file_row", table_name="telemetry_frame_row")
    op.drop_index(
        op.f("ix_telemetry_frame_row_telemetry_file_id"), table_name="telemetry_frame_row"
    )
    op.drop_index(op.f("ix_telemetry_frame_row_frame_id"), table_name="telemetry_frame_row")
    op.drop_table("telemetry_frame_row")

    op.drop_index("ix_telemetry_frame_source_file", table_name="telemetry_frame_source")
    op.drop_index(
        op.f("ix_telemetry_frame_source_telemetry_file_id"),
        table_name="telemetry_frame_source",
    )
    op.drop_index(
        op.f("ix_telemetry_frame_source_frame_id"), table_name="telemetry_frame_source"
    )
    op.drop_table("telemetry_frame_source")

    op.drop_index(
        op.f("ix_telemetry_source_frame_charger_pk"), table_name="telemetry_source_frame"
    )
    op.drop_index(
        "ix_telemetry_source_frame_classification", table_name="telemetry_source_frame"
    )
    op.drop_index("ix_telemetry_source_frame_status", table_name="telemetry_source_frame")
    op.drop_index(
        "ix_telemetry_source_frame_fingerprint", table_name="telemetry_source_frame"
    )
    op.drop_index(
        "ix_telemetry_source_frame_business_date", table_name="telemetry_source_frame"
    )
    op.drop_index(
        "ix_telemetry_source_frame_charger_date", table_name="telemetry_source_frame"
    )
    op.drop_index(
        "ix_telemetry_source_frame_charger_time", table_name="telemetry_source_frame"
    )
    op.drop_table("telemetry_source_frame")
