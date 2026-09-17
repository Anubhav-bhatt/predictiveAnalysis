"""Descriptive pattern research eligibility evaluator.

Answers: "Do we have enough empirical historical data to study temporal patterns?"
STRICT INVARIANT: Evaluates research data eligibility only. NEVER classifies
equipment health, degradation, or failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipelines.historical.gap_detector import HistoricalGap
from pipelines.historical.sampling_analyzer import SamplingProfile


@dataclass(frozen=True, slots=True)
class ResearchEligibility:
    """Descriptive evaluation of historical telemetry readiness for pattern research."""

    charger_id: str
    history_days: int
    observation_count: int
    median_sampling_interval_seconds: float | None
    largest_gap_seconds: float | None
    gap_count: int
    signal_count: int
    pattern_research_ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "charger_id": self.charger_id,
            "history_days": self.history_days,
            "observation_count": self.observation_count,
            "median_sampling_interval_seconds": self.median_sampling_interval_seconds,
            "largest_gap_seconds": self.largest_gap_seconds,
            "gap_count": self.gap_count,
            "signal_count": self.signal_count,
            "pattern_research_ready": self.pattern_research_ready,
            "reason": self.reason,
        }


class PatternResearchEligibilityEvaluator:
    """Evaluates historical data readiness using conservative scientific criteria."""

    MIN_HISTORY_DAYS = 7
    MIN_OBSERVATIONS = 100
    MAX_GAP_RATIO = 0.35

    def evaluate(
        self,
        charger_id: str,
        profile: SamplingProfile,
        gaps: list[HistoricalGap],
        signal_count: int = 0,
        active_days: int = 0,
    ) -> ResearchEligibility:
        """Evaluate historical data sufficiency without evaluating physical equipment health."""
        if profile.observation_count <= 1:
            return ResearchEligibility(
                charger_id=charger_id,
                history_days=active_days or (1 if profile.observation_count == 1 else 0),
                observation_count=profile.observation_count,
                median_sampling_interval_seconds=None,
                largest_gap_seconds=None,
                gap_count=0,
                signal_count=signal_count,
                pattern_research_ready=False,
                reason=(
                    "Only 1 historical observation is available. "
                    "Temporal pattern analysis is not yet possible."
                ),
            )

        history_days = active_days or max(1, int(profile.coverage_duration_seconds // 86400) + 1)
        largest_gap = max((g.gap_duration_seconds for g in gaps), default=0.0)
        total_gap_duration = sum(g.gap_duration_seconds for g in gaps)

        reasons: list[str] = []

        if history_days < self.MIN_HISTORY_DAYS:
            reasons.append(
                f"Insufficient historical depth ({history_days} < {self.MIN_HISTORY_DAYS} days)"
            )

        if profile.observation_count < self.MIN_OBSERVATIONS:
            reasons.append(
                f"Insufficient observation count ({profile.observation_count} < "
                f"{self.MIN_OBSERVATIONS})"
            )

        if profile.coverage_duration_seconds > 0:
            gap_ratio = total_gap_duration / profile.coverage_duration_seconds
            if gap_ratio > self.MAX_GAP_RATIO:
                reasons.append(
                    f"Excessive telemetry gaps ({round(gap_ratio * 100, 1)}% unobserved time)"
                )

        if reasons:
            return ResearchEligibility(
                charger_id=charger_id,
                history_days=history_days,
                observation_count=profile.observation_count,
                median_sampling_interval_seconds=profile.median_interval_seconds,
                largest_gap_seconds=round(largest_gap, 1) if largest_gap > 0 else None,
                gap_count=len(gaps),
                signal_count=signal_count,
                pattern_research_ready=False,
                reason="; ".join(reasons) + ".",
            )

        return ResearchEligibility(
            charger_id=charger_id,
            history_days=history_days,
            observation_count=profile.observation_count,
            median_sampling_interval_seconds=profile.median_interval_seconds,
            largest_gap_seconds=round(largest_gap, 1) if largest_gap > 0 else None,
            gap_count=len(gaps),
            signal_count=signal_count,
            pattern_research_ready=True,
            reason=(
                "Sufficient historical depth and sampling regularity available "
                "for pattern research."
            ),
        )
