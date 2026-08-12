"""Phase 1C data-operations response models.

These are read models, deliberately not the ORM entities.  Two rules are enforced
by construction rather than by reviewer vigilance:

* Internal filesystem paths (``storage_reference``) never appear in a response.
* Coverage is always reported with its three dimensions plus the raw-row count,
  so a consumer can never mistake raw rows for coverage (section 49).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backend.app.models.enums import (
    ArrivalStatus,
    CompletenessStatus,
    FileDateSpan,
    FileStatus,
    GapSeverity,
    IngestionRunStatus,
    QualitySeverity,
)

__all__ = [
    "ChargerCoverageRow",
    "ChargerDayDetail",
    "DailyOperationsSummary",
    "DailyProcessingStage",
    "GapRow",
    "IngestionRunDetail",
    "IngestionRunRow",
    "LateFileRow",
    "MissingChargerRow",
]


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DailyProcessingStage(_Base):
    """One stage of the daily pipeline (section 32).

    Deliberately coarse: operators need to know which stage a date reached, not
    the internal state machine's every transition.
    """

    stage: str
    status: str
    detail: str | None = None
    count: int | None = None


class DailyOperationsSummary(_Base):
    """The section 31 headline block for one business date."""

    business_date: dt.date

    expected: int
    received: int
    complete: int
    partial: int
    severely_incomplete: int
    no_data: int
    late: int
    missing: int
    unexpected: int

    failed: int
    quarantined: int
    duplicate: int

    fleet_coverage_percentage: float
    average_coverage_percentage: float
    p50_coverage_percentage: float | None = None
    p95_coverage_percentage: float | None = None
    p95_largest_gap_seconds: int | None = None

    fleet_delivery_rate: float = 0.0
    fleet_complete_day_rate: float = 0.0
    fleet_missing_rate: float = 0.0
    fleet_partial_rate: float = 0.0
    late_arrival_rate: float = 0.0

    total_gap_count: int = 0
    largest_gap_seconds: int = 0

    #: Rule code -> occurrences, for the daily findings panel.
    daily_rule_counts: dict[str, int] = Field(default_factory=dict)
    stages: list[DailyProcessingStage] = Field(default_factory=list)


class ChargerCoverageRow(_Base):
    """One charger-day, as the partial/coverage tables render it (section 34)."""

    charger_id: str
    business_date: dt.date
    site_code: str | None = None
    ocpp_id: str | None = None

    arrival_status: ArrivalStatus
    completeness_status: CompletenessStatus
    expected: bool

    coverage_percentage: Decimal | None = None
    sample_coverage_percentage: Decimal | None = None
    span_coverage_percentage: Decimal | None = None
    gap_adjusted_coverage_percentage: Decimal | None = None

    first_event_at: dt.datetime | None = None
    last_event_at: dt.datetime | None = None
    unique_timestamp_count: int
    expected_timestamp_count: int | None = None

    expected_sampling_interval_seconds: int | None = None
    observed_median_sampling_interval_seconds: Decimal | None = None

    gap_count: int
    largest_gap_seconds: int | None = None

    connector_count_detected: int | None = None
    expected_connector_count: int | None = None
    smr_count_detected: int | None = None
    expected_smr_count: int | None = None

    file_count: int
    duplicate_timestamp_count: int
    logical_collision_count: int
    overlapping_timestamp_count: int

    first_received_at: dt.datetime | None = None
    late_by_seconds: int | None = None
    quality_score: Decimal | None = None
    last_evaluated_at: dt.datetime | None = None


class MissingChargerRow(_Base):
    """Section 33. Every field is real data or explicitly null - nothing invented."""

    charger_id: str
    business_date: dt.date
    site_code: str | None = None
    ocpp_id: str | None = None

    #: Start of the charger's telemetry window, when one is configured.
    expected_since: dt.date | None = None
    #: Most recent earlier date with telemetry, and its coverage.
    last_successful_date: dt.date | None = None
    last_successful_coverage_percentage: float | None = None
    #: Coverage on the immediately preceding date, when a record exists.
    previous_day_coverage_percentage: float | None = None
    last_seen_at: dt.datetime | None = None


class LateFileRow(_Base):
    """Section 35."""

    charger_id: str
    business_date: dt.date
    site_code: str | None = None
    received_at: dt.datetime | None = None
    late_by_seconds: int | None = None
    coverage_percentage: Decimal | None = None
    completeness_status: CompletenessStatus
    arrival_status: ArrivalStatus


class GapRow(_Base):
    charger_id: str
    business_date: dt.date
    start_event_at: dt.datetime
    end_event_at: dt.datetime
    duration_seconds: int
    expected_interval_seconds: int | None = None
    estimated_missing_samples: int | None = None
    severity: GapSeverity

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_minutes(self) -> float:
        return round(self.duration_seconds / 60.0, 2)


class ChargerDayDetail(_Base):
    """Charger-day coverage plus its gaps and findings, for the drill-down."""

    coverage: ChargerCoverageRow
    gaps: list[GapRow] = Field(default_factory=list)
    findings: list[ChargerDayFinding] = Field(default_factory=list)
    files: list[ContributingFile] = Field(default_factory=list)


class ChargerDayFinding(_Base):
    rule_code: str
    severity: QualitySeverity
    message: str
    occurrence_count: int
    detected_at: dt.datetime


class ContributingFile(_Base):
    """A file that contributed telemetry to a charger-day (section 19).

    ``storage_reference`` is intentionally absent - internal paths are never
    serialised (Phase 1A section 20).
    """

    telemetry_file_id: UUID
    original_filename: str
    status: FileStatus
    received_at: dt.datetime
    business_date: dt.date | None = None
    filename_date: dt.date | None = None
    file_date_span: FileDateSpan | None = None
    row_count_for_date: int
    unique_timestamp_count_for_date: int
    first_event_at: dt.datetime | None = None
    last_event_at: dt.datetime | None = None
    quality_score: Decimal | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def filename_date_matches_event_date(self) -> bool | None:
        """None when the filename carries no date at all."""
        if self.filename_date is None:
            return None
        return self.filename_date == self.business_date


class IngestionRunRow(_Base):
    id: UUID
    business_date: dt.date | None = None
    source_type: str
    trigger: str
    status: IngestionRunStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None = None

    files_discovered: int
    files_registered: int
    files_ready: int
    files_partial: int
    files_duplicate: int
    files_quarantined: int
    files_failed: int

    expected_charger_count: int | None = None
    received_charger_count: int | None = None
    missing_charger_count: int | None = None
    late_charger_count: int | None = None
    fleet_coverage_percentage: Decimal | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds(), 3)


class IngestionRunDetail(IngestionRunRow):
    failure_reason: str | None = None
    request_id: str | None = None


# Resolve the forward references declared above.
ChargerDayDetail.model_rebuild()
