"""Charger-day quality rules (Phase 1C section 28).

These are a *separate* rule family from the Phase 1B file rules, and the
separation is deliberate (section 25):

    A file can be perfectly schema-valid and still carry only 20% of the day.

File quality answers "is this file trustworthy?".  Charger-day quality answers
"do we have the day?".  Neither may overwrite the other, so these rules read a
:class:`CoverageEvaluation` rather than a ``FileProfile``, and their findings are
anchored to the charger-day coverage row instead of a telemetry file.

Severities all come from configuration.  Two defaults are worth stating out loud:
``EVENT_DATE_FILENAME_MISMATCH`` is a warning rather than a failure because the
real sample exhibits it and the event timestamps are authoritative regardless;
``MULTIPLE_FILES_SAME_CHARGER_DAY`` is informational because two files forming
one complete day is normal operation (section 19).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from backend.app.core.config import DailyQualitySeverities
from backend.app.models.enums import (
    ArrivalStatus,
    CompletenessStatus,
    GapSeverity,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)
from pipelines.ingestion.coverage import CoverageEvaluation

__all__ = ["ChargerDayContext", "DailyFinding", "evaluate_charger_day_rules"]

#: Ordering used to compare a gap against the configured reporting floor.
_GAP_ORDER: dict[GapSeverity, int] = {
    GapSeverity.MINOR: 0,
    GapSeverity.MODERATE: 1,
    GapSeverity.MAJOR: 2,
    GapSeverity.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class DailyFinding:
    """A charger-day finding, shaped for persistence next to file findings."""

    rule_code: QualityIssueType
    severity: QualitySeverity
    message: str
    charger_id: str
    business_date: dt.date
    occurrence_count: int = 1
    entity_reference: str | None = None
    event_time: dt.datetime | None = None
    details: dict[str, object] = field(default_factory=dict)

    scope: QualityRuleScope = QualityRuleScope.CHARGER_DAY

    @property
    def issue_hash(self) -> str:
        """Stable identity: rule plus locator, never the counts.

        Excluding counts is what lets a reconciliation run update a finding whose
        tally changed instead of inserting a second row (section 41).
        """
        import hashlib

        parts = (
            self.rule_code.value,
            self.scope.value,
            self.charger_id,
            self.business_date.isoformat(),
            self.entity_reference or "",
            self.event_time.isoformat() if self.event_time else "",
        )
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChargerDayContext:
    """Everything the daily rules need, assembled once per charger-day."""

    evaluation: CoverageEvaluation
    arrival_status: ArrivalStatus

    expected_connectors: int | None = None
    expected_smrs: int | None = None

    late_by_seconds: int | None = None

    #: Files whose filename date disagrees with their telemetry date, as
    #: ``(filename, filename_date)``. Reported, never acted upon (section 29).
    filename_date_mismatches: Sequence[tuple[str, dt.date]] = ()

    def severity_of(self, name: str, severities: DailyQualitySeverities) -> QualitySeverity:
        raw = str(getattr(severities, name, "WARNING")).upper()
        try:
            return QualitySeverity(raw)
        except ValueError:
            return QualitySeverity.WARNING


def evaluate_charger_day_rules(
    context: ChargerDayContext,
    severities: DailyQualitySeverities | None = None,
) -> list[DailyFinding]:
    """Run every charger-day rule and return findings in stable order."""
    config = severities or DailyQualitySeverities()
    findings: list[DailyFinding] = []
    for rule in _RULES:
        findings.extend(rule(context, config))
    findings.sort(key=lambda f: (f.rule_code.value, f.entity_reference or "", f.issue_hash))
    return findings


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _missing_charger_data(
    ctx: ChargerDayContext, cfg: DailyQualitySeverities
) -> Iterable[DailyFinding]:
    if ctx.arrival_status is not ArrivalStatus.MISSING:
        return ()
    ev = ctx.evaluation
    return (
        DailyFinding(
            rule_code=QualityIssueType.MISSING_CHARGER_DATA,
            severity=ctx.severity_of("missing_charger_data", cfg),
            message=(
                f"Charger {ev.charger_id} was expected on {ev.business_date} "
                f"but delivered no usable telemetry."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={"expected": True, "file_count": ev.file_count},
        ),
    )


def _late_file(ctx: ChargerDayContext, cfg: DailyQualitySeverities) -> Iterable[DailyFinding]:
    if ctx.arrival_status is not ArrivalStatus.LATE:
        return ()
    ev = ctx.evaluation
    late_by = ctx.late_by_seconds or 0
    return (
        DailyFinding(
            rule_code=QualityIssueType.LATE_FILE,
            severity=ctx.severity_of("late_file", cfg),
            message=(
                f"Telemetry for {ev.business_date} arrived "
                f"{late_by // 3600}h{(late_by % 3600) // 60:02d}m past the configured cutoff."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={
                "late_by_seconds": late_by,
                "first_received_at": (
                    ev.first_received_at.isoformat() if ev.first_received_at else None
                ),
            },
        ),
    )


def _completeness(ctx: ChargerDayContext, cfg: DailyQualitySeverities) -> Iterable[DailyFinding]:
    """PARTIAL and SEVERELY_INCOMPLETE are distinct from FAILED (section 18).

    A structurally valid file covering only part of the day is an operational
    incompleteness, not a processing failure.
    """
    ev = ctx.evaluation
    status = ev.completeness_status
    if status is CompletenessStatus.PARTIAL:
        code, key = QualityIssueType.PARTIAL_DAY, "partial_day"
    elif status is CompletenessStatus.SEVERELY_INCOMPLETE:
        code, key = QualityIssueType.SEVERELY_INCOMPLETE_DAY, "severely_incomplete_day"
    else:
        return ()
    return (
        DailyFinding(
            rule_code=code,
            severity=ctx.severity_of(key, cfg),
            message=(
                f"Only {ev.coverage_percentage:.2f}% of expected observations present "
                f"({ev.unique_timestamp_count} of {ev.expected_timestamp_count} "
                f"unique event timestamps)."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={
                "coverage_percentage": ev.coverage_percentage,
                "sample_coverage_percentage": ev.sample_coverage_percentage,
                "span_coverage_percentage": ev.span_coverage_percentage,
                "unique_timestamp_count": ev.unique_timestamp_count,
                "expected_timestamp_count": ev.expected_timestamp_count,
            },
        ),
    )


def _telemetry_gap(ctx: ChargerDayContext, cfg: DailyQualitySeverities) -> Iterable[DailyFinding]:
    ev = ctx.evaluation
    floor = _GAP_ORDER.get(_parse_gap_severity(cfg.gap_min_severity), 1)
    reportable = [g for g in ev.gaps if _GAP_ORDER.get(g.severity, 0) >= floor]
    if not reportable:
        return ()
    worst = max(reportable, key=lambda g: g.duration_seconds)
    return (
        DailyFinding(
            rule_code=QualityIssueType.TELEMETRY_GAP,
            severity=ctx.severity_of("telemetry_gap", cfg),
            # Aggregated: one finding for the day carrying the count, never one
            # row per gap. The gap rows themselves live in telemetry_gap.
            occurrence_count=len(reportable),
            message=(
                f"{len(reportable)} reportable telemetry gap(s); "
                f"largest {worst.duration_seconds}s ({worst.severity.value})."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            event_time=worst.start_event_at,
            details={
                "gap_count": len(reportable),
                "largest_gap_seconds": worst.duration_seconds,
                "total_gap_seconds": ev.total_gap_seconds,
                "min_reported_severity": cfg.gap_min_severity,
            },
        ),
    )


def _abnormal_cadence(
    ctx: ChargerDayContext, cfg: DailyQualitySeverities
) -> Iterable[DailyFinding]:
    ev = ctx.evaluation
    if not ev.cadence_is_abnormal or ev.observed_median_interval_seconds is None:
        return ()
    return (
        DailyFinding(
            rule_code=QualityIssueType.ABNORMAL_SAMPLING_INTERVAL,
            severity=ctx.severity_of("abnormal_sampling_interval", cfg),
            message=(
                f"Observed median cadence {ev.observed_median_interval_seconds:.1f}s deviates "
                f"from the expected {ev.expected_sampling_interval_seconds}s."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={
                "observed_median_seconds": ev.observed_median_interval_seconds,
                "observed_p95_seconds": ev.observed_p95_interval_seconds,
                "expected_interval_seconds": ev.expected_sampling_interval_seconds,
            },
        ),
    )


def _missing_topology(
    ctx: ChargerDayContext, cfg: DailyQualitySeverities
) -> Iterable[DailyFinding]:
    """Expected vs observed connectors and SMRs (sections 26, 27).

    This is a *coverage* finding, not a hardware diagnosis. A connector absent
    from a day's telemetry may mean a failure, a configuration change or a source
    defect; Phase 1C reports the discrepancy and does not guess which.
    """
    ev = ctx.evaluation
    out: list[DailyFinding] = []
    if not ev.has_data:
        return out

    for expected, observed, code, key, label in (
        (
            ctx.expected_connectors,
            ev.connectors_detected,
            QualityIssueType.MISSING_EXPECTED_CONNECTOR,
            "missing_expected_connector",
            "connector",
        ),
        (
            ctx.expected_smrs,
            ev.smrs_detected,
            QualityIssueType.MISSING_EXPECTED_SMR,
            "missing_expected_smr",
            "SMR",
        ),
    ):
        if expected is None or len(observed) >= expected:
            continue
        out.append(
            DailyFinding(
                rule_code=code,
                severity=ctx.severity_of(key, cfg),
                occurrence_count=expected - len(observed),
                message=(
                    f"Expected {expected} {label}(s) but observed {len(observed)} "
                    f"({', '.join(sorted(observed)) or 'none'})."
                ),
                charger_id=ev.charger_id,
                business_date=ev.business_date,
                details={
                    "expected_count": expected,
                    "observed_count": len(observed),
                    "observed": sorted(observed),
                },
            )
        )
    return out


def _multiple_files(ctx: ChargerDayContext, cfg: DailyQualitySeverities) -> Iterable[DailyFinding]:
    ev = ctx.evaluation
    if ev.file_count <= 1:
        return ()
    return (
        DailyFinding(
            rule_code=QualityIssueType.MULTIPLE_FILES_SAME_CHARGER_DAY,
            severity=ctx.severity_of("multiple_files_same_charger_day", cfg),
            occurrence_count=ev.file_count,
            message=(
                f"{ev.file_count} files contributed to this charger-day; coverage is their union."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={"file_count": ev.file_count},
        ),
    )


def _overlapping_coverage(
    ctx: ChargerDayContext, cfg: DailyQualitySeverities
) -> Iterable[DailyFinding]:
    ev = ctx.evaluation
    if ev.overlapping_timestamp_count <= 0:
        return ()
    return (
        DailyFinding(
            rule_code=QualityIssueType.OVERLAPPING_FILE_COVERAGE,
            severity=ctx.severity_of("overlapping_file_coverage", cfg),
            occurrence_count=ev.overlapping_timestamp_count,
            message=(
                f"{ev.overlapping_timestamp_count} event timestamp(s) appear in more than one "
                f"file. Quantified here; frame-level resolution is Phase 1D."
            ),
            charger_id=ev.charger_id,
            business_date=ev.business_date,
            details={
                "overlapping_timestamp_count": ev.overlapping_timestamp_count,
                "duplicate_file_count": ev.duplicate_file_count,
            },
        ),
    )


def _filename_mismatch(
    ctx: ChargerDayContext, cfg: DailyQualitySeverities
) -> Iterable[DailyFinding]:
    """Filename date vs event date (section 29).

    Informational/warning by design. The filename is never authoritative and the
    event date is never rewritten to match it.
    """
    ev = ctx.evaluation
    out: list[DailyFinding] = []
    for filename, filename_date in ctx.filename_date_mismatches:
        out.append(
            DailyFinding(
                rule_code=QualityIssueType.EVENT_DATE_FILENAME_MISMATCH,
                severity=ctx.severity_of("event_date_filename_mismatch", cfg),
                message=(
                    f"Filename {filename!r} suggests {filename_date}, but the telemetry's "
                    f"event date is {ev.business_date}. The event date is authoritative."
                ),
                charger_id=ev.charger_id,
                business_date=ev.business_date,
                entity_reference=filename[:128],
                details={
                    "filename": filename,
                    "filename_date": filename_date.isoformat(),
                    "event_business_date": ev.business_date.isoformat(),
                },
            )
        )
    return out


def _parse_gap_severity(raw: str) -> GapSeverity:
    try:
        return GapSeverity(str(raw).upper())
    except ValueError:
        return GapSeverity.MODERATE


_RULES = (
    _missing_charger_data,
    _late_file,
    _completeness,
    _telemetry_gap,
    _abnormal_cadence,
    _missing_topology,
    _multiple_files,
    _overlapping_coverage,
    _filename_mismatch,
)
