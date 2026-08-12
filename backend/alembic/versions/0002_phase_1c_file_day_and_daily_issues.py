"""Phase 1C: per-date file contributions and charger-day quality findings.

Two changes, both required by Phase 1C behaviour that the baseline could not
express:

``telemetry_file_day``
    One row per (file, business date). A file may span dates (section 8) and
    several files may combine into one charger-day (section 19), so the per-date
    unique-timestamp set has to be first-class. Storing it is what lets
    reconciliation rebuild a charger-day after a late file without re-reading the
    raw CSV (section 24).

``data_quality_issue`` becomes anchorable to a charger-day
    ``telemetry_file_id`` had to become nullable: the most important daily
    finding, ``MISSING_CHARGER_DATA``, has no originating file at all - nothing
    arrived. Those rows anchor to ``charger_day_coverage`` instead.

Batch operations are used throughout so the migration applies on SQLite as well
as PostgreSQL; SQLite cannot ALTER a column's nullability in place.

Revision ID: b3f1c07d5a24
Revises: a265296ab819
Create Date: 2026-08-12 09:14:02.118447
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1c07d5a24"
down_revision: str | None = "a265296ab819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_file_day",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("telemetry_file_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("charger_id", sa.String(length=128), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unique_timestamp_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        # Seconds from local midnight per unique event timestamp. JSONB on
        # PostgreSQL, JSON on SQLite - the same variant the models declare.
        sa.Column(
            "event_second_offsets",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "connectors_seen",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "smrs_seen",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("duplicate_timestamp_count", sa.Integer(), nullable=False),
        sa.Column("logical_collision_count", sa.Integer(), nullable=False),
        sa.Column("exact_duplicate_row_count", sa.Integer(), nullable=False),
        sa.Column("source_timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "row_count >= 0", name=op.f("ck_telemetry_file_day_row_count_non_negative")
        ),
        sa.CheckConstraint(
            "unique_timestamp_count >= 0",
            name=op.f("ck_telemetry_file_day_unique_timestamp_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["telemetry_file_id"],
            ["telemetry_file.id"],
            name=op.f("fk_telemetry_file_day_telemetry_file_id_telemetry_file"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_file_day")),
        sa.UniqueConstraint(
            "telemetry_file_id", "business_date", name="uq_telemetry_file_day_identity"
        ),
    )
    op.create_index(
        "ix_telemetry_file_day_business_date",
        "telemetry_file_day",
        ["business_date"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_file_day_charger_date",
        "telemetry_file_day",
        ["charger_id", "business_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telemetry_file_day_telemetry_file_id"),
        "telemetry_file_day",
        ["telemetry_file_id"],
        unique=False,
    )

    with op.batch_alter_table("data_quality_issue") as batch:
        # Charger-day findings have no file; see the module docstring.
        batch.alter_column(
            "telemetry_file_id", existing_type=sa.Uuid(as_uuid=True), nullable=True
        )
        batch.add_column(sa.Column("charger_day_coverage_id", sa.Uuid(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("charger_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("business_date", sa.Date(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_data_quality_issue_charger_day_coverage_id_charger_day_coverage"),
            "charger_day_coverage",
            ["charger_day_coverage_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_data_quality_issue_coverage_hash",
            ["charger_day_coverage_id", "issue_hash"],
        )
        batch.create_check_constraint(
            "issue_has_an_anchor",
            "telemetry_file_id IS NOT NULL OR charger_day_coverage_id IS NOT NULL",
        )

    op.create_index(
        op.f("ix_data_quality_issue_charger_day_coverage_id"),
        "data_quality_issue",
        ["charger_day_coverage_id"],
        unique=False,
    )
    op.create_index(
        "ix_data_quality_issue_charger_date",
        "data_quality_issue",
        ["charger_id", "business_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_data_quality_issue_charger_date", table_name="data_quality_issue")
    op.drop_index(
        op.f("ix_data_quality_issue_charger_day_coverage_id"), table_name="data_quality_issue"
    )

    with op.batch_alter_table("data_quality_issue") as batch:
        # Bare names here: the metadata naming convention expands them, exactly
        # as it did on the way up. Passing the expanded name double-prefixes it.
        batch.drop_constraint("issue_has_an_anchor", type_="check")
        batch.drop_constraint("uq_data_quality_issue_coverage_hash", type_="unique")
        batch.drop_constraint(
            op.f("fk_data_quality_issue_charger_day_coverage_id_charger_day_coverage"),
            type_="foreignkey",
        )
        batch.drop_column("business_date")
        batch.drop_column("charger_id")
        batch.drop_column("charger_day_coverage_id")
        batch.alter_column(
            "telemetry_file_id", existing_type=sa.Uuid(as_uuid=True), nullable=False
        )

    op.drop_index(
        op.f("ix_telemetry_file_day_telemetry_file_id"), table_name="telemetry_file_day"
    )
    op.drop_index("ix_telemetry_file_day_charger_date", table_name="telemetry_file_day")
    op.drop_index("ix_telemetry_file_day_business_date", table_name="telemetry_file_day")
    op.drop_table("telemetry_file_day")
