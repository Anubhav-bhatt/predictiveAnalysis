"""Coverage, cadence and gap arithmetic (Phase 1C sections 10-15, 45).

These tests pin the numbers, not just the shapes. The single most important one is
``test_duplicate_timestamps_do_not_inflate_coverage``: raw duplication must never
be able to raise a coverage figure, because that is the failure mode that would
make the whole daily report untrustworthy.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pytest

from backend.app.core.config import FleetSettings
from backend.app.models.enums import CompletenessStatus, GapSeverity
from pipelines.ingestion.coverage import (
    CoverageEvaluation,
    CoveragePolicy,
    FileContribution,
    evaluate_charger_day,
    is_late,
)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BUSINESS_DATE = dt.date(2026, 8, 10)


def policy(**overrides: object) -> CoveragePolicy:
    settings = FleetSettings(**overrides)  # type: ignore[arg-type]
    return CoveragePolicy.from_settings(settings, expected_interval_seconds=120)


def stamps(
    count: int, *, start_hour: int = 0, start_minute: int = 0, step: int = 120
) -> list[dt.datetime]:
    base = dt.datetime(2026, 8, 10, start_hour, start_minute, tzinfo=IST)
    return [base + dt.timedelta(seconds=i * step) for i in range(count)]


def evaluate(
    contributions: Iterable[FileContribution], pol: CoveragePolicy | None = None
) -> CoverageEvaluation:
    return evaluate_charger_day(
        charger_id="HYD12",
        business_date=BUSINESS_DATE,
        contributions=list(contributions),
        policy=pol or policy(),
    )


# ---------------------------------------------------------------------------
# Expected sample count and complete days
# ---------------------------------------------------------------------------


def test_expected_timestamp_count_is_day_over_interval() -> None:
    result = evaluate([FileContribution(None, stamps(1))])
    assert result.expected_timestamp_count == 86_400 // 120 == 720


def test_full_day_is_complete() -> None:
    result = evaluate([FileContribution(None, stamps(720))])
    assert result.unique_timestamp_count == 720
    assert result.sample_coverage_percentage == pytest.approx(100.0)
    assert result.completeness_status is CompletenessStatus.COMPLETE
    assert result.gap_count == 0


def test_partial_day_records_partial_not_failed() -> None:
    """A structurally valid file covering part of the day is PARTIAL (section 18).

    PARTIAL is a *band*, not "anything short of complete": with the default
    thresholds it spans 50-95% sample coverage.
    """
    result = evaluate([FileContribution(None, stamps(400))])  # ~13h20m
    assert result.completeness_status is CompletenessStatus.PARTIAL
    assert 55.0 < result.sample_coverage_percentage < 56.0


def test_short_partial_day_is_incomplete_but_never_failed() -> None:
    """Section 18's 00:00-05:30 example, measured honestly.

    5.5 hours is ~23% of a day, which under the *default* configuration lands in
    SEVERELY_INCOMPLETE rather than PARTIAL. The distinction section 18 actually
    insists on is preserved either way: this is an operational completeness
    verdict, never a processing failure. Which band it falls in is configuration.
    """
    result = evaluate([FileContribution(None, stamps(166))])  # 00:00 -> ~05:32
    assert result.completeness_status is CompletenessStatus.SEVERELY_INCOMPLETE
    assert 22.0 < result.sample_coverage_percentage < 24.0

    # Widen the partial band and the same day reads as PARTIAL - proving the
    # verdict is threshold-driven, not hard-coded.
    lenient = evaluate(
        [FileContribution(None, stamps(166))], policy(completeness_partial_min_pct=20.0)
    )
    assert lenient.completeness_status is CompletenessStatus.PARTIAL


def test_severely_incomplete_day() -> None:
    result = evaluate([FileContribution(None, stamps(30))])
    assert result.completeness_status is CompletenessStatus.SEVERELY_INCOMPLETE


def test_no_data_day() -> None:
    result = evaluate([])
    assert result.completeness_status is CompletenessStatus.NO_DATA
    assert result.unique_timestamp_count == 0
    assert result.coverage_percentage == 0.0
    assert result.has_data is False


def test_completeness_thresholds_are_configurable() -> None:
    """Section 6: thresholds live in configuration, never inline."""
    strict = policy(completeness_complete_min_pct=99.9, completeness_partial_min_pct=90.0)
    result = evaluate([FileContribution(None, stamps(700))], strict)
    assert result.sample_coverage_percentage == pytest.approx(97.222, abs=0.001)
    assert result.completeness_status is CompletenessStatus.PARTIAL


# ---------------------------------------------------------------------------
# The critical rule: raw duplication must not inflate coverage (section 11)
# ---------------------------------------------------------------------------


def test_duplicate_timestamps_do_not_inflate_coverage() -> None:
    half_day = stamps(360)
    # The same timestamps presented eight times over - the 2x4 raw grain.
    replayed = FileContribution(None, half_day * 8)
    result = evaluate([replayed])

    assert result.unique_timestamp_count == 360, "coverage must count unique stamps only"
    assert result.sample_coverage_percentage == pytest.approx(50.0)
    assert result.sample_coverage_percentage <= 100.0


def test_coverage_never_exceeds_one_hundred_percent() -> None:
    """Even a wildly over-sampled day is capped, so a ratio cannot mislead."""
    result = evaluate([FileContribution(None, stamps(5000, step=10))])
    assert result.sample_coverage_percentage == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Span vs sample coverage (section 12)
# ---------------------------------------------------------------------------


def test_span_coverage_alone_would_be_misleading() -> None:
    """00:01 to 23:59 with an empty middle: high span, low sample."""
    edges = [
        dt.datetime(2026, 8, 10, 0, 1, tzinfo=IST),
        dt.datetime(2026, 8, 10, 0, 3, tzinfo=IST),
        dt.datetime(2026, 8, 10, 23, 57, tzinfo=IST),
        dt.datetime(2026, 8, 10, 23, 59, tzinfo=IST),
    ]
    result = evaluate([FileContribution(None, edges)])

    assert result.span_coverage_percentage > 99.0
    assert result.sample_coverage_percentage < 1.0
    # The headline number is the honest one.
    assert result.coverage_percentage == result.sample_coverage_percentage
    assert result.gap_adjusted_coverage_percentage < 5.0


# ---------------------------------------------------------------------------
# Cadence (section 10)
# ---------------------------------------------------------------------------


def test_median_cadence_matches_the_known_sample() -> None:
    result = evaluate([FileContribution(None, stamps(100, step=121))])
    assert result.observed_median_interval_seconds == pytest.approx(121.0)
    assert result.cadence_is_abnormal is False


def test_cadence_ignores_duplicate_timestamps() -> None:
    """Duplicates would otherwise inject 0-second intervals and skew the median."""
    base = stamps(50, step=121)
    result = evaluate([FileContribution(None, base + base)])
    assert result.observed_median_interval_seconds == pytest.approx(121.0)


def test_abnormal_cadence_is_flagged() -> None:
    result = evaluate([FileContribution(None, stamps(100, step=600))])
    assert result.cadence_is_abnormal is True
    assert result.observed_median_interval_seconds == pytest.approx(600.0)


def test_cadence_interval_percentiles() -> None:
    series = stamps(20, step=120)
    series.append(series[-1] + dt.timedelta(seconds=900))
    result = evaluate([FileContribution(None, series)])
    assert result.observed_min_interval_seconds == pytest.approx(120.0)
    assert result.observed_max_interval_seconds == pytest.approx(900.0)


# ---------------------------------------------------------------------------
# Gap detection and tolerance (sections 14, 15)
# ---------------------------------------------------------------------------


def test_gap_requires_tolerance_not_exact_interval() -> None:
    """2,2,2,10 minutes: only the 10-minute hole is a gap (section 14)."""
    series = [dt.datetime(2026, 8, 10, 6, 0, tzinfo=IST)]
    for minutes in (2, 2, 2, 10):
        series.append(series[-1] + dt.timedelta(minutes=minutes))

    result = evaluate([FileContribution(None, series)])
    assert result.gap_count == 1
    assert result.largest_gap_seconds == 600


def test_normal_cadence_jitter_is_not_a_gap() -> None:
    series = stamps(40, step=121)
    result = evaluate([FileContribution(None, series)])
    assert result.gap_count == 0


def test_gap_multiplier_is_configuration_driven() -> None:
    """expected 120s x multiplier: the same data yields different gap counts."""
    series = [dt.datetime(2026, 8, 10, 6, 0, tzinfo=IST)]
    for seconds in (120, 300, 120):
        series.append(series[-1] + dt.timedelta(seconds=seconds))

    lenient = evaluate([FileContribution(None, series)], policy(gap_threshold_multiplier=3.0))
    strict = evaluate([FileContribution(None, series)], policy(gap_threshold_multiplier=1.5))

    assert lenient.gap_count == 0, "300s <= 360s threshold"
    assert strict.gap_count == 1, "300s > 180s threshold"


def test_gap_severity_bands_are_configurable() -> None:
    def gap_of(minutes: int, pol: CoveragePolicy) -> GapSeverity:
        series = [
            dt.datetime(2026, 8, 10, 6, 0, tzinfo=IST),
            dt.datetime(2026, 8, 10, 6, 0, tzinfo=IST) + dt.timedelta(minutes=minutes),
        ]
        result = evaluate([FileContribution(None, series)], pol)
        assert result.gap_count == 1
        return GapSeverity(result.gaps[0].severity)

    default = policy()
    assert gap_of(10, default) is GapSeverity.MINOR
    assert gap_of(45, default) is GapSeverity.MODERATE
    assert gap_of(180, default) is GapSeverity.MAJOR
    assert gap_of(400, default) is GapSeverity.CRITICAL

    # Re-band and the very same 10-minute gap is classified differently: 600s now
    # meets the MAJOR floor exactly. Nothing about the bands is hard-coded.
    shifted = policy(gap_moderate_seconds=300, gap_major_seconds=600, gap_critical_seconds=900)
    assert gap_of(10, shifted) is GapSeverity.MAJOR
    # 7 minutes, not 6: a 360s interval only equals the detection threshold, and
    # detection requires exceeding it.
    assert gap_of(7, shifted) is GapSeverity.MODERATE
    assert gap_of(20, shifted) is GapSeverity.CRITICAL


def test_gap_estimates_missing_samples() -> None:
    series = [
        dt.datetime(2026, 8, 10, 6, 0, tzinfo=IST),
        dt.datetime(2026, 8, 10, 6, 20, tzinfo=IST),
    ]
    result = evaluate([FileContribution(None, series)])
    # 1200s at a 120s cadence: 10 slots, 9 of them missing observations.
    assert result.gaps[0].estimated_missing_samples == 9


def test_leading_and_trailing_time_is_not_a_gap() -> None:
    """Absent telemetry before the first sample is not an inter-sample gap."""
    series = stamps(10, start_hour=12)
    result = evaluate([FileContribution(None, series)])
    assert result.gap_count == 0
    assert result.leading_missing_seconds > 0
    assert result.trailing_missing_seconds > 0


# ---------------------------------------------------------------------------
# Multiple files per charger-day (sections 19, 20)
# ---------------------------------------------------------------------------


def test_two_files_combine_into_one_complete_day() -> None:
    """file completeness != charger-day completeness (section 19)."""
    morning = FileContribution(None, stamps(360))
    afternoon = FileContribution(None, stamps(360, start_hour=12))

    combined = evaluate([morning, afternoon])
    assert combined.file_count == 2
    assert combined.unique_timestamp_count == 720
    assert combined.completeness_status is CompletenessStatus.COMPLETE

    alone = evaluate([morning])
    assert alone.completeness_status is CompletenessStatus.PARTIAL


def test_overlapping_files_are_quantified_not_discarded() -> None:
    """Section 20: overlap is measured; resolution belongs to Phase 1D."""
    first = FileContribution(None, stamps(360))
    second = FileContribution(None, stamps(360, start_hour=6))  # 6h of overlap

    result = evaluate([first, second])
    assert result.overlapping_timestamp_count > 0
    assert result.unique_timestamp_count == 540


def test_timestamps_outside_the_business_date_are_excluded() -> None:
    """A cross-midnight file contributes only its in-range stamps to this date."""
    inside = stamps(10)
    outside = [dt.datetime(2026, 8, 11, 0, 30, tzinfo=IST)]
    result = evaluate([FileContribution(None, inside + outside)])
    assert result.unique_timestamp_count == 10


def test_primary_file_is_the_largest_contributor() -> None:
    from uuid import uuid4

    small, big = uuid4(), uuid4()
    result = evaluate(
        [
            FileContribution(small, stamps(10)),
            FileContribution(big, stamps(200, start_hour=6)),
        ]
    )
    assert result.primary_telemetry_file_id == big


# ---------------------------------------------------------------------------
# Topology (sections 26, 27)
# ---------------------------------------------------------------------------


def test_connectors_and_smrs_are_unioned_across_files() -> None:
    a = FileContribution(None, stamps(10), connectors=frozenset({"1"}), smrs=frozenset({"1", "2"}))
    b = FileContribution(
        None, stamps(10, start_hour=6), connectors=frozenset({"2"}), smrs=frozenset({"3"})
    )
    result = evaluate([a, b])
    assert result.connectors_detected == frozenset({"1", "2"})
    assert result.smrs_detected == frozenset({"1", "2", "3"})


def test_connector_identity_is_not_assumed_numeric() -> None:
    """Section 26: the source contract does not guarantee numeric ids."""
    result = evaluate(
        [FileContribution(None, stamps(5), connectors=frozenset({"GUN-A", "GUN-B"}))]
    )
    assert result.connectors_detected == frozenset({"GUN-A", "GUN-B"})


# ---------------------------------------------------------------------------
# Late arrival (section 17)
# ---------------------------------------------------------------------------


def test_late_is_measured_from_receipt_not_processing() -> None:
    pol = policy(late_arrival_grace_hours=24)
    on_time = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.UTC)
    late = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.UTC)

    assert is_late(business_date=BUSINESS_DATE, first_received_at=on_time, policy=pol)[0] is False
    is_late_flag, late_by = is_late(
        business_date=BUSINESS_DATE, first_received_at=late, policy=pol
    )
    assert is_late_flag is True
    assert late_by is not None and late_by > 0


def test_unknown_receipt_time_is_not_called_late() -> None:
    flag, late_by = is_late(business_date=BUSINESS_DATE, first_received_at=None, policy=policy())
    assert flag is False
    assert late_by is None


def test_grace_period_is_configurable() -> None:
    received = dt.datetime(2026, 8, 12, 6, 0, tzinfo=dt.UTC)
    generous = is_late(
        business_date=BUSINESS_DATE,
        first_received_at=received,
        policy=policy(late_arrival_grace_hours=72),
    )
    tight = is_late(
        business_date=BUSINESS_DATE,
        first_received_at=received,
        policy=policy(late_arrival_grace_hours=1),
    )
    assert generous[0] is False
    assert tight[0] is True


# ---------------------------------------------------------------------------
# Timezone policy (section 9)
# ---------------------------------------------------------------------------


def test_business_date_boundaries_use_the_source_timezone() -> None:
    """A charger's day is its own local day, not a UTC day."""
    just_after_local_midnight = dt.datetime(2026, 8, 10, 0, 5, tzinfo=IST)
    result = evaluate([FileContribution(None, [just_after_local_midnight])])
    assert result.unique_timestamp_count == 1
    assert result.detail["source_timezone"] == "Asia/Kolkata"


def test_utc_timezone_shifts_the_day_window() -> None:
    """The same instant belongs to a different day window under a different tz."""
    pol = CoveragePolicy.from_settings(
        FleetSettings(default_source_timezone="UTC"), expected_interval_seconds=120
    )
    early_ist = dt.datetime(2026, 8, 10, 2, 0, tzinfo=IST)  # 2026-08-09 20:30 UTC
    result = evaluate([FileContribution(None, [early_ist])], pol)
    assert result.unique_timestamp_count == 0
