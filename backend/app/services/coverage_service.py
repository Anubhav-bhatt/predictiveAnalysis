"""Charger-day reconciliation (Phase 1C sections 16, 19, 24, 40, 41, 44).

This service turns "what files did we get?" into "do we have the fleet's day?".

It is the component that answers the Phase 1C questions, and its contract is
narrow enough to state completely:

    reconcile(business_date) is idempotent.

Running it twice changes nothing.  Running it again after a late file arrives
flips that charger-day from MISSING to LATE/COMPLETE *in place* - it never
creates a second coverage row, a second gap set, or a second copy of the daily
findings.  Three mechanisms deliver that:

* coverage identity is ``(charger_id, business_date)``, upserted not inserted;
* gaps are deleted for every affected charger-day and rewritten from scratch, so
  a gap that a late file filled disappears rather than lingering (section 44);
* charger-day findings are replaced per coverage row, keyed by a hash that
  excludes counts.

Fleet scale (section 40) is handled by refusing to loop over the database. The
whole pass is a fixed number of statements: read the expected fleet, read every
file-day for the date, then bulk-upsert coverage, bulk-replace gaps and
bulk-replace findings. Per-charger work happens in memory, never in SQL.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from backend.app.core.config import DailyQualitySeverities, FleetSettings, Settings
from backend.app.core.logging import get_logger, log_context
from backend.app.models.charger import Charger
from backend.app.models.enums import ArrivalStatus, CompletenessStatus, QualityRuleScope
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.ingestion import TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from pipelines.ingestion.coverage import (
    CoverageEvaluation,
    CoveragePolicy,
    FileContribution,
    evaluate_charger_day,
    is_late,
)
from pipelines.quality.daily_rules import (
    ChargerDayContext,
    DailyFinding,
    evaluate_charger_day_rules,
)

__all__ = ["ReconciliationSummary", "CoverageService"]

logger = get_logger(__name__)


@dataclass(slots=True)
class ReconciliationSummary:
    """Outcome of one reconciliation pass over one business date."""

    business_date: dt.date

    expected_charger_count: int = 0
    received_charger_count: int = 0
    complete_count: int = 0
    partial_count: int = 0
    severely_incomplete_count: int = 0
    missing_charger_count: int = 0
    late_charger_count: int = 0
    unexpected_charger_count: int = 0

    total_unique_timestamps: int = 0
    total_raw_rows: int = 0
    gap_count: int = 0
    daily_finding_count: int = 0

    fleet_coverage_percentage: float = 0.0
    average_coverage_percentage: float = 0.0

    coverage_ids: dict[str, UUID] = field(default_factory=dict)

    @property
    def delivery_rate(self) -> float:
        """Share of expected chargers that delivered anything at all."""
        if self.expected_charger_count <= 0:
            return 0.0
        return round(100.0 * self.received_charger_count / self.expected_charger_count, 3)

    def as_dict(self) -> dict[str, object]:
        return {
            "business_date": self.business_date.isoformat(),
            "expected_chargers": self.expected_charger_count,
            "received_chargers": self.received_charger_count,
            "complete": self.complete_count,
            "partial": self.partial_count,
            "severely_incomplete": self.severely_incomplete_count,
            "missing": self.missing_charger_count,
            "late": self.late_charger_count,
            "unexpected": self.unexpected_charger_count,
            "unique_event_timestamps": self.total_unique_timestamps,
            "raw_rows": self.total_raw_rows,
            "gap_count": self.gap_count,
            "daily_findings": self.daily_finding_count,
            "fleet_coverage_percentage": self.fleet_coverage_percentage,
            "average_coverage_percentage": self.average_coverage_percentage,
            "delivery_rate": self.delivery_rate,
        }


class CoverageService:
    def __init__(
        self,
        fleet_repo: FleetRepository,
        file_repo: TelemetryFileRepository,
        quality_repo: QualityRepository,
        settings: Settings,
    ) -> None:
        self._fleet = fleet_repo
        self._files = file_repo
        self._quality = quality_repo
        self._settings = settings

    @property
    def _fleet_settings(self) -> FleetSettings:
        return self._settings.fleet

    @property
    def _severities(self) -> DailyQualitySeverities:
        return self._settings.daily_severities

    # -- public API --------------------------------------------------------

    async def reconcile(
        self, business_date: dt.date, *, ingestion_run_id: UUID | None = None
    ) -> ReconciliationSummary:
        """Rebuild every charger-day for one business date.

        Safe to call repeatedly; see the module docstring for why.
        """
        with log_context(business_date=business_date.isoformat()):
            # The session runs with autoflush disabled, so a file whose status was
            # advanced to READY_FOR_NORMALIZATION earlier in this same transaction
            # is still pending in the identity map. Reconciliation reads file state
            # with Core selects, which would not see it - and would then treat a
            # freshly ingested file as unusable and report the charger MISSING.
            await self._fleet.session.flush()

            expected = await self._fleet.expected_chargers(business_date)
            expected_by_id = {c.charger_id: c for c in expected}

            file_days = await self._files.file_days_for_date(business_date)
            grouped = self._group_by_charger(file_days)

            summary = ReconciliationSummary(
                business_date=business_date, expected_charger_count=len(expected_by_id)
            )

            evaluations: list[_Evaluated] = []

            # Chargers that delivered something - expected or not.
            for charger_id, contributions in grouped.items():
                charger = expected_by_id.get(charger_id)
                policy = self._policy_for(charger)
                evaluation = evaluate_charger_day(
                    charger_id=charger_id,
                    business_date=business_date,
                    contributions=[c.contribution for c in contributions],
                    policy=policy,
                )
                late, late_by = is_late(
                    business_date=business_date,
                    first_received_at=evaluation.first_received_at,
                    policy=policy,
                )
                if charger is None:
                    arrival = ArrivalStatus.UNEXPECTED
                elif late:
                    arrival = ArrivalStatus.LATE
                else:
                    arrival = ArrivalStatus.RECEIVED
                evaluations.append(
                    _Evaluated(charger_id, evaluation, arrival, charger, late_by or 0)
                )

            # Expected chargers that delivered nothing become real MISSING rows
            # rather than an absence someone has to notice (section 16).
            for charger_id, charger in expected_by_id.items():
                if charger_id in grouped:
                    continue
                policy = self._policy_for(charger)
                evaluation = evaluate_charger_day(
                    charger_id=charger_id,
                    business_date=business_date,
                    contributions=[],
                    policy=policy,
                )
                evaluations.append(
                    _Evaluated(charger_id, evaluation, ArrivalStatus.MISSING, charger, 0)
                )

            await self._persist(business_date, evaluations, grouped, summary, ingestion_run_id)

            logger.info(
                "coverage.reconciled",
                processing_stage="RECONCILING",
                expected=summary.expected_charger_count,
                received=summary.received_charger_count,
                missing=summary.missing_charger_count,
                late=summary.late_charger_count,
                partial=summary.partial_count,
                gap_count=summary.gap_count,
                coverage_percentage=summary.fleet_coverage_percentage,
                final_status="COMPLETED",
            )
            return summary

    async def reconcile_dates(
        self, dates: Sequence[dt.date], *, ingestion_run_id: UUID | None = None
    ) -> list[ReconciliationSummary]:
        """Reconcile several dates - what a run touching a cross-midnight file needs."""
        return [
            await self.reconcile(business_date, ingestion_run_id=ingestion_run_id)
            for business_date in sorted(set(dates))
        ]

    # -- internals ---------------------------------------------------------

    def _policy_for(self, charger: Charger | None) -> CoveragePolicy:
        """Resolve cadence and timezone with documented precedence (section 10).

        charger override > global default. Charger-model and schema-version tiers
        are declared in the contract but have no storage yet, so they are not
        silently faked here - the precedence chain simply has two live levels.
        """
        interval = charger.expected_sampling_interval_seconds if charger else None
        timezone = charger.source_timezone if charger else None
        return CoveragePolicy.from_settings(
            self._fleet_settings,
            expected_interval_seconds=interval,
            source_timezone=timezone,
        )

    @staticmethod
    def _group_by_charger(
        rows: Sequence[tuple[TelemetryFileDay, TelemetryFile]],
    ) -> dict[str, list[_Contribution]]:
        """Turn (file_day, file) pairs into per-charger contribution lists."""
        grouped: dict[str, list[_Contribution]] = {}
        for file_day, telemetry_file in rows:
            contribution = FileContribution(
                telemetry_file_id=telemetry_file.id,
                # Rehydrated from the persisted offsets: no CSV is re-read to
                # reconcile, which is what makes late-arrival handling cheap.
                timestamps=file_day.timestamps_utc(),
                received_at=telemetry_file.received_at,
                connectors=frozenset(file_day.connectors_seen or ()),
                smrs=frozenset(file_day.smrs_seen or ()),
                quality_score=telemetry_file.quality_score,
                exact_duplicate_rows=file_day.exact_duplicate_row_count,
                logical_collision_groups=file_day.logical_collision_count,
                duplicate_timestamp_count=file_day.duplicate_timestamp_count,
            )
            grouped.setdefault(file_day.charger_id, []).append(
                _Contribution(
                    contribution=contribution,
                    file_day=file_day,
                    telemetry_file=telemetry_file,
                )
            )
        return grouped

    async def _persist(
        self,
        business_date: dt.date,
        evaluations: Sequence[_Evaluated],
        grouped: dict[str, list[_Contribution]],
        summary: ReconciliationSummary,
        ingestion_run_id: UUID | None,
    ) -> None:
        coverage_rows: list[dict[str, object]] = []

        for item in evaluations:
            self._tally(summary, item.evaluation, item.arrival, grouped.get(item.charger_id, []))
            coverage_rows.append(
                self._coverage_row(
                    item.evaluation, item.arrival, item.charger, item.late_by_seconds
                )
            )

        coverage_ids = await self._fleet.upsert_coverage_bulk(business_date, coverage_rows)
        summary.coverage_ids = coverage_ids

        gap_payloads: list[tuple[UUID, list[dict[str, object]]]] = []
        issue_payloads: list[tuple[UUID, list[dict[str, object]]]] = []

        for item in evaluations:
            charger_id, evaluation, charger = item.charger_id, item.evaluation, item.charger
            coverage_id = coverage_ids.get(charger_id)
            if coverage_id is None:  # pragma: no cover - upsert returns every key
                continue
            charger_pk = charger.id if charger else None
            gap_payloads.append(
                (
                    coverage_id,
                    [
                        {
                            "charger_pk": charger_pk,
                            "charger_id": charger_id,
                            "business_date": business_date,
                            "telemetry_file_id": evaluation.primary_telemetry_file_id,
                            "start_event_at": gap.start_event_at,
                            "end_event_at": gap.end_event_at,
                            "duration_seconds": gap.duration_seconds,
                            "expected_interval_seconds": gap.expected_interval_seconds,
                            "estimated_missing_samples": gap.estimated_missing_samples,
                            "severity": gap.severity,
                        }
                        for gap in evaluation.gaps
                    ],
                )
            )

            findings = evaluate_charger_day_rules(
                ChargerDayContext(
                    evaluation=evaluation,
                    arrival_status=item.arrival,
                    expected_connectors=self._expected_connectors(charger),
                    expected_smrs=self._expected_smrs(charger),
                    late_by_seconds=item.late_by_seconds,
                    filename_date_mismatches=self._filename_mismatches(
                        grouped.get(charger_id, []), business_date
                    ),
                ),
                self._severities,
            )
            summary.daily_finding_count += len(findings)
            issue_payloads.append(
                (coverage_id, [self._issue_row(f, ingestion_run_id) for f in findings])
            )

        await self._fleet.replace_gaps_bulk(gap_payloads)
        await self._quality.replace_charger_day_issues_bulk(issue_payloads)

        self._finalise(summary, evaluations)

    def _expected_connectors(self, charger: Charger | None) -> int | None:
        if charger and charger.expected_connector_count is not None:
            return charger.expected_connector_count
        return self._settings.ingest.expected_connector_count

    def _expected_smrs(self, charger: Charger | None) -> int | None:
        if charger and charger.expected_smr_count is not None:
            return charger.expected_smr_count
        return self._settings.ingest.expected_smr_count

    @staticmethod
    def _filename_mismatches(
        contributions: Sequence[_Contribution], business_date: dt.date
    ) -> list[tuple[str, dt.date]]:
        """Files whose filename date disagrees with the telemetry date (section 29).

        Reported only. The filename never rewrites the event date.
        """
        out: list[tuple[str, dt.date]] = []
        for item in contributions:
            filename_date = item.telemetry_file.filename_date
            if filename_date is not None and filename_date != business_date:
                out.append((item.telemetry_file.original_filename, filename_date))
        return out

    @staticmethod
    def _tally(
        summary: ReconciliationSummary,
        evaluation: CoverageEvaluation,
        arrival: ArrivalStatus,
        contributions: Sequence[_Contribution],
    ) -> None:
        match arrival:
            case ArrivalStatus.MISSING:
                summary.missing_charger_count += 1
            case ArrivalStatus.LATE:
                summary.late_charger_count += 1
                summary.received_charger_count += 1
            case ArrivalStatus.UNEXPECTED:
                summary.unexpected_charger_count += 1
            case _:
                summary.received_charger_count += 1

        match evaluation.completeness_status:
            case CompletenessStatus.COMPLETE:
                summary.complete_count += 1
            case CompletenessStatus.PARTIAL:
                summary.partial_count += 1
            case CompletenessStatus.SEVERELY_INCOMPLETE:
                summary.severely_incomplete_count += 1
            case _:
                pass

        summary.total_unique_timestamps += evaluation.unique_timestamp_count
        summary.total_raw_rows += sum(c.file_day.row_count for c in contributions)
        summary.gap_count += evaluation.gap_count

    @staticmethod
    def _finalise(
        summary: ReconciliationSummary,
        evaluations: Sequence[_Evaluated],
    ) -> None:
        """Fleet coverage is the mean over *expected* charger-days (section 39).

        Missing chargers contribute 0%, which is the whole point: excluding them
        would let a fleet that lost half its chargers report 99% coverage.
        UNEXPECTED charger-days are excluded because they are not part of the
        denominator the fleet is measured against.
        """
        expected_pcts = [
            item.evaluation.coverage_percentage
            for item in evaluations
            if item.arrival is not ArrivalStatus.UNEXPECTED
        ]
        all_pcts = [item.evaluation.coverage_percentage for item in evaluations]
        summary.fleet_coverage_percentage = (
            round(sum(expected_pcts) / len(expected_pcts), 3) if expected_pcts else 0.0
        )
        summary.average_coverage_percentage = (
            round(sum(all_pcts) / len(all_pcts), 3) if all_pcts else 0.0
        )

    def _coverage_row(
        self,
        evaluation: CoverageEvaluation,
        arrival: ArrivalStatus,
        charger: Charger | None,
        late_by: int,
    ) -> dict[str, object]:
        """Build a uniform coverage payload.

        Every row carries an identical key set - a hard requirement of the bulk
        insert/update path, which builds one statement for the whole batch.
        """
        ev = evaluation
        return {
            "charger_pk": charger.id if charger else None,
            "charger_id": ev.charger_id,
            "expected": arrival is not ArrivalStatus.UNEXPECTED,
            "file_count": ev.file_count,
            "primary_telemetry_file_id": ev.primary_telemetry_file_id,
            "first_event_at": ev.first_event_at,
            "last_event_at": ev.last_event_at,
            "unique_timestamp_count": ev.unique_timestamp_count,
            "expected_timestamp_count": ev.expected_timestamp_count,
            "expected_sampling_interval_seconds": ev.expected_sampling_interval_seconds,
            "observed_median_sampling_interval_seconds": _dec(
                ev.observed_median_interval_seconds
            ),
            "observed_p95_sampling_interval_seconds": _dec(ev.observed_p95_interval_seconds),
            "observed_min_sampling_interval_seconds": _dec(ev.observed_min_interval_seconds),
            "observed_max_sampling_interval_seconds": _dec(ev.observed_max_interval_seconds),
            "coverage_seconds": ev.coverage_seconds,
            "expected_coverage_seconds": ev.expected_coverage_seconds,
            "span_coverage_percentage": _dec(ev.span_coverage_percentage),
            "sample_coverage_percentage": _dec(ev.sample_coverage_percentage),
            "gap_adjusted_coverage_percentage": _dec(ev.gap_adjusted_coverage_percentage),
            "coverage_percentage": _dec(ev.coverage_percentage),
            "largest_gap_seconds": ev.largest_gap_seconds,
            "gap_count": ev.gap_count,
            "total_gap_seconds": ev.total_gap_seconds,
            "duplicate_timestamp_count": ev.duplicate_timestamp_count,
            "logical_collision_count": ev.logical_collision_count,
            "overlapping_timestamp_count": ev.overlapping_timestamp_count,
            "duplicate_file_count": ev.duplicate_file_count,
            "connector_count_detected": len(ev.connectors_detected),
            "smr_count_detected": len(ev.smrs_detected),
            "expected_connector_count": self._expected_connectors(charger),
            "expected_smr_count": self._expected_smrs(charger),
            "arrival_status": arrival,
            "completeness_status": ev.completeness_status,
            "first_received_at": ev.first_received_at,
            "late_by_seconds": late_by or None,
            # Deliberately the charger-day aggregate, never a write-back over the
            # per-file score (section 25).
            "quality_score": ev.quality_score,
            "last_evaluated_at": dt.datetime.now(dt.UTC),
            "updated_at": dt.datetime.now(dt.UTC),
        }

    @staticmethod
    def _issue_row(finding: DailyFinding, ingestion_run_id: UUID | None) -> dict[str, object]:
        return {
            "telemetry_file_id": None,
            "ingestion_run_id": ingestion_run_id,
            "field_definition_id": None,
            "rule_code": finding.rule_code,
            "scope": QualityRuleScope.CHARGER_DAY,
            "severity": finding.severity,
            "entity": None,
            "field_name": None,
            "field_occurrence": None,
            "source_row_number": None,
            "event_time": finding.event_time,
            "entity_reference": finding.entity_reference,
            "charger_id": finding.charger_id,
            "business_date": finding.business_date,
            "raw_value": None,
            "message": finding.message,
            "details": dict(finding.details) or None,
            "occurrence_count": finding.occurrence_count,
            "issue_hash": finding.issue_hash,
            "detected_at": dt.datetime.now(dt.UTC),
        }


@dataclass(frozen=True, slots=True)
class _Evaluated:
    """One charger-day's assessment, before persistence."""

    charger_id: str
    evaluation: CoverageEvaluation
    arrival: ArrivalStatus
    charger: Charger | None
    late_by_seconds: int


@dataclass(frozen=True, slots=True)
class _Contribution:
    """A file-day paired with its parent file record."""

    contribution: FileContribution
    file_day: TelemetryFileDay
    telemetry_file: TelemetryFile


def _dec(value: float | None, places: str = "0.001") -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 3))).quantize(Decimal(places))
