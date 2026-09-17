"""Historical topology evolution and physical component presence tracker.

Tracks observed presence intervals (first_seen, last_seen) for connectors, SMRs,
and rectifiers across time without assuming static hardware topology.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ComponentPresence:
    """Historical presence interval for a physical component."""

    component_type: str  # "connector", "smr", "rectifier"
    component_id: int
    first_seen: dt.datetime
    last_seen: dt.datetime
    observation_count: int = 0
    active_dates: set[dt.date] = field(default_factory=set)

    @property
    def active_days_count(self) -> int:
        return len(self.active_dates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type,
            "component_id": self.component_id,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "observation_count": self.observation_count,
            "active_days_count": self.active_days_count,
        }


@dataclass(frozen=True, slots=True)
class TopologySnapshot:
    """Observed component presence across a specific timeframe or date."""

    charger_id: str
    observed_connectors: tuple[int, ...]
    observed_smrs: tuple[int, ...]
    observed_rectifiers: tuple[int, ...]
    as_of: dt.datetime


class TopologyTracker:
    """Tracks physical component presence through historical telemetry."""

    def track_presence(
        self,
        component_type: str,
        observations: list[tuple[int, dt.datetime]],
    ) -> dict[int, ComponentPresence]:
        """Track presence intervals for a component type.

        observations: list of (component_id, event_time).
        """
        presence_map: dict[int, ComponentPresence] = {}

        for comp_id, event_time in sorted(observations, key=lambda x: x[1]):
            obs_date = event_time.date()
            if comp_id not in presence_map:
                presence_map[comp_id] = ComponentPresence(
                    component_type=component_type,
                    component_id=comp_id,
                    first_seen=event_time,
                    last_seen=event_time,
                    observation_count=1,
                    active_dates={obs_date},
                )
            else:
                p = presence_map[comp_id]
                p.last_seen = max(p.last_seen, event_time)
                p.first_seen = min(p.first_seen, event_time)
                p.observation_count += 1
                p.active_dates.add(obs_date)

        return presence_map
