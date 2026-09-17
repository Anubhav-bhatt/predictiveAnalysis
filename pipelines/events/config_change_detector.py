"""Configuration change event detector (Phase 8).

Identifies parameter diffs and firmware/hardware state transitions between
consecutive configuration snapshots over time.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pipelines.events.models import ReconstructedConfigChange

__all__ = ["ConfigSnapshotObservation", "ConfigurationChangeDetector"]


@dataclass(frozen=True, slots=True)
class ConfigSnapshotObservation:
    """A point-in-time configuration snapshot."""

    event_time: dt.datetime
    config_hash: str
    config_json: dict[str, Any]


class ConfigurationChangeDetector:
    """Pure pipeline orchestrator for detecting configuration changes over time."""

    def __init__(self, version: str = "v1") -> None:
        self.version = version

    def detect_changes(
        self,
        charger_id: str,
        snapshots: Sequence[ConfigSnapshotObservation],
    ) -> list[ReconstructedConfigChange]:
        """Compare consecutive chronological snapshots and emit change events."""
        if len(snapshots) < 2:
            return []

        ordered = sorted(snapshots, key=lambda s: s.event_time)
        changes: list[ReconstructedConfigChange] = []

        prev = ordered[0]
        for curr in ordered[1:]:
            if curr.config_hash != prev.config_hash:
                # Calculate diff
                all_keys = sorted(set(prev.config_json.keys()) | set(curr.config_json.keys()))
                diff: dict[str, Any] = {}
                for k in all_keys:
                    old_v = prev.config_json.get(k)
                    new_v = curr.config_json.get(k)
                    if old_v != new_v:
                        diff[k] = {"old": old_v, "new": new_v}

                if diff:
                    changes.append(
                        ReconstructedConfigChange(
                            charger_id=charger_id,
                            change_time=curr.event_time,
                            old_config_hash=prev.config_hash,
                            new_config_hash=curr.config_hash,
                            changed_fields_json=diff,
                            previous_config_json=prev.config_json,
                            new_config_json=curr.config_json,
                            reconstruction_version=self.version,
                        )
                    )
            prev = curr

        return changes
