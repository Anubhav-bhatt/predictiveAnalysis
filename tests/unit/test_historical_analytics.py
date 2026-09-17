"""Unit tests for Phase 7 Historical Continuity analytical engines."""

from __future__ import annotations

import datetime as dt

import pytest

from pipelines.historical.counter_analyzer import (
    CounterAnalyzer,
    CounterTransitionType,
)
from pipelines.historical.eligibility_evaluator import (
    PatternResearchEligibilityEvaluator,
)
from pipelines.historical.gap_detector import GapDetector
from pipelines.historical.sampling_analyzer import SamplingAnalyzer
from pipelines.historical.topology_tracker import TopologyTracker


def test_sampling_analyzer_empty() -> None:
    analyzer = SamplingAnalyzer()
    profile = analyzer.analyze([])
    assert profile.observation_count == 0
    assert profile.distinct_timestamps == 0
    assert profile.first_event_time is None
    assert profile.median_interval_seconds is None


def test_sampling_analyzer_single_observation() -> None:
    analyzer = SamplingAnalyzer()
    t = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)
    profile = analyzer.analyze([t])
    assert profile.observation_count == 1
    assert profile.distinct_timestamps == 1
    assert profile.coverage_duration_seconds == 0.0
    assert profile.median_interval_seconds is None
    assert profile.expected_interval_seconds is None


def test_sampling_analyzer_same_second_frames() -> None:
    analyzer = SamplingAnalyzer()
    t = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)
    # Three frames at exact same second
    profile = analyzer.analyze([t, t, t], frame_sequences=[0, 1, 2])
    assert profile.observation_count == 3
    assert profile.distinct_timestamps == 1
    assert profile.same_second_frame_count == 2
    assert profile.median_interval_seconds is None


def test_sampling_analyzer_regular_cadence_with_jitter() -> None:
    analyzer = SamplingAnalyzer()
    base = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)
    # 120s, 119s, 121s, 120s, 120s, 120s
    times = [
        base,
        base + dt.timedelta(seconds=120),
        base + dt.timedelta(seconds=239),
        base + dt.timedelta(seconds=360),
        base + dt.timedelta(seconds=480),
        base + dt.timedelta(seconds=600),
    ]
    profile = analyzer.analyze(times)
    assert profile.observation_count == 6
    assert profile.distinct_timestamps == 6
    assert profile.median_interval_seconds == 120.0
    assert profile.expected_interval_seconds == 120.0
    assert profile.min_interval_seconds == 119.0
    assert profile.max_interval_seconds == 121.0
    assert profile.coverage_duration_seconds == 600.0


def test_gap_detector_finds_unobserved_period() -> None:
    analyzer = SamplingAnalyzer()
    detector = GapDetector(gap_multiplier=2.5, min_gap_seconds=180.0, sampling_analyzer=analyzer)
    base = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)

    # 10:00, 10:02, 10:04, 10:06 -> gap -> 10:40 (34 min gap)
    times = [
        base,
        base + dt.timedelta(minutes=2),
        base + dt.timedelta(minutes=4),
        base + dt.timedelta(minutes=6),
        base + dt.timedelta(minutes=40),
    ]

    gaps = detector.detect_gaps("CH_001", times)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.charger_id == "CH_001"
    assert gap.gap_start == base + dt.timedelta(minutes=6)
    assert gap.gap_end == base + dt.timedelta(minutes=40)
    assert gap.gap_duration_seconds == 34 * 60  # 2040.0s
    assert gap.expected_interval_seconds == 120.0
    assert gap.gap_multiple == pytest.approx(17.0, 0.1)


def test_gap_detector_no_gaps_on_continuous_telemetry() -> None:
    detector = GapDetector()
    base = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)
    times = [base + dt.timedelta(minutes=2 * i) for i in range(10)]
    gaps = detector.detect_gaps("CH_001", times)
    assert len(gaps) == 0


def test_counter_analyzer_monotonic_and_reset_candidate() -> None:
    analyzer = CounterAnalyzer()
    base = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)

    # Values: 100, 105, 111, 118, 3, 8
    raw_vals = [100.0, 105.0, 111.0, 118.0, 3.0, 8.0]
    observations = [
        {"event_time": base + dt.timedelta(minutes=i), "frame_sequence": 0, "value": v}
        for i, v in enumerate(raw_vals)
    ]

    report = analyzer.analyze("CH_001", "total_kwh_delivered", observations)
    assert report.total_observations == 6
    assert report.non_null_observations == 6
    assert report.first_value == 100.0
    assert report.last_value == 8.0
    assert report.increase_count == 4  # 105, 111, 118, and 8
    assert report.decrease_count == 1  # 3.0
    assert report.reset_candidate_count == 1  # 3.0 is a reset candidate (dropped from 118 to 3)

    reset_transitions = [
        t for t in report.transitions if t.transition_type == CounterTransitionType.RESET_CANDIDATE
    ]
    reset_transition = reset_transitions[0]
    assert reset_transition.current_value == 3.0
    assert reset_transition.previous_value == 118.0
    assert reset_transition.delta == -115.0


def test_topology_tracker_presence_intervals() -> None:
    tracker = TopologyTracker()
    day1 = dt.datetime(2026, 9, 10, 10, 0, tzinfo=dt.UTC)
    day2 = dt.datetime(2026, 9, 11, 10, 0, tzinfo=dt.UTC)
    day3 = dt.datetime(2026, 9, 12, 10, 0, tzinfo=dt.UTC)
    day4 = dt.datetime(2026, 9, 13, 10, 0, tzinfo=dt.UTC)

    # SMR 1 seen on Days 1-4
    # SMR 5 seen only starting on Day 4
    observations = [
        (1, day1),
        (1, day2),
        (1, day3),
        (1, day4),
        (5, day4),
    ]

    presence = tracker.track_presence("smr", observations)
    assert 1 in presence
    assert 5 in presence

    p1 = presence[1]
    assert p1.first_seen == day1
    assert p1.last_seen == day4
    assert p1.active_days_count == 4

    p5 = presence[5]
    assert p5.first_seen == day4
    assert p5.last_seen == day4
    assert p5.active_days_count == 1
    assert p5.observation_count == 1


def test_pattern_research_eligibility_snapshot_honesty() -> None:
    evaluator = PatternResearchEligibilityEvaluator()
    analyzer = SamplingAnalyzer()

    # 1 single observation
    single_time = [dt.datetime(2026, 9, 16, 17, 6, 1, tzinfo=dt.UTC)]
    profile = analyzer.analyze(single_time)
    eligibility = evaluator.evaluate("CH_SNAPSHOT", profile, gaps=[])

    assert eligibility.pattern_research_ready is False
    assert "Only 1 historical observation is available" in eligibility.reason
    assert eligibility.observation_count == 1


def test_pattern_research_eligibility_multi_day_pass() -> None:
    evaluator = PatternResearchEligibilityEvaluator()
    analyzer = SamplingAnalyzer()
    base = dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC)

    # 7 days, 20 observations per day = 140 observations, regular 1 hour intervals
    times = [base + dt.timedelta(hours=i) for i in range(140)]
    profile = analyzer.analyze(times)
    eligibility = evaluator.evaluate("CH_SYNTHETIC", profile, gaps=[], active_days=7)

    assert eligibility.pattern_research_ready is True
    assert "Sufficient historical depth" in eligibility.reason
    assert eligibility.history_days == 7
    assert eligibility.observation_count == 140
