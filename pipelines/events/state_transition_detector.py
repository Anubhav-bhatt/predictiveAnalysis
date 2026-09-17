"""Discrete state transition detector (Phase 8).

Identifies operational state changes ordered strictly by (event_time ASC, frame_sequence ASC),
preserving same-second physical transitions without fabricated timestamps.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pipelines.events.models import ReconstructedStateTransition

__all__ = ["StateObservation", "StateTransitionDetector"]


@dataclass(frozen=True, slots=True)
class StateObservation:
    """A point-in-time discrete state reading."""

    event_time: dt.datetime
    frame_sequence: int
    state_val: str | None
    frame_id: uuid.UUID | None = None


class StateTransitionDetector:
    """Detects transitions on discrete status fields over time."""

    def detect_transitions(
        self,
        charger_id: str,
        component_type: str,
        component_id: int | None,
        state_field: str,
        observations: Sequence[StateObservation],
    ) -> list[ReconstructedStateTransition]:
        """Process chronological state readings and return discrete transition events."""
        if len(observations) < 2:
            return []

        # Sort strictly by (event_time ASC, frame_sequence ASC)
        ordered = sorted(observations, key=lambda o: (o.event_time, o.frame_sequence))

        transitions: list[ReconstructedStateTransition] = []
        prev = ordered[0]

        for curr in ordered[1:]:
            curr_val = curr.state_val.strip() if curr.state_val is not None else None
            prev_val = prev.state_val.strip() if prev.state_val is not None else None

            if curr_val is not None and curr_val != prev_val:
                transitions.append(
                    ReconstructedStateTransition(
                        charger_id=charger_id,
                        component_type=component_type,
                        component_id=component_id,
                        state_field=state_field,
                        from_state=prev_val,
                        to_state=curr_val,
                        transition_time=curr.event_time,
                        frame_sequence=curr.frame_sequence,
                        frame_id=curr.frame_id,
                    )
                )
            prev = curr

        return transitions
