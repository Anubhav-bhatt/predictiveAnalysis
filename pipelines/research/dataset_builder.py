"""Analytical dataset construction (Phase 9).

Transforms Silver observations + reconstructed events into typed
analytical records at various grains. Zero interpolation; gap-crossing
windows are flagged, not filled.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from typing import Any

from backend.app.models.enums import AnalyticalGrain
from pipelines.research.models import (
    AnalyticalDataset,
    AnalyticalRecord,
    DatasetMetadata,
)
from pipelines.research.signal_statistician import SignalStatistician

__all__ = ["ResearchDatasetBuilder"]


class ResearchDatasetBuilder:
    """Constructs analytical unit records from Silver telemetry and events."""

    def __init__(
        self,
        *,
        statistician: SignalStatistician | None = None,
    ) -> None:
        self._stat = statistician or SignalStatistician()

    def build_charger_time_dataset(
        self,
        charger_id: str,
        observations: list[dict[str, Any]],
        *,
        gap_intervals: list[tuple[dt.datetime, dt.datetime]] | None = None,
    ) -> AnalyticalDataset:
        """Build CHARGER_TIME grain: one record per charger over the full window.

        Aggregates all numeric signals into descriptive statistics.
        """
        t0 = time.monotonic()
        gaps = gap_intervals or []

        if not observations:
            meta = DatasetMetadata(
                grain=AnalyticalGrain.CHARGER_TIME,
                charger_id=charger_id,
                record_count=0,
                signal_count=0,
                dataset_version="v1",
                build_duration_ms=0.0,
            )
            return AnalyticalDataset(metadata=meta, records=())

        # Collect signal values
        signal_values: dict[str, list[Any]] = {}
        timestamps: list[dt.datetime] = []
        skip_keys = frozenset({"event_time", "frame_sequence", "frame_id", "charger_id", "ocpp_id"})

        for obs in observations:
            event_time = obs.get("event_time")
            if isinstance(event_time, dt.datetime):
                timestamps.append(event_time)
            for key, val in obs.items():
                if key in skip_keys:
                    continue
                if key not in signal_values:
                    signal_values[key] = []
                signal_values[key].append(val)

        # Compute per-signal statistics as features
        features: dict[str, Any] = {}
        for sig_name, vals in signal_values.items():
            stats = self._stat.compute_statistics(sig_name, vals)
            features[f"{sig_name}_mean"] = stats.mean
            features[f"{sig_name}_std"] = stats.std
            features[f"{sig_name}_min"] = stats.min_val
            features[f"{sig_name}_max"] = stats.max_val
            features[f"{sig_name}_p50"] = stats.p50
            features[f"{sig_name}_missing_rate"] = stats.missing_rate

        window_start = min(timestamps) if timestamps else None
        window_end = max(timestamps) if timestamps else None

        # Count gaps in observation window
        gap_count = 0
        for gs, ge in gaps:
            if window_start and window_end and not (ge <= window_start or gs >= window_end):
                gap_count += 1

        # Track missing signals
        missing_signals = tuple(
            sig for sig, vals in signal_values.items() if all(v is None for v in vals)
        )

        record = AnalyticalRecord(
            grain=AnalyticalGrain.CHARGER_TIME,
            charger_id=charger_id,
            window_start=window_start,
            window_end=window_end,
            features=features,
            observation_count=len(observations),
            has_gap=gap_count > 0,
            gap_count=gap_count,
            missing_signals=missing_signals,
            quality_score=1.0 - (len(missing_signals) / max(len(signal_values), 1)),
        )

        build_ms = (time.monotonic() - t0) * 1000
        meta = DatasetMetadata(
            grain=AnalyticalGrain.CHARGER_TIME,
            charger_id=charger_id,
            record_count=1,
            signal_count=len(signal_values),
            window_start=window_start,
            window_end=window_end,
            gap_count=gap_count,
            missing_rate=len(missing_signals) / max(len(signal_values), 1),
            dataset_version="v1",
            build_duration_ms=build_ms,
        )
        return AnalyticalDataset(metadata=meta, records=(record,))

    def build_session_level_dataset(
        self,
        charger_id: str,
        sessions: list[dict[str, Any]],
        *,
        pre_session_telemetry: dict[str, list[dict[str, Any]]] | None = None,
    ) -> AnalyticalDataset:
        """Build SESSION_LEVEL grain: one record per charging session.

        Each record contains session metrics (energy, duration, SOC delta,
        stop reason) and optionally pre-session telemetry summaries.
        """
        t0 = time.monotonic()
        records: list[AnalyticalRecord] = []
        pre_telem = pre_session_telemetry or {}

        for sess in sessions:
            features: dict[str, Any] = {}
            session_id = sess.get("session_id")

            features["energy_delivered_kwh"] = sess.get("energy_delivered_kwh")
            features["duration_seconds"] = sess.get("duration_seconds")
            features["start_soc"] = sess.get("start_soc")
            features["end_soc"] = sess.get("end_soc")
            features["connector_id"] = sess.get("connector_id")
            features["stop_reason"] = sess.get("stop_reason")
            features["termination_class"] = sess.get("termination_class")
            features["confidence"] = sess.get("confidence")
            features["has_gap"] = sess.get("has_gap", False)

            # SOC delta
            start_soc = sess.get("start_soc")
            end_soc = sess.get("end_soc")
            if (
                start_soc is not None
                and end_soc is not None
                and isinstance(start_soc, (int, float))
                and isinstance(end_soc, (int, float))
            ):
                features["soc_delta"] = end_soc - start_soc
            else:
                features["soc_delta"] = None

            # Efficiency proxy: kWh per minute
            energy = sess.get("energy_delivered_kwh")
            duration = sess.get("duration_seconds")
            if (
                energy is not None
                and duration is not None
                and isinstance(energy, (int, float))
                and isinstance(duration, (int, float))
                and duration > 0
            ):
                features["kwh_per_minute"] = energy / (duration / 60.0)
            else:
                features["kwh_per_minute"] = None

            # Pre-session telemetry summary if available
            pre_key = str(session_id) if session_id else None
            if pre_key and pre_key in pre_telem:
                pre_obs = pre_telem[pre_key]
                for obs in pre_obs:
                    for k, v in obs.items():
                        if k in (
                            "event_time",
                            "frame_sequence",
                            "frame_id",
                            "charger_id",
                        ):
                            continue
                        features[f"pre_session_{k}"] = v

            start_time = sess.get("start_time")
            end_time = sess.get("end_time")
            if isinstance(start_time, str):
                try:
                    start_time = dt.datetime.fromisoformat(start_time)
                except ValueError:
                    start_time = None
            if isinstance(end_time, str):
                try:
                    end_time = dt.datetime.fromisoformat(end_time)
                except ValueError:
                    end_time = None

            record = AnalyticalRecord(
                grain=AnalyticalGrain.SESSION_LEVEL,
                charger_id=charger_id,
                component_type="connector",
                component_id=sess.get("connector_id"),
                window_start=start_time if isinstance(start_time, dt.datetime) else None,
                window_end=end_time if isinstance(end_time, dt.datetime) else None,
                features=features,
                observation_count=1,
                has_gap=bool(sess.get("has_gap", False)),
                gap_count=1 if sess.get("has_gap") else 0,
                quality_score=_confidence_to_score(sess.get("confidence")),
            )
            records.append(record)

        build_ms = (time.monotonic() - t0) * 1000
        meta = DatasetMetadata(
            grain=AnalyticalGrain.SESSION_LEVEL,
            charger_id=charger_id,
            record_count=len(records),
            signal_count=0,
            dataset_version="v1",
            build_duration_ms=build_ms,
        )
        return AnalyticalDataset(metadata=meta, records=tuple(records))

    def build_event_centered_dataset(
        self,
        charger_id: str,
        events: list[dict[str, Any]],
        surrounding_telemetry: dict[str, list[dict[str, Any]]],
        *,
        gap_intervals: list[tuple[dt.datetime, dt.datetime]] | None = None,
    ) -> AnalyticalDataset:
        """Build EVENT_CENTERED grain: one record per alarm/fault with context window.

        For each event, extracts telemetry in a configurable time window
        before and after the event. Windows with gaps are flagged.
        """
        t0 = time.monotonic()
        gaps = gap_intervals or []
        records: list[AnalyticalRecord] = []

        for event in events:
            event_id = event.get("event_id") or event.get("id", "unknown")
            event_start = event.get("start_time")
            event_end = event.get("end_time")

            if isinstance(event_start, str):
                try:
                    event_start = dt.datetime.fromisoformat(event_start)
                except ValueError:
                    event_start = None
            if isinstance(event_end, str):
                try:
                    event_end = dt.datetime.fromisoformat(event_end)
                except ValueError:
                    event_end = None

            features: dict[str, Any] = {
                "event_type": event.get("event_type"),
                "alarm_code": event.get("alarm_code"),
                "fault_code": event.get("fault_code"),
                "severity": event.get("severity"),
                "duration_seconds": event.get("duration_seconds"),
                "is_open": event.get("is_open"),
            }

            # Incorporate surrounding telemetry
            telem = surrounding_telemetry.get(str(event_id), [])
            if telem:
                sig_values: dict[str, list[Any]] = {}
                for obs in telem:
                    for k, v in obs.items():
                        if k in (
                            "event_time",
                            "frame_sequence",
                            "frame_id",
                            "charger_id",
                        ):
                            continue
                        if k not in sig_values:
                            sig_values[k] = []
                        sig_values[k].append(v)

                for sig_name, vals in sig_values.items():
                    numeric = [
                        float(v)
                        for v in vals
                        if v is not None
                        and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
                    ]
                    if numeric:
                        features[f"context_{sig_name}_mean"] = sum(numeric) / len(numeric)
                        features[f"context_{sig_name}_min"] = min(numeric)
                        features[f"context_{sig_name}_max"] = max(numeric)

            # Check gap overlap
            gap_count = 0
            if isinstance(event_start, dt.datetime):
                for gs, ge in gaps:
                    event_end_check = event_end or event_start
                    if isinstance(event_end_check, dt.datetime) and not (
                        ge <= event_start or gs >= event_end_check
                    ):
                        gap_count += 1

            record = AnalyticalRecord(
                grain=AnalyticalGrain.EVENT_CENTERED,
                charger_id=charger_id,
                component_type=event.get("component_type"),
                component_id=event.get("component_id"),
                window_start=event_start if isinstance(event_start, dt.datetime) else None,
                window_end=event_end if isinstance(event_end, dt.datetime) else None,
                features=features,
                observation_count=len(telem),
                has_gap=gap_count > 0,
                gap_count=gap_count,
                quality_score=1.0,
            )
            records.append(record)

        build_ms = (time.monotonic() - t0) * 1000
        meta = DatasetMetadata(
            grain=AnalyticalGrain.EVENT_CENTERED,
            charger_id=charger_id,
            record_count=len(records),
            signal_count=0,
            dataset_version="v1",
            build_duration_ms=build_ms,
        )
        return AnalyticalDataset(metadata=meta, records=tuple(records))


def _confidence_to_score(confidence: Any) -> float:
    """Map EventConfidence enum value to a numeric quality score."""
    mapping = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4}
    return mapping.get(str(confidence), 0.5) if confidence else 0.5
