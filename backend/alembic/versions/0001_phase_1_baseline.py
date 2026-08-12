"""Phase 1 baseline: ingestion, data dictionary and fleet coverage.

Delivered as a single baseline rather than one migration per phase, because
Phases 1A, 1B and 1C were implemented in one pass against an empty repository -
there was no previously deployed schema to evolve from. Later phases add
incremental revisions on top of this.

TimescaleDB is enabled only when the extension is actually available. No table
in this baseline is a hypertable: these are ingestion-control and metadata
tables whose access patterns are relational, not time-series. Timescale becomes
load-bearing when the Silver telemetry tables arrive in a later phase.

Revision ID: a265296ab819
Revises:
Create Date: 2026-08-11 22:08:36.432311
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a265296ab819"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_timescaledb_if_available() -> None:
    """Create the TimescaleDB extension when the server offers it.

    Guarded so the same migration runs on a plain PostgreSQL instance (and on
    SQLite in the hermetic test-suite) without failing.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    available = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).scalar()
    if available:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")


def upgrade() -> None:
    _enable_timescaledb_if_available()

    op.create_table('charger',
    sa.Column('charger_id', sa.String(length=128), nullable=False),
    sa.Column('ocpp_id', sa.String(length=128), nullable=True),
    sa.Column('site_code', sa.String(length=128), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('lifecycle_status', sa.Enum('COMMISSIONED', 'ACTIVE', 'TEMPORARILY_INACTIVE', 'DECOMMISSIONED', 'TEST', name='chargerlifecyclestatus', native_enum=False, length=48), nullable=False),
    sa.Column('telemetry_expected', sa.Boolean(), nullable=False),
    sa.Column('telemetry_start_date', sa.Date(), nullable=True),
    sa.Column('telemetry_end_date', sa.Date(), nullable=True),
    sa.Column('expected_sampling_interval_seconds', sa.Integer(), nullable=True),
    sa.Column('expected_connector_count', sa.Integer(), nullable=True),
    sa.Column('expected_smr_count', sa.Integer(), nullable=True),
    sa.Column('source_timezone', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charger')),
    sa.UniqueConstraint('charger_id', name='uq_charger_charger_id')
    )
    op.create_index('ix_charger_lifecycle_status', 'charger', ['lifecycle_status'], unique=False)
    op.create_index('ix_charger_ocpp_id', 'charger', ['ocpp_id'], unique=False)
    op.create_index('ix_charger_site_code', 'charger', ['site_code'], unique=False)
    op.create_table('ingestion_run',
    sa.Column('source_type', sa.Enum('FILESYSTEM', 'SFTP', 'S3', 'AZURE_BLOB', 'API', name='sourcetype', native_enum=False, length=48), nullable=False),
    sa.Column('trigger', sa.Enum('CLI', 'WORKER', 'API', 'TEST', name='ingestiontrigger', native_enum=False, length=48), nullable=False),
    sa.Column('status', sa.Enum('STARTED', 'DISCOVERING', 'PROCESSING', 'RECONCILING', 'COMPLETED', 'COMPLETED_WITH_WARNINGS', 'FAILED', name='ingestionrunstatus', native_enum=False, length=48), nullable=False),
    sa.Column('business_date', sa.Date(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('files_discovered', sa.Integer(), nullable=False),
    sa.Column('files_registered', sa.Integer(), nullable=False),
    sa.Column('files_ready', sa.Integer(), nullable=False),
    sa.Column('files_partial', sa.Integer(), nullable=False),
    sa.Column('files_duplicate', sa.Integer(), nullable=False),
    sa.Column('files_quarantined', sa.Integer(), nullable=False),
    sa.Column('files_failed', sa.Integer(), nullable=False),
    sa.Column('expected_charger_count', sa.Integer(), nullable=True),
    sa.Column('received_charger_count', sa.Integer(), nullable=True),
    sa.Column('missing_charger_count', sa.Integer(), nullable=True),
    sa.Column('late_charger_count', sa.Integer(), nullable=True),
    sa.Column('fleet_coverage_percentage', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingestion_run'))
    )
    op.create_index(op.f('ix_ingestion_run_business_date'), 'ingestion_run', ['business_date'], unique=False)
    op.create_index('ix_ingestion_run_started_at', 'ingestion_run', ['started_at'], unique=False)
    op.create_index('ix_ingestion_run_status', 'ingestion_run', ['status'], unique=False)
    op.create_table('schema_version',
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('header_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('field_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_header_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'DEPRECATED', name='schemaversionstatus', native_enum=False, length=48), nullable=False),
    sa.Column('coverage_status', sa.Enum('COMPLETE', 'INCOMPLETE', name='schemacoveragestatus', native_enum=False, length=48), nullable=False),
    sa.Column('mapped_field_count', sa.Integer(), nullable=False),
    sa.Column('unmapped_field_count', sa.Integer(), nullable=False),
    sa.Column('dictionary_revision', sa.String(length=64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_schema_version')),
    sa.UniqueConstraint('header_fingerprint', name='uq_schema_version_header_fingerprint'),
    sa.UniqueConstraint('version', name='uq_schema_version_version')
    )
    op.create_index('ix_schema_version_status', 'schema_version', ['status'], unique=False)
    op.create_table('field_definition',
    sa.Column('schema_version_id', sa.Uuid(), nullable=False),
    sa.Column('source_name', sa.String(length=512), nullable=False),
    sa.Column('source_occurrence', sa.Integer(), nullable=False),
    sa.Column('source_position', sa.Integer(), nullable=False),
    sa.Column('canonical_name', sa.String(length=256), nullable=False),
    sa.Column('display_name', sa.String(length=256), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('entity', sa.Enum('FILE', 'SITE', 'CHARGER', 'CONNECTOR', 'SMR', 'SESSION', 'ALARM', 'CONFIGURATION', 'UNKNOWN', name='fieldentity', native_enum=False, length=48), nullable=False),
    sa.Column('field_class', sa.Enum('IDENTIFIER', 'DIMENSION', 'CONFIGURATION', 'CONTINUOUS_TELEMETRY', 'DISCRETE_TELEMETRY', 'STATE', 'COUNTER', 'SESSION_ATTRIBUTE', 'ALARM_FLAG', 'FAULT_CODE', 'TIMESTAMP', 'DERIVED_SOURCE_VALUE', 'UNKNOWN', name='fieldclass', native_enum=False, length=48), nullable=False),
    sa.Column('category', sa.Enum('IDENTITY', 'ELECTRICAL_INPUT', 'ELECTRICAL_OUTPUT', 'THERMAL', 'POWER_MODULE', 'SMR', 'CONNECTOR', 'GUN', 'INSULATION', 'COMMUNICATION', 'OCPP', 'CCS', 'CCU', 'PLC', 'CAN', 'SESSION', 'STATE_MACHINE', 'CONTACTOR', 'COOLING', 'FAN', 'METER', 'BATTERY', 'COUNTER', 'FAULT', 'ALARM', 'FIRMWARE', 'HARDWARE', 'SYSTEM', 'UNKNOWN', name='fieldcategory', native_enum=False, length=48), nullable=False),
    sa.Column('sub_category', sa.String(length=64), nullable=True),
    sa.Column('data_type', sa.Enum('STRING', 'INTEGER', 'FLOAT', 'BOOLEAN', 'ENUM', 'DATETIME', 'DURATION', 'IDENTIFIER', 'UNKNOWN', name='canonicaldatatype', native_enum=False, length=48), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=True),
    sa.Column('nullable', sa.Boolean(), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('valid_min', sa.Numeric(precision=24, scale=6), nullable=True),
    sa.Column('valid_max', sa.Numeric(precision=24, scale=6), nullable=True),
    sa.Column('range_status', sa.Enum('VERIFIED', 'UNVERIFIED', 'NOT_APPLICABLE', name='rangestatus', native_enum=False, length=48), nullable=False),
    sa.Column('normalization_strategy', sa.Enum('PASSTHROUGH', 'CHARGER_SCALAR', 'PER_CONNECTOR', 'PER_SMR', 'PER_SESSION', 'ALARM_EDGE', 'COUNTER_SNAPSHOT', 'CONFIG_SNAPSHOT', 'RAW_RETAIN', 'UNKNOWN', name='normalizationstrategy', native_enum=False, length=48), nullable=False),
    sa.Column('storage_strategy', sa.Enum('MASTER_DATA', 'CONFIGURATION_SNAPSHOT', 'CHARGER_TELEMETRY', 'CONNECTOR_TELEMETRY', 'SMR_TELEMETRY', 'SESSION_OBSERVATION', 'ALARM_EVENT', 'COUNTER_TELEMETRY', 'RAW_ONLY', 'UNKNOWN', name='storagestrategy', native_enum=False, length=48), nullable=False),
    sa.Column('aggregation_strategy', sa.Enum('NONE', 'FIRST', 'LAST', 'MIN', 'MAX', 'MEAN', 'MEDIAN', 'SUM', 'MODE', 'ANY_TRUE', 'COUNT_DISTINCT', 'UNKNOWN', name='aggregationstrategy', native_enum=False, length=48), nullable=False),
    sa.Column('ml_candidate', sa.Enum('YES', 'NO', 'UNKNOWN', name='mlcandidate', native_enum=False, length=48), nullable=False),
    sa.Column('leakage_risk', sa.Enum('NONE', 'LOW', 'MEDIUM', 'HIGH', 'UNKNOWN', name='leakagerisk', native_enum=False, length=48), nullable=False),
    sa.Column('availability_semantics', sa.Enum('REAL_TIME', 'SESSION_START', 'SESSION_DURING', 'SESSION_END', 'POST_EVENT', 'STATIC', 'UNKNOWN', name='availabilitysemantics', native_enum=False, length=48), nullable=False),
    sa.Column('review_status', sa.Enum('AUTO_CLASSIFIED', 'ENGINEER_REVIEWED', 'DOMAIN_REVIEW_REQUIRED', 'VERIFIED', name='reviewstatus', native_enum=False, length=48), nullable=False),
    sa.Column('deprecated', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_dictionary_mapped', sa.Boolean(), nullable=False),
    sa.Column('dictionary_source', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('source_occurrence >= 1', name=op.f('ck_field_definition_source_occurrence_positive')),
    sa.CheckConstraint('source_position >= 0', name=op.f('ck_field_definition_source_position_non_negative')),
    sa.ForeignKeyConstraint(['schema_version_id'], ['schema_version.id'], name=op.f('fk_field_definition_schema_version_id_schema_version'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_definition')),
    sa.UniqueConstraint('schema_version_id', 'canonical_name', name='uq_field_definition_canonical_name'),
    sa.UniqueConstraint('schema_version_id', 'source_name', 'source_occurrence', name='uq_field_definition_source_identity'),
    sa.UniqueConstraint('schema_version_id', 'source_position', name='uq_field_definition_position')
    )
    op.create_index('ix_field_definition_category', 'field_definition', ['category'], unique=False)
    op.create_index('ix_field_definition_entity', 'field_definition', ['entity'], unique=False)
    op.create_index('ix_field_definition_field_class', 'field_definition', ['field_class'], unique=False)
    op.create_index('ix_field_definition_review_status', 'field_definition', ['review_status'], unique=False)
    op.create_index(op.f('ix_field_definition_schema_version_id'), 'field_definition', ['schema_version_id'], unique=False)
    op.create_index('ix_field_definition_storage_strategy', 'field_definition', ['storage_strategy'], unique=False)
    op.create_table('telemetry_file',
    sa.Column('ingestion_run_id', sa.Uuid(), nullable=True),
    sa.Column('source_type', sa.Enum('FILESYSTEM', 'SFTP', 'S3', 'AZURE_BLOB', 'API', name='sourcetype', native_enum=False, length=48), nullable=False),
    sa.Column('original_filename', sa.String(length=512), nullable=False),
    sa.Column('source_reference', sa.Text(), nullable=False),
    sa.Column('storage_reference', sa.Text(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Enum('DISCOVERED', 'REGISTERED', 'LANDING', 'PROFILING', 'SCHEMA_VALIDATION', 'QUALITY_VALIDATION', 'READY_FOR_NORMALIZATION', 'COMPLETED', 'PARTIAL', 'DUPLICATE', 'QUARANTINED', 'FAILED', name='filestatus', native_enum=False, length=48), nullable=False),
    sa.Column('duplicate_of_file_id', sa.Uuid(), nullable=True),
    sa.Column('row_count', sa.BigInteger(), nullable=True),
    sa.Column('column_count', sa.Integer(), nullable=True),
    sa.Column('connector_count_detected', sa.Integer(), nullable=True),
    sa.Column('smr_count_detected', sa.Integer(), nullable=True),
    sa.Column('session_id_count', sa.Integer(), nullable=True),
    sa.Column('event_time_min', sa.DateTime(timezone=True), nullable=True),
    sa.Column('event_time_max', sa.DateTime(timezone=True), nullable=True),
    sa.Column('event_time_format', sa.String(length=64), nullable=True),
    sa.Column('business_date', sa.Date(), nullable=True),
    sa.Column('distinct_business_date_count', sa.Integer(), nullable=True),
    sa.Column('file_date_span', sa.Enum('SINGLE_DAY', 'CROSS_MIDNIGHT', 'MULTI_DAY', 'UNKNOWN', name='filedatespan', native_enum=False, length=48), nullable=True),
    sa.Column('filename_date', sa.Date(), nullable=True),
    sa.Column('unique_event_timestamp_count', sa.Integer(), nullable=True),
    sa.Column('median_sampling_interval_seconds', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('invalid_timestamp_count', sa.BigInteger(), nullable=True),
    sa.Column('exact_duplicate_row_count', sa.BigInteger(), nullable=True),
    sa.Column('duplicate_participating_row_count', sa.BigInteger(), nullable=True),
    sa.Column('logical_key_collision_group_count', sa.BigInteger(), nullable=True),
    sa.Column('logical_key_conflicting_group_count', sa.BigInteger(), nullable=True),
    sa.Column('max_occurrences_per_logical_key', sa.Integer(), nullable=True),
    sa.Column('empty_field_count', sa.Integer(), nullable=True),
    sa.Column('constant_field_count', sa.Integer(), nullable=True),
    sa.Column('varying_field_count', sa.Integer(), nullable=True),
    sa.Column('duplicate_header_count', sa.Integer(), nullable=True),
    sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('profiling_duration_ms', sa.Integer(), nullable=True),
    sa.Column('schema_version_id', sa.Uuid(), nullable=True),
    sa.Column('header_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('schema_compatibility', sa.Enum('EXACT_MATCH', 'COMPATIBLE_ADDITION', 'COMPATIBLE_MISSING_OPTIONAL', 'INCOMPATIBLE_MISSING_REQUIRED', 'INCOMPATIBLE_TYPE_CHANGE', 'UNKNOWN_SCHEMA', name='schemacompatibility', native_enum=False, length=48), nullable=True),
    sa.Column('quality_score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('schema_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('completeness_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('validity_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('duplicate_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('timestamp_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('quarantine_reason', sa.Text(), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('profile_artifact_reference', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('file_size_bytes >= 0', name=op.f('ck_telemetry_file_file_size_non_negative')),
    sa.ForeignKeyConstraint(['duplicate_of_file_id'], ['telemetry_file.id'], name=op.f('fk_telemetry_file_duplicate_of_file_id_telemetry_file'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ingestion_run_id'], ['ingestion_run.id'], name=op.f('fk_telemetry_file_ingestion_run_id_ingestion_run'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['schema_version_id'], ['schema_version.id'], name=op.f('fk_telemetry_file_schema_version_id_schema_version'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telemetry_file')),
    sa.UniqueConstraint('sha256', 'original_filename', name='uq_telemetry_file_sha256_name')
    )
    op.create_index(op.f('ix_telemetry_file_business_date'), 'telemetry_file', ['business_date'], unique=False)
    op.create_index('ix_telemetry_file_event_time_min', 'telemetry_file', ['event_time_min'], unique=False)
    op.create_index(op.f('ix_telemetry_file_ingestion_run_id'), 'telemetry_file', ['ingestion_run_id'], unique=False)
    op.create_index('ix_telemetry_file_received_at', 'telemetry_file', ['received_at'], unique=False)
    op.create_index(op.f('ix_telemetry_file_schema_version_id'), 'telemetry_file', ['schema_version_id'], unique=False)
    op.create_index('ix_telemetry_file_sha256', 'telemetry_file', ['sha256'], unique=False)
    op.create_index('ix_telemetry_file_status', 'telemetry_file', ['status'], unique=False)
    op.create_table('charger_day_coverage',
    sa.Column('charger_pk', sa.Uuid(), nullable=True),
    sa.Column('charger_id', sa.String(length=128), nullable=False),
    sa.Column('business_date', sa.Date(), nullable=False),
    sa.Column('expected', sa.Boolean(), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('primary_telemetry_file_id', sa.Uuid(), nullable=True),
    sa.Column('first_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('unique_timestamp_count', sa.Integer(), nullable=False),
    sa.Column('expected_timestamp_count', sa.Integer(), nullable=True),
    sa.Column('expected_sampling_interval_seconds', sa.Integer(), nullable=True),
    sa.Column('observed_median_sampling_interval_seconds', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('observed_p95_sampling_interval_seconds', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('observed_min_sampling_interval_seconds', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('observed_max_sampling_interval_seconds', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('coverage_seconds', sa.Integer(), nullable=True),
    sa.Column('expected_coverage_seconds', sa.Integer(), nullable=True),
    sa.Column('span_coverage_percentage', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('sample_coverage_percentage', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('gap_adjusted_coverage_percentage', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('coverage_percentage', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('largest_gap_seconds', sa.Integer(), nullable=True),
    sa.Column('gap_count', sa.Integer(), nullable=False),
    sa.Column('total_gap_seconds', sa.Integer(), nullable=True),
    sa.Column('duplicate_timestamp_count', sa.Integer(), nullable=False),
    sa.Column('logical_collision_count', sa.Integer(), nullable=False),
    sa.Column('overlapping_timestamp_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_file_count', sa.Integer(), nullable=False),
    sa.Column('connector_count_detected', sa.Integer(), nullable=True),
    sa.Column('smr_count_detected', sa.Integer(), nullable=True),
    sa.Column('expected_connector_count', sa.Integer(), nullable=True),
    sa.Column('expected_smr_count', sa.Integer(), nullable=True),
    sa.Column('arrival_status', sa.Enum('EXPECTED', 'RECEIVED', 'LATE', 'MISSING', 'UNEXPECTED', name='arrivalstatus', native_enum=False, length=48), nullable=False),
    sa.Column('completeness_status', sa.Enum('COMPLETE', 'PARTIAL', 'SEVERELY_INCOMPLETE', 'NO_DATA', 'UNKNOWN', name='completenessstatus', native_enum=False, length=48), nullable=False),
    sa.Column('first_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('late_by_seconds', sa.BigInteger(), nullable=True),
    sa.Column('quality_score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('file_count >= 0', name=op.f('ck_charger_day_coverage_file_count_non_negative')),
    sa.ForeignKeyConstraint(['charger_pk'], ['charger.id'], name=op.f('fk_charger_day_coverage_charger_pk_charger'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['primary_telemetry_file_id'], ['telemetry_file.id'], name=op.f('fk_charger_day_coverage_primary_telemetry_file_id_telemetry_file'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charger_day_coverage')),
    sa.UniqueConstraint('charger_id', 'business_date', name='uq_charger_day_coverage_identity')
    )
    op.create_index('ix_charger_day_coverage_arrival', 'charger_day_coverage', ['business_date', 'arrival_status'], unique=False)
    op.create_index('ix_charger_day_coverage_business_date', 'charger_day_coverage', ['business_date'], unique=False)
    op.create_index(op.f('ix_charger_day_coverage_charger_pk'), 'charger_day_coverage', ['charger_pk'], unique=False)
    op.create_index('ix_charger_day_coverage_completeness', 'charger_day_coverage', ['business_date', 'completeness_status'], unique=False)
    op.create_table('data_quality_issue',
    sa.Column('telemetry_file_id', sa.Uuid(), nullable=False),
    sa.Column('ingestion_run_id', sa.Uuid(), nullable=True),
    sa.Column('field_definition_id', sa.Uuid(), nullable=True),
    sa.Column('rule_code', sa.Enum('MISSING_REQUIRED_FIELD', 'DUPLICATE_HEADER', 'INVALID_TIMESTAMP', 'EXACT_DUPLICATE', 'LOGICAL_KEY_COLLISION', 'UNKNOWN_FIELD', 'MISSING_FIELD', 'ALL_NULL_FIELD', 'SENTINEL_VALUE', 'OUT_OF_RANGE', 'UNEXPECTED_CONNECTOR_CARDINALITY', 'UNEXPECTED_SMR_CARDINALITY', 'TELEMETRY_GAP', 'SCHEMA_MISMATCH', 'INVALID_TYPE', 'UNKNOWN_ENUM_VALUE', 'MISSING_CHARGER_DATA', 'LATE_FILE', 'PARTIAL_DAY', 'SEVERELY_INCOMPLETE_DAY', 'ABNORMAL_SAMPLING_INTERVAL', 'MISSING_EXPECTED_CONNECTOR', 'MISSING_EXPECTED_SMR', 'MULTIPLE_FILES_SAME_CHARGER_DAY', 'OVERLAPPING_FILE_COVERAGE', 'EVENT_DATE_FILENAME_MISMATCH', name='qualityissuetype', native_enum=False, length=48), nullable=False),
    sa.Column('scope', sa.Enum('FILE', 'FIELD', 'ROW', 'CHARGER_DAY', 'TIMESTAMP', 'ENTITY', name='qualityrulescope', native_enum=False, length=48), nullable=False),
    sa.Column('severity', sa.Enum('INFO', 'WARNING', 'ERROR', 'CRITICAL', name='qualityseverity', native_enum=False, length=48), nullable=False),
    sa.Column('entity', sa.Enum('FILE', 'SITE', 'CHARGER', 'CONNECTOR', 'SMR', 'SESSION', 'ALARM', 'CONFIGURATION', 'UNKNOWN', name='fieldentity', native_enum=False, length=48), nullable=True),
    sa.Column('field_name', sa.String(length=512), nullable=True),
    sa.Column('field_occurrence', sa.Integer(), nullable=True),
    sa.Column('source_row_number', sa.BigInteger(), nullable=True),
    sa.Column('event_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('entity_reference', sa.String(length=128), nullable=True),
    sa.Column('raw_value', sa.String(length=128), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('occurrence_count', sa.BigInteger(), nullable=False),
    sa.Column('issue_hash', sa.String(length=64), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('occurrence_count >= 1', name=op.f('ck_data_quality_issue_occurrence_count_positive')),
    sa.ForeignKeyConstraint(['field_definition_id'], ['field_definition.id'], name=op.f('fk_data_quality_issue_field_definition_id_field_definition'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ingestion_run_id'], ['ingestion_run.id'], name=op.f('fk_data_quality_issue_ingestion_run_id_ingestion_run'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['telemetry_file_id'], ['telemetry_file.id'], name=op.f('fk_data_quality_issue_telemetry_file_id_telemetry_file'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_quality_issue')),
    sa.UniqueConstraint('telemetry_file_id', 'issue_hash', name='uq_data_quality_issue_hash')
    )
    op.create_index('ix_data_quality_issue_detected_at', 'data_quality_issue', ['detected_at'], unique=False)
    op.create_index(op.f('ix_data_quality_issue_field_definition_id'), 'data_quality_issue', ['field_definition_id'], unique=False)
    op.create_index('ix_data_quality_issue_file_severity', 'data_quality_issue', ['telemetry_file_id', 'severity'], unique=False)
    op.create_index(op.f('ix_data_quality_issue_ingestion_run_id'), 'data_quality_issue', ['ingestion_run_id'], unique=False)
    op.create_index('ix_data_quality_issue_rule_code', 'data_quality_issue', ['rule_code'], unique=False)
    op.create_index('ix_data_quality_issue_severity', 'data_quality_issue', ['severity'], unique=False)
    op.create_index(op.f('ix_data_quality_issue_telemetry_file_id'), 'data_quality_issue', ['telemetry_file_id'], unique=False)
    op.create_table('field_allowed_value',
    sa.Column('field_definition_id', sa.Uuid(), nullable=False),
    sa.Column('value', sa.String(length=256), nullable=False),
    sa.Column('meaning', sa.String(length=256), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['field_definition_id'], ['field_definition.id'], name=op.f('fk_field_allowed_value_field_definition_id_field_definition'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_allowed_value')),
    sa.UniqueConstraint('field_definition_id', 'value', name='uq_field_allowed_value')
    )
    op.create_index(op.f('ix_field_allowed_value_field_definition_id'), 'field_allowed_value', ['field_definition_id'], unique=False)
    op.create_table('field_prediction_domain',
    sa.Column('field_definition_id', sa.Uuid(), nullable=False),
    sa.Column('domain', sa.Enum('charger_health', 'smr_health', 'thermal_failure', 'contactor_failure', 'communication_failure', 'insulation_failure', 'connector_failure', 'session_failure', name='predictiondomain', native_enum=False, length=48), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['field_definition_id'], ['field_definition.id'], name=op.f('fk_field_prediction_domain_field_definition_id_field_definition'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_prediction_domain')),
    sa.UniqueConstraint('field_definition_id', 'domain', name='uq_field_prediction_domain')
    )
    op.create_index(op.f('ix_field_prediction_domain_field_definition_id'), 'field_prediction_domain', ['field_definition_id'], unique=False)
    op.create_table('field_profile',
    sa.Column('telemetry_file_id', sa.Uuid(), nullable=False),
    sa.Column('field_definition_id', sa.Uuid(), nullable=True),
    sa.Column('source_name', sa.String(length=512), nullable=False),
    sa.Column('source_occurrence', sa.Integer(), nullable=False),
    sa.Column('source_position', sa.Integer(), nullable=False),
    sa.Column('canonical_name', sa.String(length=256), nullable=True),
    sa.Column('null_count', sa.BigInteger(), nullable=False),
    sa.Column('null_percentage', sa.Numeric(precision=6, scale=3), nullable=False),
    sa.Column('unique_count', sa.BigInteger(), nullable=False),
    sa.Column('variability_class', sa.Enum('ALL_NULL_IN_SAMPLE', 'CONSTANT_IN_SAMPLE', 'VARIABLE_IN_SAMPLE', name='variabilityclass', native_enum=False, length=48), nullable=False),
    sa.Column('min_value', sa.String(length=256), nullable=True),
    sa.Column('max_value', sa.String(length=256), nullable=True),
    sa.Column('numeric_valid_count', sa.BigInteger(), nullable=True),
    sa.Column('mean_value', sa.Float(), nullable=True),
    sa.Column('median_value', sa.Float(), nullable=True),
    sa.Column('stddev_value', sa.Float(), nullable=True),
    sa.Column('sentinel_hit_count', sa.BigInteger(), nullable=False),
    sa.Column('example_values', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('observed_values', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('null_count >= 0', name=op.f('ck_field_profile_null_count_non_negative')),
    sa.ForeignKeyConstraint(['field_definition_id'], ['field_definition.id'], name=op.f('fk_field_profile_field_definition_id_field_definition'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['telemetry_file_id'], ['telemetry_file.id'], name=op.f('fk_field_profile_telemetry_file_id_telemetry_file'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_profile')),
    sa.UniqueConstraint('telemetry_file_id', 'source_position', name='uq_field_profile_file_position')
    )
    op.create_index(op.f('ix_field_profile_field_definition_id'), 'field_profile', ['field_definition_id'], unique=False)
    op.create_index(op.f('ix_field_profile_telemetry_file_id'), 'field_profile', ['telemetry_file_id'], unique=False)
    op.create_index('ix_field_profile_variability', 'field_profile', ['variability_class'], unique=False)
    op.create_table('field_sentinel_value',
    sa.Column('field_definition_id', sa.Uuid(), nullable=False),
    sa.Column('value', sa.String(length=128), nullable=False),
    sa.Column('meaning', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['field_definition_id'], ['field_definition.id'], name=op.f('fk_field_sentinel_value_field_definition_id_field_definition'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_sentinel_value')),
    sa.UniqueConstraint('field_definition_id', 'value', name='uq_field_sentinel_value')
    )
    op.create_index(op.f('ix_field_sentinel_value_field_definition_id'), 'field_sentinel_value', ['field_definition_id'], unique=False)
    op.create_table('telemetry_file_identifier',
    sa.Column('telemetry_file_id', sa.Uuid(), nullable=False),
    sa.Column('identifier_type', sa.String(length=32), nullable=False),
    sa.Column('value', sa.String(length=256), nullable=False),
    sa.Column('occurrence_count', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['telemetry_file_id'], ['telemetry_file.id'], name=op.f('fk_telemetry_file_identifier_telemetry_file_id_telemetry_file'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telemetry_file_identifier')),
    sa.UniqueConstraint('telemetry_file_id', 'identifier_type', 'value', name='uq_telemetry_file_identifier_value')
    )
    op.create_index('ix_telemetry_file_identifier_lookup', 'telemetry_file_identifier', ['identifier_type', 'value'], unique=False)
    op.create_index(op.f('ix_telemetry_file_identifier_telemetry_file_id'), 'telemetry_file_identifier', ['telemetry_file_id'], unique=False)
    op.create_table('telemetry_gap',
    sa.Column('coverage_id', sa.Uuid(), nullable=False),
    sa.Column('charger_pk', sa.Uuid(), nullable=True),
    sa.Column('charger_id', sa.String(length=128), nullable=False),
    sa.Column('business_date', sa.Date(), nullable=False),
    sa.Column('telemetry_file_id', sa.Uuid(), nullable=True),
    sa.Column('start_event_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_event_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_seconds', sa.Integer(), nullable=False),
    sa.Column('expected_interval_seconds', sa.Integer(), nullable=True),
    sa.Column('estimated_missing_samples', sa.Integer(), nullable=True),
    sa.Column('severity', sa.Enum('MINOR', 'MODERATE', 'MAJOR', 'CRITICAL', name='gapseverity', native_enum=False, length=48), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('duration_seconds > 0', name=op.f('ck_telemetry_gap_duration_positive')),
    sa.CheckConstraint('end_event_at > start_event_at', name=op.f('ck_telemetry_gap_gap_interval_ordered')),
    sa.ForeignKeyConstraint(['charger_pk'], ['charger.id'], name=op.f('fk_telemetry_gap_charger_pk_charger'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['coverage_id'], ['charger_day_coverage.id'], name=op.f('fk_telemetry_gap_coverage_id_charger_day_coverage'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['telemetry_file_id'], ['telemetry_file.id'], name=op.f('fk_telemetry_gap_telemetry_file_id_telemetry_file'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telemetry_gap')),
    sa.UniqueConstraint('coverage_id', 'start_event_at', 'end_event_at', name='uq_telemetry_gap_identity')
    )
    op.create_index('ix_telemetry_gap_charger_date', 'telemetry_gap', ['charger_id', 'business_date'], unique=False)
    op.create_index(op.f('ix_telemetry_gap_charger_pk'), 'telemetry_gap', ['charger_pk'], unique=False)
    op.create_index(op.f('ix_telemetry_gap_coverage_id'), 'telemetry_gap', ['coverage_id'], unique=False)
    op.create_index('ix_telemetry_gap_severity', 'telemetry_gap', ['severity'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_telemetry_gap_severity', table_name='telemetry_gap')
    op.drop_index(op.f('ix_telemetry_gap_coverage_id'), table_name='telemetry_gap')
    op.drop_index(op.f('ix_telemetry_gap_charger_pk'), table_name='telemetry_gap')
    op.drop_index('ix_telemetry_gap_charger_date', table_name='telemetry_gap')
    op.drop_table('telemetry_gap')
    op.drop_index(op.f('ix_telemetry_file_identifier_telemetry_file_id'), table_name='telemetry_file_identifier')
    op.drop_index('ix_telemetry_file_identifier_lookup', table_name='telemetry_file_identifier')
    op.drop_table('telemetry_file_identifier')
    op.drop_index(op.f('ix_field_sentinel_value_field_definition_id'), table_name='field_sentinel_value')
    op.drop_table('field_sentinel_value')
    op.drop_index('ix_field_profile_variability', table_name='field_profile')
    op.drop_index(op.f('ix_field_profile_telemetry_file_id'), table_name='field_profile')
    op.drop_index(op.f('ix_field_profile_field_definition_id'), table_name='field_profile')
    op.drop_table('field_profile')
    op.drop_index(op.f('ix_field_prediction_domain_field_definition_id'), table_name='field_prediction_domain')
    op.drop_table('field_prediction_domain')
    op.drop_index(op.f('ix_field_allowed_value_field_definition_id'), table_name='field_allowed_value')
    op.drop_table('field_allowed_value')
    op.drop_index(op.f('ix_data_quality_issue_telemetry_file_id'), table_name='data_quality_issue')
    op.drop_index('ix_data_quality_issue_severity', table_name='data_quality_issue')
    op.drop_index('ix_data_quality_issue_rule_code', table_name='data_quality_issue')
    op.drop_index(op.f('ix_data_quality_issue_ingestion_run_id'), table_name='data_quality_issue')
    op.drop_index('ix_data_quality_issue_file_severity', table_name='data_quality_issue')
    op.drop_index(op.f('ix_data_quality_issue_field_definition_id'), table_name='data_quality_issue')
    op.drop_index('ix_data_quality_issue_detected_at', table_name='data_quality_issue')
    op.drop_table('data_quality_issue')
    op.drop_index('ix_charger_day_coverage_completeness', table_name='charger_day_coverage')
    op.drop_index(op.f('ix_charger_day_coverage_charger_pk'), table_name='charger_day_coverage')
    op.drop_index('ix_charger_day_coverage_business_date', table_name='charger_day_coverage')
    op.drop_index('ix_charger_day_coverage_arrival', table_name='charger_day_coverage')
    op.drop_table('charger_day_coverage')
    op.drop_index('ix_telemetry_file_status', table_name='telemetry_file')
    op.drop_index('ix_telemetry_file_sha256', table_name='telemetry_file')
    op.drop_index(op.f('ix_telemetry_file_schema_version_id'), table_name='telemetry_file')
    op.drop_index('ix_telemetry_file_received_at', table_name='telemetry_file')
    op.drop_index(op.f('ix_telemetry_file_ingestion_run_id'), table_name='telemetry_file')
    op.drop_index('ix_telemetry_file_event_time_min', table_name='telemetry_file')
    op.drop_index(op.f('ix_telemetry_file_business_date'), table_name='telemetry_file')
    op.drop_table('telemetry_file')
    op.drop_index('ix_field_definition_storage_strategy', table_name='field_definition')
    op.drop_index(op.f('ix_field_definition_schema_version_id'), table_name='field_definition')
    op.drop_index('ix_field_definition_review_status', table_name='field_definition')
    op.drop_index('ix_field_definition_field_class', table_name='field_definition')
    op.drop_index('ix_field_definition_entity', table_name='field_definition')
    op.drop_index('ix_field_definition_category', table_name='field_definition')
    op.drop_table('field_definition')
    op.drop_index('ix_schema_version_status', table_name='schema_version')
    op.drop_table('schema_version')
    op.drop_index('ix_ingestion_run_status', table_name='ingestion_run')
    op.drop_index('ix_ingestion_run_started_at', table_name='ingestion_run')
    op.drop_index(op.f('ix_ingestion_run_business_date'), table_name='ingestion_run')
    op.drop_table('ingestion_run')
    op.drop_index('ix_charger_site_code', table_name='charger')
    op.drop_index('ix_charger_ocpp_id', table_name='charger')
    op.drop_index('ix_charger_lifecycle_status', table_name='charger')
    op.drop_table('charger')
    # ### end Alembic commands ###
