"""Monotonicity and transition analyzer for cumulative lifecycle counters.

Descriptively inspects cumulative counters (total energy, charge cycles, runtimes)
without automatic smoothing, delta imputation, or guessed repairs of decreases.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CounterTransitionType(StrEnum):
    """Categorization of transition between consecutive counter observations."""

    UNCHANGED = "UNCHANGED"
    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    RESET_CANDIDATE = "RESET_CANDIDATE"
    INITIAL = "INITIAL"


@dataclass(frozen=True, slots=True)
class CounterTransition:
    """Descriptive record of a step transition in a counter timeline."""

    charger_id: str
    counter_name: str
    event_time: dt.datetime
    frame_sequence: int
    previous_value: float | None
    current_value: float
    delta: float | None
    transition_type: CounterTransitionType


@dataclass(frozen=True, slots=True)
class CounterAnalysisReport:
    """Summary of counter behavior across an observed timeline."""

    counter_name: str
    total_observations: int
    non_null_observations: int
    first_value: float | None
    last_value: float | None
    net_change: float | None
    increase_count: int
    unchanged_count: int
    decrease_count: int
    reset_candidate_count: int
    transitions: list[CounterTransition]


class CounterAnalyzer:
    """Analyzes cumulative counters strictly preserving observations without repair."""

    # Drops larger than this percentage from preceding peak to near-zero indicate
    # a reset candidate
    RESET_CANDIDATE_RATIO = 0.5

    def analyze(
        self,
        charger_id: str,
        counter_name: str,
        observations: list[dict[str, Any]],
    ) -> CounterAnalysisReport:
        """Inspect chronological counter observations.

        Each observation dict is expected to contain:
          'event_time': dt.datetime
          'frame_sequence': int
          'value': float | int | None
        """
        if not observations:
            return CounterAnalysisReport(
                counter_name=counter_name,
                total_observations=0,
                non_null_observations=0,
                first_value=None,
                last_value=None,
                net_change=None,
                increase_count=0,
                unchanged_count=0,
                decrease_count=0,
                reset_candidate_count=0,
                transitions=[],
            )

        # Ensure canonical temporal order
        sorted_obs = sorted(
            observations,
            key=lambda x: (x["event_time"], x.get("frame_sequence", 0)),
        )

        transitions: list[CounterTransition] = []
        increase_cnt = 0
        unchanged_cnt = 0
        decrease_cnt = 0
        reset_cnt = 0

        first_val: float | None = None
        last_val: float | None = None
        prev_val: float | None = None
        max_seen: float = 0.0
        non_null_cnt = 0

        for obs in sorted_obs:
            raw_v = obs.get("value")
            if raw_v is None:
                continue

            try:
                curr_val = float(raw_v)
            except (ValueError, TypeError):
                continue

            non_null_cnt += 1
            if first_val is None:
                first_val = curr_val
                transitions.append(
                    CounterTransition(
                        charger_id=charger_id,
                        counter_name=counter_name,
                        event_time=obs["event_time"],
                        frame_sequence=obs.get("frame_sequence", 0),
                        previous_value=None,
                        current_value=curr_val,
                        delta=None,
                        transition_type=CounterTransitionType.INITIAL,
                    )
                )
                prev_val = curr_val
                max_seen = curr_val
                last_val = curr_val
                continue

            last_val = curr_val
            delta = curr_val - prev_val  # type: ignore[operator]

            if delta > 0:
                trans_type = CounterTransitionType.INCREASED
                increase_cnt += 1
                if curr_val > max_seen:
                    max_seen = curr_val
            elif delta == 0:
                trans_type = CounterTransitionType.UNCHANGED
                unchanged_cnt += 1
            else:
                # Value decreased! Determine if it qualifies as a reset candidate
                decrease_cnt += 1
                if max_seen > 10.0 and curr_val < (max_seen * self.RESET_CANDIDATE_RATIO):
                    trans_type = CounterTransitionType.RESET_CANDIDATE
                    reset_cnt += 1
                else:
                    trans_type = CounterTransitionType.DECREASED

            transitions.append(
                CounterTransition(
                    charger_id=charger_id,
                    counter_name=counter_name,
                    event_time=obs["event_time"],
                    frame_sequence=obs.get("frame_sequence", 0),
                    previous_value=prev_val,
                    current_value=curr_val,
                    delta=round(delta, 3),
                    transition_type=trans_type,
                )
            )
            prev_val = curr_val

        net_change = (
            (last_val - first_val) if (first_val is not None and last_val is not None) else None
        )

        return CounterAnalysisReport(
            counter_name=counter_name,
            total_observations=len(sorted_obs),
            non_null_observations=non_null_cnt,
            first_value=first_val,
            last_value=last_val,
            net_change=round(net_change, 3) if net_change is not None else None,
            increase_count=increase_cnt,
            unchanged_count=unchanged_cnt,
            decrease_count=decrease_cnt,
            reset_candidate_count=reset_cnt,
            transitions=transitions,
        )
