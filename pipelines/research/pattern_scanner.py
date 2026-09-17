"""Automated pattern scanning on analytical datasets (Phase 9).

Detects domain-informed telemetry patterns: thermal drift, voltage anomalies,
current imbalance, alarm clustering, session degradation, and component divergence.
All findings are classified with graduated evidence levels.

Zero IO — operates on pre-built analytical records and signal arrays.
"""

from __future__ import annotations

import math
import time
from typing import Any

from backend.app.models.enums import (
    AnalyticalGrain,
    PatternCategory,
    PatternEvidenceLevel,
)
from pipelines.research.models import (
    PatternCandidate,
    PatternEvidence,
    PatternScanResult,
    SignalStatistics,
)

__all__ = ["PatternScanner"]


class PatternScanner:
    """Scans analytical data for telemetry patterns and anomalies."""

    # Configurable thresholds
    DEFAULT_VOLTAGE_LOW = 200.0  # V - lower bound for phase-neutral voltage
    DEFAULT_VOLTAGE_HIGH = 260.0  # V - upper bound for phase-neutral voltage
    DEFAULT_CURRENT_IMBALANCE_THRESHOLD = 0.2  # 20% relative deviation
    DEFAULT_TEMP_DRIFT_THRESHOLD = 5.0  # °C monotonic increase considered drift
    DEFAULT_ALARM_CLUSTER_WINDOW_SECONDS = 3600.0  # 1 hour
    DEFAULT_ALARM_CLUSTER_MIN_COUNT = 3  # min alarms in cluster

    def __init__(
        self,
        *,
        voltage_low: float = DEFAULT_VOLTAGE_LOW,
        voltage_high: float = DEFAULT_VOLTAGE_HIGH,
        current_imbalance_threshold: float = DEFAULT_CURRENT_IMBALANCE_THRESHOLD,
        temp_drift_threshold: float = DEFAULT_TEMP_DRIFT_THRESHOLD,
        alarm_cluster_window_seconds: float = DEFAULT_ALARM_CLUSTER_WINDOW_SECONDS,
        alarm_cluster_min_count: int = DEFAULT_ALARM_CLUSTER_MIN_COUNT,
    ) -> None:
        self._voltage_low = voltage_low
        self._voltage_high = voltage_high
        self._current_imbalance = current_imbalance_threshold
        self._temp_drift = temp_drift_threshold
        self._alarm_cluster_window = alarm_cluster_window_seconds
        self._alarm_cluster_min_count = alarm_cluster_min_count

    def scan(
        self,
        charger_id: str,
        *,
        signal_stats: list[SignalStatistics] | None = None,
        session_features: list[dict[str, Any]] | None = None,
        alarm_events: list[dict[str, Any]] | None = None,
        fleet_signal_stats: dict[str, SignalStatistics] | None = None,
    ) -> PatternScanResult:
        """Run all pattern detectors and return consolidated scan result."""
        t0 = time.monotonic()
        candidates: list[PatternCandidate] = []
        stats = signal_stats or []
        fleet_stats = fleet_signal_stats or {}
        signals_scanned = len(stats)

        # --- Voltage anomaly detection ---
        voltage_signals = {
            s.signal_name: s
            for s in stats
            if "voltage" in s.signal_name.lower() and s.non_null_count > 0 and s.mean is not None
        }
        for sig_name, sig_stat in voltage_signals.items():
            # Skip line-line voltages (higher nominal values)
            if any(x in sig_name for x in ("l1_l2", "l2_l3", "l3_l1")):
                continue
            candidates.extend(
                self._check_voltage_anomaly(charger_id, sig_name, sig_stat, fleet_stats)
            )

        # --- Current imbalance detection ---
        candidates.extend(self._check_current_imbalance(charger_id, stats, fleet_stats))

        # --- Thermal drift detection ---
        temp_signals = {
            s.signal_name: s
            for s in stats
            if "temp" in s.signal_name.lower() and s.non_null_count > 0 and s.mean is not None
        }
        for sig_name, sig_stat in temp_signals.items():
            candidates.extend(
                self._check_thermal_drift(charger_id, sig_name, sig_stat, fleet_stats)
            )

        # --- Session degradation detection ---
        if session_features:
            candidates.extend(self._check_session_degradation(charger_id, session_features))

        # --- Alarm clustering detection ---
        if alarm_events:
            candidates.extend(self._check_alarm_clustering(charger_id, alarm_events))

        scan_ms = (time.monotonic() - t0) * 1000
        return PatternScanResult(
            charger_id=charger_id,
            candidates=tuple(candidates),
            scan_duration_ms=scan_ms,
            signals_scanned=signals_scanned,
            records_analyzed=len(session_features or []) + len(alarm_events or []),
            scan_version="v1",
        )

    def _check_voltage_anomaly(
        self,
        charger_id: str,
        signal_name: str,
        stat: SignalStatistics,
        fleet_stats: dict[str, SignalStatistics],
    ) -> list[PatternCandidate]:
        """Detect out-of-range voltage readings."""
        candidates: list[PatternCandidate] = []

        if stat.mean is None or stat.min_val is None or stat.max_val is None:
            return candidates

        evidence_items: list[PatternEvidence] = []
        anomaly = False

        if stat.min_val < self._voltage_low:
            anomaly = True
            evidence_items.append(
                PatternEvidence(
                    metric_name=f"{signal_name}_min",
                    observed_value=stat.min_val,
                    reference_value=self._voltage_low,
                    threshold=self._voltage_low,
                    description=(
                        f"Minimum {signal_name} ({stat.min_val:.1f}V) "
                        f"below threshold ({self._voltage_low:.0f}V)"
                    ),
                )
            )

        if stat.max_val > self._voltage_high:
            anomaly = True
            evidence_items.append(
                PatternEvidence(
                    metric_name=f"{signal_name}_max",
                    observed_value=stat.max_val,
                    reference_value=self._voltage_high,
                    threshold=self._voltage_high,
                    description=(
                        f"Maximum {signal_name} ({stat.max_val:.1f}V) "
                        f"above threshold ({self._voltage_high:.0f}V)"
                    ),
                )
            )

        # Compare to fleet median if available
        fleet_stat = fleet_stats.get(signal_name)
        if fleet_stat and fleet_stat.p50 is not None and stat.mean is not None:
            deviation = abs(stat.mean - fleet_stat.p50) / max(fleet_stat.p50, 1e-6)
            if deviation > 0.1:  # >10% deviation from fleet median
                anomaly = True
                evidence_items.append(
                    PatternEvidence(
                        metric_name=f"{signal_name}_fleet_deviation",
                        observed_value=stat.mean,
                        reference_value=fleet_stat.p50,
                        threshold=0.1,
                        description=(
                            f"{signal_name} mean ({stat.mean:.1f}V) deviates "
                            f"{deviation:.1%} from fleet median ({fleet_stat.p50:.1f}V)"
                        ),
                    )
                )

        if anomaly and evidence_items:
            # Determine evidence level
            evidence_level = PatternEvidenceLevel.OBSERVATION
            if len(evidence_items) >= 2:
                evidence_level = PatternEvidenceLevel.WEAK_CANDIDATE
            if stat.non_null_count >= 100 and len(evidence_items) >= 2:
                evidence_level = PatternEvidenceLevel.MODERATE_CANDIDATE

            candidates.append(
                PatternCandidate(
                    charger_id=charger_id,
                    pattern_category=PatternCategory.VOLTAGE_ANOMALY,
                    evidence_level=evidence_level,
                    title=f"Voltage anomaly detected on {signal_name}",
                    description=(
                        f"Signal {signal_name} shows out-of-range readings "
                        f"(range: {stat.min_val:.1f}–{stat.max_val:.1f}V, "
                        f"mean: {stat.mean:.1f}V) across {stat.non_null_count} observations."
                    ),
                    confidence_score=min(0.3 + 0.1 * len(evidence_items), 0.8),
                    affected_signals=(signal_name,),
                    supporting_evidence=tuple(evidence_items),
                    analytical_grain=AnalyticalGrain.CHARGER_TIME,
                    scan_version="v1",
                )
            )

        return candidates

    def _check_current_imbalance(
        self,
        charger_id: str,
        stats: list[SignalStatistics],
        fleet_stats: dict[str, SignalStatistics],
    ) -> list[PatternCandidate]:
        """Detect phase current imbalance (L1/L2/L3 divergence)."""
        current_map: dict[str, SignalStatistics] = {}
        for s in stats:
            if (
                "input_current" in s.signal_name.lower()
                and s.non_null_count > 0
                and s.mean is not None
            ):
                current_map[s.signal_name] = s

        if len(current_map) < 2:
            return []

        means = {name: st.mean for name, st in current_map.items() if st.mean is not None}
        if len(means) < 2:
            return []

        avg_current = sum(means.values()) / len(means)
        if avg_current < 0.01:  # Near-zero currents, skip
            return []

        max_deviation = max(abs(m - avg_current) / avg_current for m in means.values())

        if max_deviation <= self._current_imbalance:
            return []

        evidence_items = [
            PatternEvidence(
                metric_name=name,
                observed_value=mean,
                reference_value=avg_current,
                threshold=self._current_imbalance,
                description=(
                    f"{name} mean={mean:.2f}A vs average={avg_current:.2f}A "
                    f"({abs(mean - avg_current) / avg_current:.1%} deviation)"
                ),
            )
            for name, mean in means.items()
        ]

        evidence_level = PatternEvidenceLevel.OBSERVATION
        if max_deviation > 0.3:
            evidence_level = PatternEvidenceLevel.WEAK_CANDIDATE
        if max_deviation > 0.5:
            evidence_level = PatternEvidenceLevel.MODERATE_CANDIDATE

        return [
            PatternCandidate(
                charger_id=charger_id,
                pattern_category=PatternCategory.CURRENT_IMBALANCE,
                evidence_level=evidence_level,
                title="Phase current imbalance detected",
                description=(
                    f"Input currents show {max_deviation:.1%} maximum deviation "
                    f"from average ({avg_current:.2f}A). "
                    f"Threshold: {self._current_imbalance:.0%}."
                ),
                confidence_score=min(0.3 + max_deviation, 0.9),
                affected_signals=tuple(means.keys()),
                supporting_evidence=tuple(evidence_items),
                analytical_grain=AnalyticalGrain.CHARGER_TIME,
                scan_version="v1",
            )
        ]

    def _check_thermal_drift(
        self,
        charger_id: str,
        signal_name: str,
        stat: SignalStatistics,
        fleet_stats: dict[str, SignalStatistics],
    ) -> list[PatternCandidate]:
        """Detect abnormal temperature readings indicating thermal issues."""
        if stat.mean is None or stat.max_val is None:
            return []

        evidence_items: list[PatternEvidence] = []

        # Check if max temperature is significantly above mean (potential drift)
        if stat.std is not None and stat.std > 0:
            spread = stat.max_val - stat.mean
            if spread > self._temp_drift:
                evidence_items.append(
                    PatternEvidence(
                        metric_name=f"{signal_name}_spread",
                        observed_value=spread,
                        reference_value=self._temp_drift,
                        threshold=self._temp_drift,
                        description=(
                            f"{signal_name} spread (max - mean = {spread:.1f}°C) "
                            f"exceeds drift threshold ({self._temp_drift:.0f}°C)"
                        ),
                    )
                )

        # Compare to fleet if available
        fleet_stat = fleet_stats.get(signal_name)
        if (
            fleet_stat
            and fleet_stat.p95 is not None
            and stat.max_val is not None
            and stat.max_val > fleet_stat.p95
        ):
            evidence_items.append(
                PatternEvidence(
                    metric_name=f"{signal_name}_fleet_p95_exceedance",
                    observed_value=stat.max_val,
                    reference_value=fleet_stat.p95,
                    threshold=fleet_stat.p95,
                    description=(
                        f"{signal_name} max ({stat.max_val:.1f}°C) exceeds "
                        f"fleet P95 ({fleet_stat.p95:.1f}°C)"
                    ),
                )
            )

        if not evidence_items:
            return []

        evidence_level = PatternEvidenceLevel.OBSERVATION
        if len(evidence_items) >= 2:
            evidence_level = PatternEvidenceLevel.WEAK_CANDIDATE

        return [
            PatternCandidate(
                charger_id=charger_id,
                pattern_category=PatternCategory.THERMAL_DRIFT,
                evidence_level=evidence_level,
                title=f"Thermal anomaly on {signal_name}",
                description=(
                    f"{signal_name}: mean={stat.mean:.1f}°C, max={stat.max_val:.1f}°C, "
                    f"std={stat.std:.1f}°C across {stat.non_null_count} observations."
                ),
                confidence_score=min(0.3 + 0.15 * len(evidence_items), 0.75),
                affected_signals=(signal_name,),
                supporting_evidence=tuple(evidence_items),
                analytical_grain=AnalyticalGrain.CHARGER_TIME,
                scan_version="v1",
            )
        ]

    def _check_session_degradation(
        self,
        charger_id: str,
        session_features: list[dict[str, Any]],
    ) -> list[PatternCandidate]:
        """Detect declining session quality (energy, success rate)."""
        if len(session_features) < 2:
            return []

        evidence_items: list[PatternEvidence] = []
        energies: list[float] = []
        durations: list[float] = []
        failed = 0
        total = len(session_features)

        for sf in session_features:
            e = sf.get("energy_delivered_kwh")
            d = sf.get("duration_seconds")
            tc = sf.get("termination_class")
            if isinstance(e, (int, float)) and not math.isnan(e):
                energies.append(float(e))
            if isinstance(d, (int, float)) and not math.isnan(d):
                durations.append(float(d))
            if tc and str(tc) not in ("NORMAL", "USER_STOPPED", "REMOTE_STOPPED"):
                failed += 1

        # Check failure rate
        failure_rate = failed / total
        if failure_rate > 0.3:
            evidence_items.append(
                PatternEvidence(
                    metric_name="session_failure_rate",
                    observed_value=failure_rate,
                    reference_value=0.1,
                    threshold=0.3,
                    description=f"Session failure rate ({failure_rate:.0%}) exceeds 30% threshold",
                )
            )

        # Check zero-energy sessions
        if energies:
            zero_energy = sum(1 for e in energies if e <= 0.01)
            zero_rate = zero_energy / len(energies)
            if zero_rate > 0.2:
                evidence_items.append(
                    PatternEvidence(
                        metric_name="zero_energy_session_rate",
                        observed_value=zero_rate,
                        reference_value=0.05,
                        threshold=0.2,
                        description=(
                            f"Zero-energy session rate ({zero_rate:.0%}) exceeds 20% threshold"
                        ),
                    )
                )

        if not evidence_items:
            return []

        evidence_level = PatternEvidenceLevel.OBSERVATION
        if len(evidence_items) >= 2:
            evidence_level = PatternEvidenceLevel.WEAK_CANDIDATE

        return [
            PatternCandidate(
                charger_id=charger_id,
                pattern_category=PatternCategory.SESSION_DEGRADATION,
                evidence_level=evidence_level,
                title="Session quality degradation indicators",
                description=(
                    f"{total} sessions analyzed: failure rate={failure_rate:.0%}, "
                    f"avg energy={sum(energies) / len(energies):.1f} kWh"
                    if energies
                    else f"{total} sessions analyzed: failure rate={failure_rate:.0%}"
                ),
                confidence_score=min(0.3 + 0.2 * len(evidence_items), 0.7),
                affected_signals=("energy_delivered_kwh", "termination_class"),
                supporting_evidence=tuple(evidence_items),
                analytical_grain=AnalyticalGrain.SESSION_LEVEL,
                scan_version="v1",
            )
        ]

    def _check_alarm_clustering(
        self,
        charger_id: str,
        alarm_events: list[dict[str, Any]],
    ) -> list[PatternCandidate]:
        """Detect temporal clustering of alarm events."""
        import datetime as dt

        if len(alarm_events) < self._alarm_cluster_min_count:
            return []

        # Parse alarm times
        alarm_times: list[tuple[dt.datetime, str]] = []
        for ae in alarm_events:
            t = ae.get("start_time")
            code = ae.get("alarm_code", "unknown")
            if isinstance(t, str):
                try:
                    t = dt.datetime.fromisoformat(t)
                except ValueError:
                    continue
            if isinstance(t, dt.datetime):
                alarm_times.append((t, code))

        if len(alarm_times) < self._alarm_cluster_min_count:
            return []

        alarm_times.sort(key=lambda x: x[0])

        # Sliding window clustering
        candidates: list[PatternCandidate] = []
        window_td = dt.timedelta(seconds=self._alarm_cluster_window)

        i = 0
        while i < len(alarm_times):
            window_end = alarm_times[i][0] + window_td
            j = i
            while j < len(alarm_times) and alarm_times[j][0] <= window_end:
                j += 1

            cluster_size = j - i
            if cluster_size >= self._alarm_cluster_min_count:
                cluster_codes = [alarm_times[k][1] for k in range(i, j)]
                distinct_codes = set(cluster_codes)
                evidence_level = PatternEvidenceLevel.OBSERVATION
                if cluster_size >= self._alarm_cluster_min_count * 2:
                    evidence_level = PatternEvidenceLevel.WEAK_CANDIDATE
                if len(distinct_codes) >= 3:
                    evidence_level = PatternEvidenceLevel.MODERATE_CANDIDATE

                candidates.append(
                    PatternCandidate(
                        charger_id=charger_id,
                        pattern_category=PatternCategory.ALARM_CLUSTERING,
                        evidence_level=evidence_level,
                        title=(
                            f"Alarm cluster: {cluster_size} alarms in "
                            f"{self._alarm_cluster_window / 3600:.0f}h window"
                        ),
                        description=(
                            f"{cluster_size} alarms ({len(distinct_codes)} distinct codes) "
                            f"clustered between {alarm_times[i][0].isoformat()} and "
                            f"{alarm_times[j - 1][0].isoformat()}"
                        ),
                        confidence_score=min(0.2 + 0.1 * cluster_size, 0.8),
                        affected_signals=tuple(sorted(distinct_codes)),
                        observation_window_start=alarm_times[i][0],
                        observation_window_end=alarm_times[j - 1][0],
                        supporting_evidence=(
                            PatternEvidence(
                                metric_name="cluster_size",
                                observed_value=float(cluster_size),
                                reference_value=float(self._alarm_cluster_min_count),
                                threshold=float(self._alarm_cluster_min_count),
                                description=(
                                    f"{cluster_size} alarms in {self._alarm_cluster_window}s window"
                                ),
                            ),
                        ),
                        analytical_grain=AnalyticalGrain.CHARGER_TIME,
                        scan_version="v1",
                    )
                )
                # Skip past this cluster
                i = j
            else:
                i += 1

        return candidates
