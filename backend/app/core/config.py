"""Typed application configuration.

Everything that the platform must not hard-code lives here: safety limits,
timestamp formats, expected topology and storage roots.  Nothing in the
ingestion path reads ``os.environ`` directly.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = ".env"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    CONSOLE = "console"
    JSON = "json"


class AcknowledgeStrategy(StrEnum):
    """What a source adapter does with the origin file once it is landed."""

    NONE = "none"
    MOVE = "move"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CPI_DATABASE_", env_file=_ENV_FILE, extra="ignore"
    )

    host: str = "localhost"
    port: int = 5432
    user: str = "cpi"
    # Development-only default; real deployments supply CPI_DATABASE_PASSWORD.
    password: str = "cpi"  # noqa: S105
    name: str = "cpi"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    # Full override.  When set, the discrete fields above are ignored.  This is
    # what the test-suite and Alembic use to point at another database.
    url: str | None = None

    @property
    def async_url(self) -> str:
        if self.url:
            return self.url
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        )

    @property
    def is_sqlite(self) -> bool:
        return self.async_url.startswith("sqlite")


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CPI_API_", env_file=_ENV_FILE, extra="ignore")

    host: str = "0.0.0.0"  # noqa: S104 - containers must bind all interfaces
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    default_page_size: int = 50
    max_page_size: int = 200
    #: Upper bound on a coverage-history request, so an unbounded range cannot
    #: turn one HTTP call into a full-table scan.
    max_coverage_history_days: int = 400


class StorageSettings(BaseSettings):
    """Bronze landing zone roots.

    These are *internal* paths.  They are never returned through the public API
    (section 20 - do not leak local filesystem paths).
    """

    model_config = SettingsConfigDict(env_prefix="CPI_STORAGE_", env_file=_ENV_FILE, extra="ignore")

    raw_root: Path = Path("./data/raw")
    quarantine_root: Path = Path("./data/quarantine")
    processed_root: Path = Path("./data/processed")


class FilesystemSourceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CPI_SOURCE_FILESYSTEM_", env_file=_ENV_FILE, extra="ignore"
    )

    inbox: Path = Path("./data/inbox")
    glob: str = "*.csv"
    ack_strategy: AcknowledgeStrategy = AcknowledgeStrategy.NONE
    archive_dir: Path = Path("./data/inbox_archive")


class IngestSettings(BaseSettings):
    """Ingestion safety limits and parsing policy.

    None of these values are inferred from the incoming file.  Section 20 of the
    contract is explicit: filenames, MIME types, column names, field types and
    row contents are all untrusted.
    """

    model_config = SettingsConfigDict(env_prefix="CPI_INGEST_", env_file=_ENV_FILE, extra="ignore")

    max_file_size_bytes: int = 536_870_912  # 512 MiB
    max_column_count: int = 2000
    max_row_count: int = 5_000_000
    allowed_extensions: list[str] = Field(default_factory=lambda: [".csv"])

    # Event-time parsing.  Day-first formats are declared explicitly; the parser
    # never guesses between day-first and month-first (section 11).
    timestamp_formats: list[str] = Field(
        default_factory=lambda: [
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ]
    )
    timestamp_failure_tolerance: float = 0.02

    expected_connector_count: int = 2
    expected_smr_count: int = 4
    telemetry_gap_factor: float = 5.0

    # Values that look numeric but almost certainly encode "no reading".
    # Phase 1A only profiles and flags these - it never rewrites them.
    global_sentinel_values: list[str] = Field(
        default_factory=lambda: ["-150", "-999", "-9999", "65535"]
    )

    @field_validator("allowed_extensions")
    @classmethod
    def _normalise_extensions(cls, value: list[str]) -> list[str]:
        return [ext if ext.startswith(".") else f".{ext}" for ext in (e.lower() for e in value)]

    @field_validator("timestamp_failure_tolerance")
    @classmethod
    def _check_tolerance(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("timestamp_failure_tolerance must be between 0.0 and 1.0")
        return value


class FleetSettings(BaseSettings):
    """Fleet-scale daily operations policy (Phase 1C).

    Every threshold that decides COMPLETE vs PARTIAL, or what counts as a gap,
    lives here.  None of these numbers appear as literals in the evaluators.
    """

    model_config = SettingsConfigDict(env_prefix="CPI_FLEET_", env_file=_ENV_FILE, extra="ignore")

    #: Applied to naive source timestamps.  Chargers may later span regions, so
    #: this is a default, overridable per charger, not a parsing rule.
    default_source_timezone: str = "Asia/Kolkata"

    #: Global cadence default.  Precedence: charger > charger model > schema
    #: version > this global default.
    default_sampling_interval_seconds: int = 120

    #: A gap is an inter-sample interval longer than
    #: expected_interval * gap_threshold_multiplier.
    gap_threshold_multiplier: float = 3.0

    # Gap severity bands, in seconds.  Development defaults; tune per fleet.
    gap_minor_seconds: int = 300  # 5 minutes
    gap_moderate_seconds: int = 1800  # 30 minutes
    gap_major_seconds: int = 7200  # 2 hours
    gap_critical_seconds: int = 21600  # 6 hours

    # Completeness bands, as sample-coverage percentages.
    completeness_complete_min_pct: float = 95.0
    completeness_partial_min_pct: float = 50.0

    #: A charger-day is late when its first file was received later than
    #: business_date end + this grace period.
    late_arrival_grace_hours: int = 24

    #: Seconds in a full telemetry day; used for expected-sample estimation.
    day_seconds: int = 86_400

    #: Tolerance before observed cadence is called abnormal, as a ratio of the
    #: expected interval (0.5 => flag if median is <50% or >150% of expected).
    cadence_deviation_tolerance: float = 0.5

    @field_validator("gap_threshold_multiplier")
    @classmethod
    def _check_multiplier(cls, value: float) -> float:
        if value <= 1.0:
            raise ValueError("gap_threshold_multiplier must be greater than 1.0")
        return value


class DailyQualitySeverities(BaseSettings):
    """Severity of each charger-day rule (Phase 1C section 28).

    Severities are configuration, not literals in the rules, because what counts
    as merely noteworthy differs per fleet.  Two defaults are deliberate:

    ``event_date_filename_mismatch`` is a WARNING, never fatal - the known
    production sample exhibits it, and the event date is authoritative anyway.

    ``multiple_files_same_charger_day`` is INFO - two files combining into one
    complete day is normal operation, not a defect (section 19).
    """

    model_config = SettingsConfigDict(
        env_prefix="CPI_DAILY_SEVERITY_", env_file=_ENV_FILE, extra="ignore"
    )

    missing_charger_data: str = "ERROR"
    late_file: str = "WARNING"
    partial_day: str = "WARNING"
    severely_incomplete_day: str = "ERROR"
    telemetry_gap: str = "WARNING"
    abnormal_sampling_interval: str = "WARNING"
    missing_expected_connector: str = "WARNING"
    missing_expected_smr: str = "WARNING"
    multiple_files_same_charger_day: str = "INFO"
    overlapping_file_coverage: str = "INFO"
    event_date_filename_mismatch: str = "WARNING"

    #: Only gaps at least this severe raise a TELEMETRY_GAP finding, so a day
    #: with dozens of minor cadence wobbles does not drown the daily report.
    gap_min_severity: str = "MODERATE"


class QualityScoreWeights(BaseSettings):
    """Weights for the transparent multi-dimension quality score.

    The score is a weighted mean of independently computed dimensions rather
    than one opaque formula.  See docs/data-quality.md.
    """

    model_config = SettingsConfigDict(
        env_prefix="CPI_QUALITY_WEIGHT_", env_file=_ENV_FILE, extra="ignore"
    )

    schema_quality: float = 0.30
    completeness_quality: float = 0.20
    validity_quality: float = 0.20
    duplicate_quality: float = 0.15
    timestamp_quality: float = 0.15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CPI_", env_file=_ENV_FILE, extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE
    project_root: Path = Path()

    # Optional path to the real production-like charger CSV.  Used only by the
    # opt-in integration profile run; absence must never break the suite.
    real_sample_path: Path | None = None

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    filesystem_source: FilesystemSourceSettings = Field(default_factory=FilesystemSourceSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    fleet: FleetSettings = Field(default_factory=FleetSettings)
    quality_weights: QualityScoreWeights = Field(default_factory=QualityScoreWeights)
    daily_severities: DailyQualitySeverities = Field(default_factory=DailyQualitySeverities)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that the API, the worker and the CLI all observe one consistent
    configuration.  Tests clear the cache via ``get_settings.cache_clear()``.
    """
    return Settings()
