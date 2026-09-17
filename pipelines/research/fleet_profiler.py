"""Fleet-level statistical profiling (Phase 9).

Aggregates per-charger observation statistics, signal coverage,
topology distributions, and missingness matrices into a unified
fleet profile. Zero IO — operates on pre-fetched data.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pipelines.research.models import (
    ChargerProfile,
    FleetProfile,
    SignalStatistics,
)
from pipelines.research.signal_statistician import SignalStatistician

__all__ = ["FleetProfiler"]


class FleetProfiler:
    """Builds fleet-wide and per-charger statistical profiles."""

    def __init__(
        self,
        *,
        statistician: SignalStatistician | None = None,
    ) -> None:
        self._stat = statistician or SignalStatistician()

    def build_charger_profile(
        self,
        charger_id: str,
        *,
        observations: list[dict[str, Any]],
        session_count: int = 0,
        alarm_count: int = 0,
        fault_count: int = 0,
        gap_count: int = 0,
        connector_count: int = 0,
        smr_count: int = 0,
        rectifier_count: int = 0,
    ) -> ChargerProfile:
        """Build a statistical profile for a single charger.

        ``observations`` is a list of dicts, each dict mapping signal names
        to their observed values at one timestamp.
        """
        n = len(observations)
        timestamps: set[dt.datetime] = set()
        signal_non_null: dict[str, int] = {}
        signal_total: dict[str, int] = {}
        first_seen: dt.datetime | None = None
        last_seen: dt.datetime | None = None

        for obs in observations:
            event_time = obs.get("event_time")
            if isinstance(event_time, dt.datetime):
                timestamps.add(event_time)
                if first_seen is None or event_time < first_seen:
                    first_seen = event_time
                if last_seen is None or event_time > last_seen:
                    last_seen = event_time

            for key, val in obs.items():
                if key in ("event_time", "frame_sequence", "frame_id", "charger_id"):
                    continue
                signal_total[key] = signal_total.get(key, 0) + 1
                if val is not None:
                    signal_non_null[key] = signal_non_null.get(key, 0) + 1

        signal_coverage: dict[str, float] = {}
        for sig, total in signal_total.items():
            non_null = signal_non_null.get(sig, 0)
            signal_coverage[sig] = non_null / total if total > 0 else 0.0

        return ChargerProfile(
            charger_id=charger_id,
            observation_count=n,
            first_seen=first_seen,
            last_seen=last_seen,
            distinct_timestamps=len(timestamps),
            connector_count=connector_count,
            smr_count=smr_count,
            rectifier_count=rectifier_count,
            session_count=session_count,
            alarm_count=alarm_count,
            fault_count=fault_count,
            gap_count=gap_count,
            signal_coverage=signal_coverage,
        )

    def build_fleet_profile(
        self,
        charger_profiles: list[ChargerProfile],
        *,
        fleet_signal_values: dict[str, list[Any]] | None = None,
    ) -> FleetProfile:
        """Aggregate charger profiles into a fleet-wide summary.

        ``fleet_signal_values`` maps signal names to merged observation
        values across the entire fleet for fleet-level statistics.
        """
        total_chargers = len(charger_profiles)
        total_observations = sum(cp.observation_count for cp in charger_profiles)
        total_sessions = sum(cp.session_count for cp in charger_profiles)
        total_alarms = sum(cp.alarm_count for cp in charger_profiles)
        total_faults = sum(cp.fault_count for cp in charger_profiles)
        total_gaps = sum(cp.gap_count for cp in charger_profiles)

        first_seen: dt.datetime | None = None
        last_seen: dt.datetime | None = None
        all_null_counts = 0
        all_total_counts = 0

        for cp in charger_profiles:
            if cp.first_seen is not None and (first_seen is None or cp.first_seen < first_seen):
                first_seen = cp.first_seen
            if cp.last_seen is not None and (last_seen is None or cp.last_seen > last_seen):
                last_seen = cp.last_seen
            for _sig, cov in cp.signal_coverage.items():
                total = cp.observation_count
                non_null = int(cov * total)
                all_null_counts += total - non_null
                all_total_counts += total

        fleet_missing_rate = all_null_counts / all_total_counts if all_total_counts > 0 else 0.0

        fleet_stats: list[SignalStatistics] = []
        if fleet_signal_values:
            for sig_name, values in sorted(fleet_signal_values.items()):
                stats = self._stat.compute_statistics(sig_name, values)
                fleet_stats.append(stats)

        return FleetProfile(
            total_chargers=total_chargers,
            total_observations=total_observations,
            charger_profiles=tuple(charger_profiles),
            fleet_signal_stats=tuple(fleet_stats),
            temporal_span_start=first_seen,
            temporal_span_end=last_seen,
            total_sessions=total_sessions,
            total_alarms=total_alarms,
            total_faults=total_faults,
            total_gaps=total_gaps,
            fleet_missing_rate=fleet_missing_rate,
        )
