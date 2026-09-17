"""Time-series sampling interval analyzer for historical telemetry continuity.

Computes descriptive empirical sampling statistics (median, P05, P95, min, max deltas)
from observed chronological event times without forcing resampling or grid-alignment.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SamplingProfile:
    """Descriptive empirical sampling statistics for a timeline."""

    observation_count: int
    distinct_timestamps: int
    first_event_time: dt.datetime | None
    last_event_time: dt.datetime | None
    coverage_duration_seconds: float
    median_interval_seconds: float | None
    p05_interval_seconds: float | None
    p95_interval_seconds: float | None
    min_interval_seconds: float | None
    max_interval_seconds: float | None
    expected_interval_seconds: float | None
    same_second_frame_count: int


class SamplingAnalyzer:
    """Analyzes observed timestamp intervals without data fabrication."""

    MIN_SAMPLES_FOR_EXPECTED_INFERENCE = 5

    def analyze(
        self,
        event_times: list[dt.datetime],
        frame_sequences: list[int] | None = None,
    ) -> SamplingProfile:
        """Compute empirical interval statistics from chronological event timestamps.

        Input timestamps must already be sorted or will be paired with frame_sequences
        and sorted chronologically.
        """
        if not event_times:
            return SamplingProfile(
                observation_count=0,
                distinct_timestamps=0,
                first_event_time=None,
                last_event_time=None,
                coverage_duration_seconds=0.0,
                median_interval_seconds=None,
                p05_interval_seconds=None,
                p95_interval_seconds=None,
                min_interval_seconds=None,
                max_interval_seconds=None,
                expected_interval_seconds=None,
                same_second_frame_count=0,
            )

        if frame_sequences is None:
            frame_sequences = [0] * len(event_times)

        # Ensure canonical temporal sort: event_time ASC, frame_sequence ASC
        paired = sorted(zip(event_times, frame_sequences, strict=False), key=lambda x: (x[0], x[1]))
        sorted_times = [p[0] for p in paired]

        first_time = sorted_times[0]
        last_time = sorted_times[-1]
        coverage_duration = (last_time - first_time).total_seconds()

        # Compute positive deltas between consecutive distinct timestamps
        deltas: list[float] = []
        same_second_count = 0
        distinct_set = set(sorted_times)

        for i in range(1, len(sorted_times)):
            delta = (sorted_times[i] - sorted_times[i - 1]).total_seconds()
            if delta < 0:
                # Should not occur after sort, but safeguard against negative deltas
                continue
            if delta == 0.0:
                same_second_count += 1
            else:
                deltas.append(delta)

        if not deltas:
            # Single timestamp or all same-second frames
            return SamplingProfile(
                observation_count=len(sorted_times),
                distinct_timestamps=len(distinct_set),
                first_event_time=first_time,
                last_event_time=last_time,
                coverage_duration_seconds=coverage_duration,
                median_interval_seconds=None,
                p05_interval_seconds=None,
                p95_interval_seconds=None,
                min_interval_seconds=None,
                max_interval_seconds=None,
                expected_interval_seconds=None,
                same_second_frame_count=same_second_count,
            )

        sorted_deltas = sorted(deltas)
        n = len(sorted_deltas)
        median_val = float(statistics.median(sorted_deltas))
        p05_idx = int(round(0.05 * (n - 1)))
        p95_idx = int(round(0.95 * (n - 1)))
        p05_val = float(sorted_deltas[p05_idx])
        p95_val = float(sorted_deltas[p95_idx])
        min_val = float(sorted_deltas[0])
        max_val = float(sorted_deltas[-1])

        # Infer expected interval only if we have sufficient samples and reasonable stability
        expected_interval: float | None = None
        if n >= self.MIN_SAMPLES_FOR_EXPECTED_INFERENCE:
            within_cluster = sum(
                1 for d in sorted_deltas if (median_val * 0.85) <= d <= (median_val * 1.15)
            )
            if within_cluster >= n * 0.4:
                # Round to nearest integer or single decimal for clean expected cadence
                expected_interval = round(median_val, 1)

        return SamplingProfile(
            observation_count=len(sorted_times),
            distinct_timestamps=len(distinct_set),
            first_event_time=first_time,
            last_event_time=last_time,
            coverage_duration_seconds=coverage_duration,
            median_interval_seconds=round(median_val, 2),
            p05_interval_seconds=round(p05_val, 2),
            p95_interval_seconds=round(p95_val, 2),
            min_interval_seconds=round(min_val, 2),
            max_interval_seconds=round(max_val, 2),
            expected_interval_seconds=expected_interval,
            same_second_frame_count=same_second_count,
        )
