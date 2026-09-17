"""Fleet coverage metrics and operational counters (Phase 1C sections 39, 48).

Every rate here has a stated denominator, because that is where fleet metrics
usually go wrong.  The rule applied throughout:

    Delivery and completeness rates are measured against **expected**
    charger-days, and a missing charger counts as 0% - it is never excluded.

Excluding missing chargers would let a fleet that lost half its estate report
99% coverage, which is precisely the failure this phase exists to prevent.
``UNEXPECTED`` charger-days (telemetry from a charger not in the registry) are
excluded from the denominator instead, since they are not part of what the fleet
was measured against - they are reported as their own count.

Percentiles are computed in Python from an ordered list rather than with a
dialect-specific SQL percentile function, so PostgreSQL and SQLite agree. No
Prometheus client is introduced: section 48 asks for the internal abstraction
only.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.enums import ArrivalStatus, CompletenessStatus
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository

__all__ = ["DailyFleetMetrics", "MetricsService", "percentile"]


def percentile(ordered: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile over an already-sorted list.

    Nearest-rank (rather than interpolated) is chosen deliberately: every reported
    percentile is then an actually-observed value, which matters when the number
    is going to be quoted in an operational review.
    """
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(float(ordered[0]), 3)
    index = int(round(fraction * (len(ordered) - 1)))
    index = max(0, min(len(ordered) - 1, index))
    return round(float(ordered[index]), 3)


@dataclass(slots=True)
class DailyFleetMetrics:
    """The section 39 metric set for one business date."""

    business_date: dt.date

    expected_chargers: int = 0
    received_chargers: int = 0
    complete: int = 0
    partial: int = 0
    severely_incomplete: int = 0
    no_data: int = 0
    missing: int = 0
    late: int = 0
    unexpected: int = 0

    files_ready: int = 0
    files_partial: int = 0
    files_duplicate: int = 0
    files_failed: int = 0
    files_quarantined: int = 0

    #: received / expected
    fleet_delivery_rate: float = 0.0
    #: COMPLETE / expected
    fleet_complete_day_rate: float = 0.0
    fleet_missing_rate: float = 0.0
    fleet_partial_rate: float = 0.0
    late_arrival_rate: float = 0.0

    #: Mean coverage over expected charger-days; missing counted as 0%.
    fleet_coverage_percentage: float = 0.0
    average_coverage_percentage: float = 0.0
    p50_coverage_percentage: float | None = None
    p95_coverage_percentage: float | None = None
    p95_largest_gap_seconds: int | None = None

    total_gap_count: int = 0
    total_unique_timestamps: int = 0
    largest_gap_seconds: int = 0

    daily_rule_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["business_date"] = self.business_date.isoformat()
        return payload


class MetricsService:
    def __init__(
        self,
        fleet_repo: FleetRepository,
        file_repo: TelemetryFileRepository,
        run_repo: IngestionRunRepository,
        quality_repo: QualityRepository,
        settings: Settings,
    ) -> None:
        self._fleet = fleet_repo
        self._files = file_repo
        self._runs = run_repo
        self._quality = quality_repo
        self._settings = settings

    async def daily(self, business_date: dt.date) -> DailyFleetMetrics:
        """Aggregate one business date. Every count comes from SQL, not Python loops."""
        summary = await self._fleet.daily_summary(business_date)
        arrival = summary["arrival"]
        completeness = summary["completeness"]

        coverage_values = await self._fleet.coverage_distribution(business_date)
        gap_values = await self._fleet.largest_gap_distribution(business_date)
        rule_counts = await self._quality.charger_day_rule_counts(business_date)

        metrics = DailyFleetMetrics(business_date=business_date)

        metrics.missing = int(arrival.get(ArrivalStatus.MISSING.value, 0))
        metrics.late = int(arrival.get(ArrivalStatus.LATE.value, 0))
        metrics.unexpected = int(arrival.get(ArrivalStatus.UNEXPECTED.value, 0))
        received_plain = int(arrival.get(ArrivalStatus.RECEIVED.value, 0))
        metrics.received_chargers = received_plain + metrics.late

        # Expected = every charger-day this fleet was measured against. Rows
        # flagged UNEXPECTED are not part of that denominator.
        metrics.expected_chargers = int(summary["total_charger_days"]) - metrics.unexpected

        metrics.complete = int(completeness.get(CompletenessStatus.COMPLETE.value, 0))
        metrics.partial = int(completeness.get(CompletenessStatus.PARTIAL.value, 0))
        metrics.severely_incomplete = int(
            completeness.get(CompletenessStatus.SEVERELY_INCOMPLETE.value, 0)
        )
        metrics.no_data = int(completeness.get(CompletenessStatus.NO_DATA.value, 0))

        file_counts = await self._files.counts_by_status()
        metrics.files_ready = int(file_counts.get("READY_FOR_NORMALIZATION", 0)) + int(
            file_counts.get("COMPLETED", 0)
        )
        metrics.files_partial = int(file_counts.get("PARTIAL", 0))
        metrics.files_duplicate = int(file_counts.get("DUPLICATE", 0))
        metrics.files_failed = int(file_counts.get("FAILED", 0))
        metrics.files_quarantined = int(file_counts.get("QUARANTINED", 0))

        expected = metrics.expected_chargers
        metrics.fleet_delivery_rate = _rate(metrics.received_chargers, expected)
        metrics.fleet_complete_day_rate = _rate(metrics.complete, expected)
        metrics.fleet_missing_rate = _rate(metrics.missing, expected)
        metrics.fleet_partial_rate = _rate(metrics.partial, expected)
        # Denominator is chargers that actually delivered - lateness is only
        # meaningful for telemetry that arrived at all.
        metrics.late_arrival_rate = _rate(metrics.late, metrics.received_chargers)

        # Missing charger-days hold coverage 0 and are included here by design.
        metrics.fleet_coverage_percentage = (
            round(sum(coverage_values) / len(coverage_values), 3) if coverage_values else 0.0
        )
        metrics.average_coverage_percentage = float(summary["average_coverage_percentage"] or 0.0)
        metrics.p50_coverage_percentage = percentile(coverage_values, 0.50)
        metrics.p95_coverage_percentage = percentile(coverage_values, 0.95)

        p95_gap = percentile([float(v) for v in gap_values], 0.95)
        metrics.p95_largest_gap_seconds = int(p95_gap) if p95_gap is not None else None

        metrics.total_gap_count = int(summary["total_gap_count"])
        metrics.largest_gap_seconds = int(summary["largest_gap_seconds"])
        metrics.daily_rule_counts = rule_counts

        return metrics

    async def counters(self, business_date: dt.date) -> dict[str, int | float]:
        """Flat counter/gauge view (section 48).

        Deliberately a plain mapping rather than a Prometheus registry: the
        contract asks for the internal abstraction, and no metrics infrastructure
        exists in the project yet to hang exporters off.
        """
        metrics = await self.daily(business_date)
        return {
            "files_ready": metrics.files_ready,
            "files_partial": metrics.files_partial,
            "files_duplicate": metrics.files_duplicate,
            "files_failed": metrics.files_failed,
            "files_quarantined": metrics.files_quarantined,
            "chargers_expected": metrics.expected_chargers,
            "chargers_received": metrics.received_chargers,
            "chargers_missing": metrics.missing,
            "chargers_partial": metrics.partial,
            "late_files": metrics.late,
            "gap_count": metrics.total_gap_count,
            "average_daily_coverage": metrics.fleet_coverage_percentage,
        }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 3)
