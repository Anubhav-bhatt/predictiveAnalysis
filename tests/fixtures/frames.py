"""Deterministic frame fixtures (Phase 1D sections 54-64).

Builds small Polars frames with exactly the row patterns Phase 1D must classify,
so each rule is tested against declared intent rather than numbers copied from a
previous run.

The canonical column names match what :mod:`pipelines.profiling.column_roles`
resolves, so fixtures exercise the real role-resolution path.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

import polars as pl

from backend.app.models.enums import CanonicalDataType
from pipelines.frame_reconstruction.canonical_serializer import CanonicalSerializer
from pipelines.frame_reconstruction.reconstruction_service import (
    ReconstructionInput,
    ReconstructionOutcome,
    reconstruct,
)
from pipelines.profiling.column_roles import resolve_roles

__all__ = [
    "CHARGER",
    "FIELD_TYPES",
    "T0",
    "build_frame",
    "make_row",
    "run_reconstruction",
]

CHARGER = "D82510560390014"
T0 = dt.datetime(2026, 7, 27, 21, 20, 20, tzinfo=dt.UTC)

#: Column set: the four identity roles plus a handful of telemetry fields whose
#: values decide frame equality.
COLUMNS: tuple[str, ...] = (
    "charger_id",
    "event_time",
    "connector_no",
    "smr_no",
    "connector_status",
    "ocpp_state",
    "smr_output_current",
    "cabinet_temperature",
    "rsrp",
)

FIELD_TYPES: Mapping[str, CanonicalDataType] = {
    "charger_id": CanonicalDataType.IDENTIFIER,
    "event_time": CanonicalDataType.DATETIME,
    "connector_no": CanonicalDataType.IDENTIFIER,
    "smr_no": CanonicalDataType.IDENTIFIER,
    "connector_status": CanonicalDataType.ENUM,
    "ocpp_state": CanonicalDataType.ENUM,
    "smr_output_current": CanonicalDataType.FLOAT,
    "cabinet_temperature": CanonicalDataType.FLOAT,
    "rsrp": CanonicalDataType.INTEGER,
}


def make_row(
    *,
    connector: str | None,
    smr: str | None,
    connector_status: str = "Idle",
    ocpp_state: str = "Available",
    output_current: str = "12.5",
    cabinet_temperature: str = "42",
    rsrp: str = "-83",
    charger_id: str = CHARGER,
    event_time: dt.datetime = T0,
) -> dict[str, str | None]:
    """One raw row. Every value is text, as the profiler reads it."""
    return {
        "charger_id": charger_id,
        "event_time": event_time.strftime("%d-%m-%Y %H:%M:%S"),
        "connector_no": connector,
        "smr_no": smr,
        "connector_status": connector_status,
        "ocpp_state": ocpp_state,
        "smr_output_current": output_current,
        "cabinet_temperature": cabinet_temperature,
        "rsrp": rsrp,
    }


def normal_frame_rows(
    *,
    connectors: Sequence[str] = ("1", "2"),
    smrs: Sequence[str] = ("1", "2", "3", "4"),
    # Values are text, but `event_time` is a datetime, so the override map is a
    # union rather than str-only.
    **overrides: str | dt.datetime,
) -> list[dict[str, str | None]]:
    """One complete frame: connectors x SMRs rows, 8 for the known topology."""
    return [
        make_row(connector=connector, smr=smr, **overrides)  # type: ignore[arg-type]
        for connector in connectors
        for smr in smrs
    ]


def build_frame(rows: Sequence[Mapping[str, str | None]]) -> pl.DataFrame:
    """Assemble rows into a Utf8 Polars frame with stable column order."""
    return pl.DataFrame(
        {name: [row.get(name) for row in rows] for name in COLUMNS},
        schema=dict.fromkeys(COLUMNS, pl.Utf8),
    )


def run_reconstruction(
    rows: Sequence[Mapping[str, str | None]],
    *,
    connector_count: int | None = 2,
    smr_count: int | None = 4,
    telemetry_file_id: object = "file-a",
    event_times: Sequence[dt.datetime | None] | None = None,
    max_frames_per_timestamp: int = 64,
) -> ReconstructionOutcome:
    """Reconstruct a fixture through the real pipeline."""
    frame = build_frame(rows)
    roles = resolve_roles(list(frame.columns))
    serializer = CanonicalSerializer(
        field_types=FIELD_TYPES,
        # Identity and metadata columns are excluded from payload fingerprints:
        # two frames at the same timestamp share them by definition, so including
        # them would add no discriminating power.
        excluded_fields=frozenset({"charger_id", "event_time"}),
    )

    if event_times is None:
        parsed: list[dt.datetime | None] = []
        for row in rows:
            raw = row.get("event_time")
            parsed.append(
                dt.datetime.strptime(str(raw), "%d-%m-%Y %H:%M:%S").replace(tzinfo=dt.UTC)
                if raw
                else None
            )
        event_times = parsed

    return reconstruct(
        ReconstructionInput(
            frame=frame,
            event_times=list(event_times),
            roles=roles,
            serializer=serializer,
            telemetry_file_id=telemetry_file_id,
            charger_connector_count=connector_count,
            charger_smr_count=smr_count,
            max_frames_per_timestamp=max_frames_per_timestamp,
        )
    )
