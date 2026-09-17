"""add_research_tables

Revision ID: f60ecb16d021
Revises: 56379df29815
Create Date: 2026-09-17 14:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import backend.app.db.base

revision: str = "f60ecb16d021"
down_revision: str | None = "56379df29815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pattern_candidate",
        sa.Column(
            "charger_id", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "pattern_category",
            sa.Enum(
                "THERMAL_DRIFT",
                "VOLTAGE_ANOMALY",
                "CURRENT_IMBALANCE",
                "SESSION_DEGRADATION",
                "ALARM_CLUSTERING",
                "FAULT_RECURRENCE",
                "EFFICIENCY_DECLINE",
                "COMPONENT_DIVERGENCE",
                "OPERATIONAL_PATTERN",
                name="patterncategory",
                native_enum=False,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column(
            "evidence_level",
            sa.Enum(
                "OBSERVATION",
                "WEAK_CANDIDATE",
                "MODERATE_CANDIDATE",
                "STRONG_CANDIDATE",
                "CONFIRMED_PRECURSOR",
                name="patternevidencelevel",
                native_enum=False,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column(
            "affected_signals",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "affected_components",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "observation_window_start",
            backend.app.db.base.UtcDateTime(),
            nullable=True,
        ),
        sa.Column(
            "observation_window_end",
            backend.app.db.base.UtcDateTime(),
            nullable=True,
        ),
        sa.Column(
            "supporting_evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "analytical_grain",
            sa.Enum(
                "CHARGER_TIME",
                "CONNECTOR_TIME",
                "SMR_TIME",
                "RECTIFIER_TIME",
                "SESSION_LEVEL",
                "EVENT_CENTERED",
                name="analyticalgrain",
                native_enum=False,
                length=48,
            ),
            nullable=True,
        ),
        sa.Column(
            "dataset_version", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "scan_version", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            backend.app.db.base.UtcDateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            backend.app.db.base.UtcDateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pattern_candidate_lookup",
        "pattern_candidate",
        ["charger_id", "pattern_category", "evidence_level"],
    )
    op.create_index(
        op.f("ix_pattern_candidate_charger_id"),
        "pattern_candidate",
        ["charger_id"],
    )
    op.create_index(
        op.f("ix_pattern_candidate_pattern_category"),
        "pattern_candidate",
        ["pattern_category"],
    )
    op.create_index(
        op.f("ix_pattern_candidate_evidence_level"),
        "pattern_candidate",
        ["evidence_level"],
    )

    op.create_table(
        "analytical_dataset_run",
        sa.Column(
            "grain",
            sa.Enum(
                "CHARGER_TIME",
                "CONNECTOR_TIME",
                "SMR_TIME",
                "RECTIFIER_TIME",
                "SESSION_LEVEL",
                "EVENT_CENTERED",
                name="analyticalgrain",
                native_enum=False,
                length=48,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "charger_id", sa.String(length=128), nullable=True
        ),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column(
            "observation_window_start",
            backend.app.db.base.UtcDateTime(),
            nullable=True,
        ),
        sa.Column(
            "observation_window_end",
            backend.app.db.base.UtcDateTime(),
            nullable=True,
        ),
        sa.Column("gap_count", sa.Integer(), nullable=False),
        sa.Column("missing_rate", sa.Float(), nullable=False),
        sa.Column(
            "dataset_version", sa.String(length=32), nullable=False
        ),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            backend.app.db.base.UtcDateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            backend.app.db.base.UtcDateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analytical_dataset_run_grain"),
        "analytical_dataset_run",
        ["grain"],
    )
    op.create_index(
        op.f("ix_analytical_dataset_run_charger_id"),
        "analytical_dataset_run",
        ["charger_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_analytical_dataset_run_charger_id"),
        table_name="analytical_dataset_run",
    )
    op.drop_index(
        op.f("ix_analytical_dataset_run_grain"),
        table_name="analytical_dataset_run",
    )
    op.drop_table("analytical_dataset_run")

    op.drop_index(
        op.f("ix_pattern_candidate_evidence_level"),
        table_name="pattern_candidate",
    )
    op.drop_index(
        op.f("ix_pattern_candidate_pattern_category"),
        table_name="pattern_candidate",
    )
    op.drop_index(
        op.f("ix_pattern_candidate_charger_id"),
        table_name="pattern_candidate",
    )
    op.drop_index(
        "ix_pattern_candidate_lookup",
        table_name="pattern_candidate",
    )
    op.drop_table("pattern_candidate")
