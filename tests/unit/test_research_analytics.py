"""Unit tests for Phase 9 Scientific Pattern Discovery & Analytical Datasets."""

from __future__ import annotations

import datetime as dt

from backend.app.models.enums import (
    AnalyticalGrain,
    PatternCategory,
    PatternEvidenceLevel,
)
from pipelines.research.dataset_builder import ResearchDatasetBuilder
from pipelines.research.fleet_profiler import FleetProfiler
from pipelines.research.pattern_scanner import PatternScanner
from pipelines.research.signal_statistician import SignalStatistician


class TestSignalStatistician:
    """Tests for pure descriptive statistics and correlation engine."""

    def test_empty_values(self) -> None:
        stat = SignalStatistician()
        res = stat.compute_statistics("grid_voltage", [])
        assert res.count == 0
        assert res.non_null_count == 0
        assert res.null_count == 0
        assert res.mean is None
        assert res.std is None
        assert res.min_val is None
        assert res.max_val is None
        assert res.missing_rate == 0.0

    def test_all_nulls_and_nans(self) -> None:
        stat = SignalStatistician()
        res = stat.compute_statistics("grid_voltage", [None, float("nan"), None, "invalid"])
        assert res.count == 4
        assert res.non_null_count == 0
        assert res.null_count == 4
        assert res.missing_rate == 1.0
        assert res.mean is None

    def test_sentinels_excluded_from_numeric_aggregations(self) -> None:
        stat = SignalStatistician()
        # 230.0, 232.0, 228.0, and sentinels: -1.0, -9999.0, 65535.0
        vals = [230.0, 232.0, 228.0, -1.0, -9999.0, 65535.0]
        res = stat.compute_statistics("ac_voltage_l1", vals)
        assert res.count == 6
        assert res.non_null_count == 3
        assert res.sentinel_count == 3
        assert res.min_val == 228.0
        assert res.max_val == 232.0
        assert res.mean == 230.0
        assert res.p50 == 230.0
        assert res.missing_rate == 0.5  # 3 invalid / 6 total

    def test_normal_distribution_statistics(self) -> None:
        stat = SignalStatistician()
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        res = stat.compute_statistics("test_signal", vals)
        assert res.count == 5
        assert res.non_null_count == 5
        assert res.null_count == 0
        assert res.sentinel_count == 0
        assert res.mean == 30.0
        assert res.min_val == 10.0
        assert res.max_val == 50.0
        assert res.p50 == 30.0
        assert res.missing_rate == 0.0
        assert res.std is not None and res.std > 0

    def test_correlations_perfect_positive_and_negative(self) -> None:
        stat = SignalStatistician()
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y_pos = [2.0, 4.0, 6.0, 8.0, 10.0]
        y_neg = [10.0, 8.0, 6.0, 4.0, 2.0]

        pos_corr = stat.compute_correlation("x", x, "y_pos", y_pos)
        assert pos_corr.pearson_r is not None
        assert round(pos_corr.pearson_r, 4) == 1.0
        assert pos_corr.spearman_rho is not None
        assert round(pos_corr.spearman_rho, 4) == 1.0

        neg_corr = stat.compute_correlation("x", x, "y_neg", y_neg)
        assert neg_corr.pearson_r is not None
        assert round(neg_corr.pearson_r, 4) == -1.0
        assert neg_corr.spearman_rho is not None
        assert round(neg_corr.spearman_rho, 4) == -1.0

    def test_correlations_with_sentinels_and_nones(self) -> None:
        stat = SignalStatistician()
        x = [1.0, 2.0, None, 4.0, 5.0, -1.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0]

        res = stat.compute_correlation("x", x, "y", y)
        assert res.sample_count == 4  # 1st, 2nd, 4th, 5th pairs valid
        assert res.pearson_r is not None
        assert round(res.pearson_r, 4) == 1.0

    def test_correlations_insufficient_samples(self) -> None:
        stat = SignalStatistician()
        x = [1.0, 2.0]
        y = [2.0, 4.0]
        res = stat.compute_correlation("x", x, "y", y)
        assert res.sample_count == 2
        assert res.pearson_r is None


class TestPatternScanner:
    """Tests for domain pattern scanning and graduated evidence scoring."""

    def test_voltage_low_anomaly_detection(self) -> None:
        scanner = PatternScanner()
        stat = SignalStatistician()
        # Low voltage below 200V
        vals = [185.0, 188.0, 190.0, 187.0]
        v_stat = stat.compute_statistics("grid_voltage", vals)

        res = scanner.scan("CH_01", signal_stats=[v_stat])
        volt_patterns = [
            c for c in res.candidates if c.pattern_category == PatternCategory.VOLTAGE_ANOMALY
        ]
        assert len(volt_patterns) >= 1
        pat = volt_patterns[0]
        assert "grid_voltage" in pat.title
        assert pat.confidence_score >= 0.3
        assert pat.evidence_level in (
            PatternEvidenceLevel.OBSERVATION,
            PatternEvidenceLevel.WEAK_CANDIDATE,
            PatternEvidenceLevel.MODERATE_CANDIDATE,
            PatternEvidenceLevel.STRONG_CANDIDATE,
            PatternEvidenceLevel.CONFIRMED_PRECURSOR,
        )

    def test_current_imbalance_detection(self) -> None:
        scanner = PatternScanner(current_imbalance_threshold=0.2)
        stat = SignalStatistician()
        # L1 has 50A, L2 has 52A, L3 has only 20A (severe imbalance)
        l1 = stat.compute_statistics("input_current_l1", [50.0, 50.0, 50.0])
        l2 = stat.compute_statistics("input_current_l2", [52.0, 52.0, 52.0])
        l3 = stat.compute_statistics("input_current_l3", [20.0, 20.0, 20.0])

        res = scanner.scan("CH_01", signal_stats=[l1, l2, l3])
        imbalance_patterns = [
            c for c in res.candidates if c.pattern_category == PatternCategory.CURRENT_IMBALANCE
        ]
        assert len(imbalance_patterns) == 1
        pat = imbalance_patterns[0]
        assert "imbalance" in pat.title.lower()
        assert pat.confidence_score >= 0.5

    def test_alarm_clustering_detection(self) -> None:
        scanner = PatternScanner(alarm_cluster_window_seconds=3600.0, alarm_cluster_min_count=3)
        t0 = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)
        alarms = [
            {"alarm_code": "ERR_TEMP", "start_time": t0, "end_time": t0 + dt.timedelta(minutes=5)},
            {
                "alarm_code": "ERR_VOLT",
                "start_time": t0 + dt.timedelta(minutes=10),
                "end_time": None,
            },
            {
                "alarm_code": "ERR_COMM",
                "start_time": t0 + dt.timedelta(minutes=25),
                "end_time": None,
            },
        ]

        res = scanner.scan("CH_01", alarm_events=alarms)
        cluster_patterns = [
            c for c in res.candidates if c.pattern_category == PatternCategory.ALARM_CLUSTERING
        ]
        assert len(cluster_patterns) >= 1
        pat = cluster_patterns[0]
        assert pat.confidence_score >= 0.5

    def test_session_degradation_detection(self) -> None:
        scanner = PatternScanner()
        sessions = [
            {
                "session_id": "s1",
                "termination_class": "FAULT",
                "energy_delivered_kwh": 0.0,
                "duration_seconds": 120,
            },
            {
                "session_id": "s2",
                "termination_class": "EMERGENCY_STOP",
                "energy_delivered_kwh": 0.0,
                "duration_seconds": 60,
            },
            {
                "session_id": "s3",
                "termination_class": "TIMEOUT",
                "energy_delivered_kwh": 0.0,
                "duration_seconds": 150,
            },
        ]

        res = scanner.scan("CH_01", session_features=sessions)
        deg_patterns = [
            c for c in res.candidates if c.pattern_category == PatternCategory.SESSION_DEGRADATION
        ]
        assert len(deg_patterns) >= 1
        pat = deg_patterns[0]
        assert "degradation" in pat.title.lower()


class TestAnalyticalDatasetBuilder:
    """Tests for pure dataset construction and gap-aware record generation."""

    def test_build_charger_time_dataset_empty(self) -> None:
        builder = ResearchDatasetBuilder()
        ds = builder.build_charger_time_dataset("CH_01", [])
        assert ds.metadata.grain == AnalyticalGrain.CHARGER_TIME
        assert ds.metadata.record_count == 0
        assert len(ds.records) == 0

    def test_build_charger_time_dataset_with_observations(self) -> None:
        builder = ResearchDatasetBuilder()
        t0 = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)
        obs = [
            {"event_time": t0, "voltage": 230.0, "current": 10.0, "temp": 35.0},
            {
                "event_time": t0 + dt.timedelta(minutes=1),
                "voltage": 231.0,
                "current": 12.0,
                "temp": 36.0,
            },
            {
                "event_time": t0 + dt.timedelta(minutes=2),
                "voltage": 229.0,
                "current": 11.0,
                "temp": 37.0,
            },
        ]
        # Gap inside the observation window (between 0m and 2m)
        gap_intervals = [(t0 + dt.timedelta(seconds=30), t0 + dt.timedelta(seconds=90))]

        ds = builder.build_charger_time_dataset("CH_01", obs, gap_intervals=gap_intervals)
        assert ds.metadata.record_count == 1
        assert ds.metadata.gap_count == 1
        assert len(ds.records) == 1
        rec = ds.records[0]
        assert rec.charger_id == "CH_01"
        assert rec.has_gap is True
        assert "voltage_mean" in rec.features
        assert round(rec.features["voltage_mean"], 1) == 230.0


class TestFleetProfiler:
    """Tests for fleet-level statistical profiling."""

    def test_build_charger_and_fleet_profile(self) -> None:
        profiler = FleetProfiler()
        t0 = dt.datetime(2026, 9, 1, 10, 0, tzinfo=dt.UTC)
        obs1 = [
            {"event_time": t0, "voltage": 230.0, "current": 10.0},
            {"event_time": t0 + dt.timedelta(minutes=1), "voltage": 231.0, "current": None},
        ]
        cp1 = profiler.build_charger_profile(
            "CH_01",
            observations=obs1,
            session_count=5,
            alarm_count=2,
            fault_count=1,
            gap_count=1,
        )
        assert cp1.charger_id == "CH_01"
        assert cp1.observation_count == 2
        assert cp1.distinct_timestamps == 2
        assert cp1.signal_coverage["voltage"] == 1.0
        assert cp1.signal_coverage["current"] == 0.5

        # Fleet profile from charger profiles
        fp = profiler.build_fleet_profile([cp1])
        assert fp.total_chargers == 1
        assert fp.total_observations == 2
        assert fp.total_sessions == 5
        assert fp.total_alarms == 2
        assert fp.total_faults == 1
        assert fp.total_gaps == 1
        assert fp.fleet_missing_rate > 0.0
