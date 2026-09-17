"""Historical telemetry gap detector.

Identifies absent telemetry intervals relative to local empirical sampling cadence.
STRICT INVARIANT: Observes gaps; never interpolates, synthesizes, or fills missing data.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from pipelines.historical.sampling_analyzer import SamplingAnalyzer, SamplingProfile


@dataclass(frozen=True, slots=True)
class HistoricalGap:
    """Explicit descriptor for an observed discontinuity in telemetry."""

    charger_id: str
    component_type: str | None
    component_id: int | None
    gap_start: dt.datetime
    gap_end: dt.datetime
    gap_duration_seconds: float
    previous_event_time: dt.datetime
    next_event_time: dt.datetime
    expected_interval_seconds: float | None
    gap_multiple: float | None
    detection_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "charger_id": self.charger_id,
            "component_type": self.component_type,
            "component_id": self.component_id,
            "gap_start": self.gap_start.isoformat(),
            "gap_end": self.gap_end.isoformat(),
            "gap_duration_seconds": self.gap_duration_seconds,
            "previous_event_time": self.previous_event_time.isoformat(),
            "next_event_time": self.next_event_time.isoformat(),
            "expected_interval_seconds": self.expected_interval_seconds,
            "gap_multiple": self.gap_multiple,
            "detection_version": self.detection_version,
        }


class GapDetector:
    """Detects missing telemetry windows without imputation."""

    DEFAULT_GAP_MULTIPLIER = 2.5
    DEFAULT_MINIMUM_GAP_SECONDS = 180.0
    FALLBACK_GAP_THRESHOLD_SECONDS = 300.0

    def __init__(
        self,
        gap_multiplier: float = DEFAULT_GAP_MULTIPLIER,
        min_gap_seconds: float = DEFAULT_MINIMUM_GAP_SECONDS,
        sampling_analyzer: SamplingAnalyzer | None = None,
    ) -> None:
        self._multiplier = gap_multiplier
        self._min_gap = min_gap_seconds
        self._analyzer = sampling_analyzer or SamplingAnalyzer()

    def detect_gaps(
        self,
        charger_id: str,
        event_times: list[dt.datetime],
        frame_sequences: list[int] | None = None,
        component_type: str | None = None,
        component_id: int | None = None,
        sampling_profile: SamplingProfile | None = None,
    ) -> list[HistoricalGap]:
        """Detect telemetry gaps across chronologically ordered event timestamps.

        Gaps are defined when delta exceeds max(min_gap, expected_interval * multiplier).
        No synthetic rows or interpolation are ever generated.
        """
        if len(event_times) < 2:
            return []

        if frame_sequences is None:
            frame_sequences = [0] * len(event_times)

        paired = sorted(zip(event_times, frame_sequences, strict=False), key=lambda x: (x[0], x[1]))
        sorted_times = [p[0] for p in paired]

        if sampling_profile is None:
            sampling_profile = self._analyzer.analyze(sorted_times, [p[1] for p in paired])

        expected = (
            sampling_profile.expected_interval_seconds or sampling_profile.median_interval_seconds
        )

        if expected is not None and expected > 0:
            threshold_seconds = max(self._min_gap, expected * self._multiplier)
        else:
            threshold_seconds = self.FALLBACK_GAP_THRESHOLD_SECONDS

        gaps: list[HistoricalGap] = []

        for i in range(1, len(sorted_times)):
            prev_t = sorted_times[i - 1]
            curr_t = sorted_times[i]
            duration = (curr_t - prev_t).total_seconds()

            if duration < 0:
                # Impossible negative duration safeguard
                continue

            if duration > threshold_seconds:
                multiple = round(duration / expected, 2) if expected and expected > 0 else None
                # Gap starts immediately after previous expected observation
                gap_start = prev_t
                gap_end = curr_t

                gaps.append(
                    HistoricalGap(
                        charger_id=charger_id,
                        component_type=component_type,
                        component_id=component_id,
                        gap_start=gap_start,
                        gap_end=gap_end,
                        gap_duration_seconds=duration,
                        previous_event_time=prev_t,
                        next_event_time=curr_t,
                        expected_interval_seconds=expected,
                        gap_multiple=multiple,
                    )
                )

        return gaps
