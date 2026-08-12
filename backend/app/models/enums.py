"""Canonical domain vocabulary.

Every classification in the platform is an enum defined here - never an ad-hoc
string scattered through the code (section 8 of the Phase 1B contract).  Both
the FastAPI runtime and the ingestion worker import from this single module.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Phase 1A - ingestion lifecycle
# ---------------------------------------------------------------------------


class SourceType(StrEnum):
    """Where a telemetry file came from.

    Only FILESYSTEM is implemented in Phase 1A; the rest exist so that adding an
    adapter does not require touching profiling, quality or persistence code.
    """

    FILESYSTEM = "FILESYSTEM"
    SFTP = "SFTP"
    S3 = "S3"
    AZURE_BLOB = "AZURE_BLOB"
    API = "API"


class FileStatus(StrEnum):
    """Ingestion state machine states (section 6).

    Phase 1A drives the happy path as far as READY_FOR_NORMALIZATION.  COMPLETED
    is reachable only once a later phase performs normalization.
    """

    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    LANDING = "LANDING"
    PROFILING = "PROFILING"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    QUALITY_VALIDATION = "QUALITY_VALIDATION"
    READY_FOR_NORMALIZATION = "READY_FOR_NORMALIZATION"
    # Phase 1D. READY_FOR_NORMALIZATION no longer implies the raw rows are
    # directly consumable: Phase 1E consumes reconstructed frames, so a file must
    # pass through reconstruction first.
    FRAME_RECONSTRUCTION = "FRAME_RECONSTRUCTION"
    FRAMES_RECONSTRUCTED = "FRAMES_RECONSTRUCTED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    DUPLICATE = "DUPLICATE"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


class IngestionRunStatus(StrEnum):
    """Fleet collection-cycle status.

    RECONCILING is the stage where the expected fleet is compared against what
    actually arrived; it is the step that produces MISSING charger-days.
    """

    STARTED = "STARTED"
    DISCOVERING = "DISCOVERING"
    PROCESSING = "PROCESSING"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            IngestionRunStatus.COMPLETED,
            IngestionRunStatus.COMPLETED_WITH_WARNINGS,
            IngestionRunStatus.FAILED,
        }


class IngestionTrigger(StrEnum):
    CLI = "CLI"
    WORKER = "WORKER"
    API = "API"
    TEST = "TEST"


class SchemaVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class SchemaCoverageStatus(StrEnum):
    """Whether every source position has dictionary coverage (section 21)."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class SchemaCompatibility(StrEnum):
    """Result of comparing an incoming header against a registered schema."""

    EXACT_MATCH = "EXACT_MATCH"
    COMPATIBLE_ADDITION = "COMPATIBLE_ADDITION"
    COMPATIBLE_MISSING_OPTIONAL = "COMPATIBLE_MISSING_OPTIONAL"
    INCOMPATIBLE_MISSING_REQUIRED = "INCOMPATIBLE_MISSING_REQUIRED"
    INCOMPATIBLE_TYPE_CHANGE = "INCOMPATIBLE_TYPE_CHANGE"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"

    @property
    def is_compatible(self) -> bool:
        return self in {
            SchemaCompatibility.EXACT_MATCH,
            SchemaCompatibility.COMPATIBLE_ADDITION,
            SchemaCompatibility.COMPATIBLE_MISSING_OPTIONAL,
        }


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class QualityIssueType(StrEnum):
    """Rule codes.  Phase 1A defines the vocabulary; 1B implements the engine."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    DUPLICATE_HEADER = "DUPLICATE_HEADER"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    LOGICAL_KEY_COLLISION = "LOGICAL_KEY_COLLISION"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    MISSING_FIELD = "MISSING_FIELD"
    ALL_NULL_FIELD = "ALL_NULL_FIELD"
    SENTINEL_VALUE = "SENTINEL_VALUE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    UNEXPECTED_CONNECTOR_CARDINALITY = "UNEXPECTED_CONNECTOR_CARDINALITY"
    UNEXPECTED_SMR_CARDINALITY = "UNEXPECTED_SMR_CARDINALITY"
    TELEMETRY_GAP = "TELEMETRY_GAP"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    # Phase 1B additions
    INVALID_TYPE = "INVALID_TYPE"
    UNKNOWN_ENUM_VALUE = "UNKNOWN_ENUM_VALUE"
    # Phase 1C additions - fleet/day scope rather than file scope
    MISSING_CHARGER_DATA = "MISSING_CHARGER_DATA"
    LATE_FILE = "LATE_FILE"
    PARTIAL_DAY = "PARTIAL_DAY"
    SEVERELY_INCOMPLETE_DAY = "SEVERELY_INCOMPLETE_DAY"
    ABNORMAL_SAMPLING_INTERVAL = "ABNORMAL_SAMPLING_INTERVAL"
    MISSING_EXPECTED_CONNECTOR = "MISSING_EXPECTED_CONNECTOR"
    MISSING_EXPECTED_SMR = "MISSING_EXPECTED_SMR"
    MULTIPLE_FILES_SAME_CHARGER_DAY = "MULTIPLE_FILES_SAME_CHARGER_DAY"
    OVERLAPPING_FILE_COVERAGE = "OVERLAPPING_FILE_COVERAGE"
    EVENT_DATE_FILENAME_MISMATCH = "EVENT_DATE_FILENAME_MISMATCH"
    # Phase 1D additions - frame scope rather than file or charger-day scope
    FRAME_INCOMPLETE = "FRAME_INCOMPLETE"
    FRAME_OVERCOMPLETE = "FRAME_OVERCOMPLETE"
    FRAME_MISSING_POSITION = "FRAME_MISSING_POSITION"
    FRAME_UNEXPECTED_POSITION = "FRAME_UNEXPECTED_POSITION"
    AMBIGUOUS_FRAME_BOUNDARY = "AMBIGUOUS_FRAME_BOUNDARY"
    FULL_FRAME_REPLAY = "FULL_FRAME_REPLAY"
    PARTIAL_FRAME_REPLAY = "PARTIAL_FRAME_REPLAY"
    SAME_TIMESTAMP_DISTINCT_FRAME = "SAME_TIMESTAMP_DISTINCT_FRAME"
    INCONSISTENT_TOPOLOGY = "INCONSISTENT_TOPOLOGY"
    ENTITY_ID_MISSING = "ENTITY_ID_MISSING"
    UNASSIGNED_RAW_ROW = "UNASSIGNED_RAW_ROW"


class QualityRuleScope(StrEnum):
    """What a rule reasons about (section 25)."""

    FILE = "FILE"
    FIELD = "FIELD"
    ROW = "ROW"
    CHARGER_DAY = "CHARGER_DAY"
    TIMESTAMP = "TIMESTAMP"
    FRAME = "FRAME"
    ENTITY = "ENTITY"


class QualityDimension(StrEnum):
    """Independently computed score dimensions (section 28)."""

    SCHEMA = "schema_quality"
    COMPLETENESS = "completeness_quality"
    VALIDITY = "validity_quality"
    DUPLICATES = "duplicate_quality"
    TIMESTAMP = "timestamp_quality"


# ---------------------------------------------------------------------------
# Phase 1B - semantic classification
# ---------------------------------------------------------------------------


class FieldEntity(StrEnum):
    """The primary thing a field describes (section 6)."""

    FILE = "FILE"
    SITE = "SITE"
    CHARGER = "CHARGER"
    CONNECTOR = "CONNECTOR"
    SMR = "SMR"
    SESSION = "SESSION"
    ALARM = "ALARM"
    CONFIGURATION = "CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class FieldClass(StrEnum):
    """The semantic role of a field (section 7)."""

    IDENTIFIER = "IDENTIFIER"
    DIMENSION = "DIMENSION"
    CONFIGURATION = "CONFIGURATION"
    CONTINUOUS_TELEMETRY = "CONTINUOUS_TELEMETRY"
    DISCRETE_TELEMETRY = "DISCRETE_TELEMETRY"
    STATE = "STATE"
    COUNTER = "COUNTER"
    SESSION_ATTRIBUTE = "SESSION_ATTRIBUTE"
    ALARM_FLAG = "ALARM_FLAG"
    FAULT_CODE = "FAULT_CODE"
    TIMESTAMP = "TIMESTAMP"
    DERIVED_SOURCE_VALUE = "DERIVED_SOURCE_VALUE"
    UNKNOWN = "UNKNOWN"


class FieldCategory(StrEnum):
    """EV-charger domain the field belongs to (section 8)."""

    IDENTITY = "IDENTITY"
    ELECTRICAL_INPUT = "ELECTRICAL_INPUT"
    ELECTRICAL_OUTPUT = "ELECTRICAL_OUTPUT"
    THERMAL = "THERMAL"
    POWER_MODULE = "POWER_MODULE"
    SMR = "SMR"
    CONNECTOR = "CONNECTOR"
    GUN = "GUN"
    INSULATION = "INSULATION"
    COMMUNICATION = "COMMUNICATION"
    OCPP = "OCPP"
    CCS = "CCS"
    CCU = "CCU"
    PLC = "PLC"
    CAN = "CAN"
    SESSION = "SESSION"
    STATE_MACHINE = "STATE_MACHINE"
    CONTACTOR = "CONTACTOR"
    COOLING = "COOLING"
    FAN = "FAN"
    METER = "METER"
    BATTERY = "BATTERY"
    COUNTER = "COUNTER"
    FAULT = "FAULT"
    ALARM = "ALARM"
    FIRMWARE = "FIRMWARE"
    HARDWARE = "HARDWARE"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"


class CanonicalDataType(StrEnum):
    """Semantic type - deliberately NOT the DataFrame-inferred type (section 11)."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    DATETIME = "DATETIME"
    DURATION = "DURATION"
    IDENTIFIER = "IDENTIFIER"
    UNKNOWN = "UNKNOWN"

    @property
    def is_numeric(self) -> bool:
        return self in {CanonicalDataType.INTEGER, CanonicalDataType.FLOAT}


class StorageStrategy(StrEnum):
    """Intended Silver-layer destination (section 17).  Mapping only - no tables."""

    MASTER_DATA = "MASTER_DATA"
    CONFIGURATION_SNAPSHOT = "CONFIGURATION_SNAPSHOT"
    CHARGER_TELEMETRY = "CHARGER_TELEMETRY"
    CONNECTOR_TELEMETRY = "CONNECTOR_TELEMETRY"
    SMR_TELEMETRY = "SMR_TELEMETRY"
    SESSION_OBSERVATION = "SESSION_OBSERVATION"
    ALARM_EVENT = "ALARM_EVENT"
    COUNTER_TELEMETRY = "COUNTER_TELEMETRY"
    RAW_ONLY = "RAW_ONLY"
    UNKNOWN = "UNKNOWN"


class NormalizationStrategy(StrEnum):
    """How Phase 1C/1D should fold the wide row into the Silver model.

    Declared here as metadata only; nothing consumes it in Phase 1B.
    """

    PASSTHROUGH = "PASSTHROUGH"
    CHARGER_SCALAR = "CHARGER_SCALAR"
    PER_CONNECTOR = "PER_CONNECTOR"
    PER_SMR = "PER_SMR"
    PER_SESSION = "PER_SESSION"
    ALARM_EDGE = "ALARM_EDGE"
    COUNTER_SNAPSHOT = "COUNTER_SNAPSHOT"
    CONFIG_SNAPSHOT = "CONFIG_SNAPSHOT"
    RAW_RETAIN = "RAW_RETAIN"
    UNKNOWN = "UNKNOWN"


class AggregationStrategy(StrEnum):
    """How the field collapses when several raw rows share a logical key."""

    NONE = "NONE"
    FIRST = "FIRST"
    LAST = "LAST"
    MIN = "MIN"
    MAX = "MAX"
    MEAN = "MEAN"
    MEDIAN = "MEDIAN"
    SUM = "SUM"
    MODE = "MODE"
    ANY_TRUE = "ANY_TRUE"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    UNKNOWN = "UNKNOWN"


class ReviewStatus(StrEnum):
    """Field-definition review workflow (section 30).

    DOMAIN_REVIEW_REQUIRED is a deliberate, safe state - it is what we record
    instead of inventing a definition.
    """

    AUTO_CLASSIFIED = "AUTO_CLASSIFIED"
    ENGINEER_REVIEWED = "ENGINEER_REVIEWED"
    DOMAIN_REVIEW_REQUIRED = "DOMAIN_REVIEW_REQUIRED"
    VERIFIED = "VERIFIED"


class MlCandidate(StrEnum):
    """Tri-state.  Metadata only - Phase 1B builds no features (section 18)."""

    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class PredictionDomain(StrEnum):
    CHARGER_HEALTH = "charger_health"
    SMR_HEALTH = "smr_health"
    THERMAL_FAILURE = "thermal_failure"
    CONTACTOR_FAILURE = "contactor_failure"
    COMMUNICATION_FAILURE = "communication_failure"
    INSULATION_FAILURE = "insulation_failure"
    CONNECTOR_FAILURE = "connector_failure"
    SESSION_FAILURE = "session_failure"


class LeakageRisk(StrEnum):
    """Target-leakage exposure for future supervised learning (section 19)."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class AvailabilitySemantics(StrEnum):
    """When in the lifecycle a value actually becomes known (section 19)."""

    REAL_TIME = "REAL_TIME"
    SESSION_START = "SESSION_START"
    SESSION_DURING = "SESSION_DURING"
    SESSION_END = "SESSION_END"
    POST_EVENT = "POST_EVENT"
    STATIC = "STATIC"
    UNKNOWN = "UNKNOWN"


class RangeStatus(StrEnum):
    """Whether valid_min/valid_max are engineering-justified (section 15)."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VariabilityClass(StrEnum):
    """Per-file observation only.  Never a global statement about a field (section 29)."""

    ALL_NULL_IN_SAMPLE = "ALL_NULL_IN_SAMPLE"
    CONSTANT_IN_SAMPLE = "CONSTANT_IN_SAMPLE"
    VARIABLE_IN_SAMPLE = "VARIABLE_IN_SAMPLE"


# ---------------------------------------------------------------------------
# Phase 1C - fleet-scale daily operations
# ---------------------------------------------------------------------------


class ChargerLifecycleStatus(StrEnum):
    """Not every registered charger is expected to send telemetry every day."""

    COMMISSIONED = "COMMISSIONED"
    ACTIVE = "ACTIVE"
    TEMPORARILY_INACTIVE = "TEMPORARILY_INACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"
    TEST = "TEST"


class ArrivalStatus(StrEnum):
    """Did the charger-day's telemetry turn up, and was it on time? (section 6)."""

    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    LATE = "LATE"
    MISSING = "MISSING"
    #: Telemetry arrived for a charger absent from the expected fleet registry.
    UNEXPECTED = "UNEXPECTED"


class CompletenessStatus(StrEnum):
    """How much of the charger-day is actually present.

    Thresholds live in configuration, never inline in the evaluator.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SEVERELY_INCOMPLETE = "SEVERELY_INCOMPLETE"
    NO_DATA = "NO_DATA"
    UNKNOWN = "UNKNOWN"


class GapSeverity(StrEnum):
    """Duration-banded telemetry gap severity; bands are configurable."""

    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FileDateSpan(StrEnum):
    """Whether a file's telemetry stays inside one business date (section 8)."""

    SINGLE_DAY = "SINGLE_DAY"
    CROSS_MIDNIGHT = "CROSS_MIDNIGHT"
    MULTI_DAY = "MULTI_DAY"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Phase 1D - source frame reconstruction
# ---------------------------------------------------------------------------


class FrameStatus(StrEnum):
    """Structural verdict on a reconstructed frame.

    Structure only. Whether a frame duplicates another is a separate dimension -
    a frame can be both COMPLETE and a replay.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SEVERELY_INCOMPLETE = "SEVERELY_INCOMPLETE"
    MALFORMED = "MALFORMED"
    AMBIGUOUS = "AMBIGUOUS"


class DuplicateClassification(StrEnum):
    """How a frame relates to others sharing its event timestamp.

    ``SAME_TIMESTAMP_DISTINCT_FRAME`` is the case that makes naive
    de-duplication on (timestamp, connector, SMR) unsafe: the rows share that key
    but carry genuinely different telemetry.
    """

    UNIQUE = "UNIQUE"
    EXACT_ROW_DUPLICATE = "EXACT_ROW_DUPLICATE"
    FULL_FRAME_REPLAY = "FULL_FRAME_REPLAY"
    PARTIAL_FRAME_REPLAY = "PARTIAL_FRAME_REPLAY"
    SAME_TIMESTAMP_DISTINCT_FRAME = "SAME_TIMESTAMP_DISTINCT_FRAME"
    AMBIGUOUS = "AMBIGUOUS"


__all__ = [
    "AggregationStrategy",
    "ArrivalStatus",
    "AvailabilitySemantics",
    "CanonicalDataType",
    "ChargerLifecycleStatus",
    "CompletenessStatus",
    "DuplicateClassification",
    "FieldCategory",
    "FieldClass",
    "FieldEntity",
    "FileDateSpan",
    "FileStatus",
    "FrameStatus",
    "GapSeverity",
    "IngestionRunStatus",
    "IngestionTrigger",
    "LeakageRisk",
    "MlCandidate",
    "NormalizationStrategy",
    "PredictionDomain",
    "QualityDimension",
    "QualityIssueType",
    "QualityRuleScope",
    "QualitySeverity",
    "RangeStatus",
    "ReviewStatus",
    "SchemaCompatibility",
    "SchemaCoverageStatus",
    "SchemaVersionStatus",
    "SourceType",
    "StorageStrategy",
    "VariabilityClass",
]
