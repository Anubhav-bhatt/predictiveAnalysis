"""Deterministic synthetic charger telemetry, shaped like the real daily file.

The production-like sample is ~16.5 MB and is not committed.  Instead this
builder reproduces every *structural* characteristic that the pipeline must
handle, at a size that is cheap to generate in a test:

* 449 raw source positions
* the raw header ``Last Charge Session Stop Reason`` appearing twice
* day-first event timestamps (``27-07-2026 20:31:21``)
* the 2 connectors x 4 SMRs = 8 rows-per-timestamp grain
* replayed frames producing 16- and 24-row timestamps
* exact duplicate rows
* logical-key collisions whose values *differ* (these must never be dropped)
* ``-150`` sentinel readings on SMR internal temperature
* completely empty columns, constant columns and varying columns
* ``Not alarm`` as an explicit valid state rather than a missing value
* a telemetry gap
* a filename whose date disagrees with the telemetry date

Every builder returns a :class:`FixtureExpectation` describing exactly what it
wrote, so tests assert the profiler against declared truth rather than against
numbers copied out of a previous run.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DUPLICATE_HEADER_NAME",
    "FixtureExpectation",
    "FixtureSpec",
    "TOTAL_SOURCE_POSITIONS",
    "build_columns",
    "build_telemetry_csv",
]

TOTAL_SOURCE_POSITIONS = 449
DUPLICATE_HEADER_NAME = "Last Charge Session Stop Reason"
EVENT_TIME_FORMAT = "%d-%m-%Y %H:%M:%S"

#: Sentinel used by the real device for an unavailable SMR temperature probe.
SMR_TEMPERATURE_SENTINEL = "-150"

#: An explicit, valid alarm state.  Critically *not* a missing value - treating
#: it as one would erase the fact that the charger reported "no alarm".
NOT_ALARM = "Not alarm"

CHARGER_STATES = ("Available", "Preparing", "Charging", "Finishing", "Faulted")

# ---------------------------------------------------------------------------
# Column construction
# ---------------------------------------------------------------------------

#: Named fields with real EV-charger semantics, spanning every entity the
#: dictionary must classify.
_CORE_FIELDS: tuple[str, ...] = (
    "Event Time",
    "Charger ID",
    "OCPP ID",
    "Site ID",
    "Connector No",
    "SMR No",
    "Session ID",
    "Charger Status",
    "Connector Status",
    "Cabinet Temperature",
    "Ambient Temperature",
    "SMR RectifierinternalTemp",
    "SMR Output Voltage",
    "SMR Output Current",
    "SMR Input Voltage",
    "SMR Status",
    "Gun Temperature",
    "Gun Lock Status",
    "Session Demand Voltage",
    "Session Demand Current",
    "Session Energy Delivered",
    "Session Duration",
    "Session Start Time",
    "Session Stop Time",
    "Meter Reading",
    "Grid Voltage R Phase",
    "Grid Voltage Y Phase",
    "Grid Voltage B Phase",
    "Grid Frequency",
    "Insulation Resistance Positive",
    "Insulation Resistance Negative",
    "Contactor Status",
    "Cooling Fan Speed",
    "Cooling Fan Status",
    "CCS Communication Status",
    "PLC Link Status",
    "CAN Bus Status",
    "OCPP Connection Status",
    "Signal Strength",
    "Battery SOC",
    "Battery Voltage",
    "Firmware Version",
    "Hardware Version",
    "Total Session Counter",
    "Total Energy Counter",
    "Uptime Seconds",
)

_ALARM_FIELD_COUNT = 117
_EMPTY_FIELD_COUNT = 65


def _alarm_fields() -> list[str]:
    """117 alarm/failure flags, mirroring the real file's alarm-heavy shape."""
    subjects = (
        "SMR Over Temperature",
        "SMR Communication Loss",
        "SMR Output Over Voltage",
        "SMR Output Under Voltage",
        "SMR Fan Failure",
        "Cabinet Over Temperature",
        "Gun Over Temperature",
        "Insulation Failure",
        "Contactor Weld",
        "Contactor Open Failure",
        "Emergency Stop",
        "Door Open",
        "Surge Protection",
        "Earth Fault",
        "Input Phase Loss",
        "Input Over Voltage",
        "Input Under Voltage",
        "Meter Communication Failure",
        "CCS Communication Failure",
        "PLC Communication Failure",
        "CAN Communication Failure",
        "OCPP Disconnection",
        "Cooling System Failure",
        "Fan Failure",
        "Battery Communication Failure",
        "Isolation Monitor Failure",
        "Overload Protection",
        "Short Circuit Protection",
        "Reverse Polarity",
    )
    names: list[str] = []
    index = 0
    while len(names) < _ALARM_FIELD_COUNT:
        subject = subjects[index % len(subjects)]
        suffix = index // len(subjects)
        names.append(f"Alarm {subject}" if suffix == 0 else f"Alarm {subject} {suffix + 1}")
        index += 1
    return names


def build_columns() -> tuple[list[str], dict[str, list[str]]]:
    """Return the 449 raw header names plus a map of their intended behaviour.

    The second element groups column names by how they behave in the sample:
    ``empty`` (never populated), ``constant`` (one value all day) and ``varying``.
    Those groups are what the all-null / constant / variable classification is
    asserted against.
    """
    core = list(_CORE_FIELDS)
    alarms = _alarm_fields()
    empties = [f"Reserved Spare {i + 1}" for i in range(_EMPTY_FIELD_COUNT)]

    # Two occurrences of the same raw header - the duplicate-header case.
    duplicates = [DUPLICATE_HEADER_NAME, DUPLICATE_HEADER_NAME]

    fixed_total = len(core) + len(alarms) + len(empties) + len(duplicates)
    config_count = TOTAL_SOURCE_POSITIONS - fixed_total
    if config_count < 0:  # pragma: no cover - guarded by the assertion below
        raise ValueError("Core/alarm/empty field counts exceed the 449 position budget")
    configs = [f"Config Parameter {i + 1}" for i in range(config_count)]

    columns = core + alarms + duplicates + configs + empties
    assert len(columns) == TOTAL_SOURCE_POSITIONS, (
        f"fixture must have exactly {TOTAL_SOURCE_POSITIONS} positions, got {len(columns)}"
    )

    # Alarms sit constant at "Not alarm" for the whole day unless a test forces
    # otherwise; config parameters are constant; a handful of core fields are
    # identity constants.
    constant_core = [
        "Charger ID",
        "OCPP ID",
        "Site ID",
        "Firmware Version",
        "Hardware Version",
    ]
    varying = [c for c in core if c not in constant_core]

    behaviour = {
        "empty": empties,
        "constant": constant_core + configs + alarms,
        "varying": varying + duplicates,
    }
    return columns, behaviour


# ---------------------------------------------------------------------------
# Row generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """Declarative description of the telemetry file to synthesise."""

    charger_id: str = "D82510560390014"
    ocpp_id: str = "HYD12"
    site_id: str = "SITE-HYD-001"
    start: dt.datetime = dt.datetime(2026, 7, 27, 0, 1, 22)  # noqa: RUF009
    timestamp_count: int = 40
    interval_seconds: int = 121
    connectors: tuple[int, ...] = (1, 2)
    smrs: tuple[int, ...] = (1, 2, 3, 4)
    session_count: int = 4

    #: Timestamp indexes that receive a byte-identical second frame (pure replay
    #: -> exact duplicate rows AND logical-key collisions with equal values).
    replay_timestamp_indexes: tuple[int, ...] = (5,)
    #: Timestamp indexes that receive a second frame with *different* readings.
    #: These are the observations that must never be silently dropped.
    conflicting_timestamp_indexes: tuple[int, ...] = (7,)
    #: Timestamp index receiving two extra frames (24 rows total).
    triple_frame_indexes: tuple[int, ...] = ()

    #: Number of whole rows repeated verbatim elsewhere in the file.
    exact_duplicate_rows: int = 6

    #: Insert a telemetry gap by skipping this many samples after this index.
    gap_after_index: int | None = 20
    gap_skipped_samples: int = 15

    #: Emit the SMR temperature sentinel on every Nth row (0 disables).
    sentinel_every_n_rows: int = 37

    #: Restrict emitted connectors/SMRs to simulate missing hardware coverage.
    emit_connectors: tuple[int, ...] | None = None
    emit_smrs: tuple[int, ...] | None = None

    seed: int = 20260727


@dataclass(slots=True)
class FixtureExpectation:
    """Ground truth about the generated file, asserted by tests."""

    path: Path
    spec: FixtureSpec
    column_count: int
    row_count: int
    unique_timestamp_count: int
    event_time_min: dt.datetime
    event_time_max: dt.datetime
    exact_duplicate_row_count: int
    logical_collision_group_count: int
    conflicting_logical_group_count: int
    max_rows_per_logical_key: int
    rows_per_timestamp: dict[int, int]
    session_ids: list[str]
    sentinel_row_count: int
    empty_columns: list[str] = field(default_factory=list)
    constant_columns: list[str] = field(default_factory=list)
    varying_columns: list[str] = field(default_factory=list)
    duplicate_header_names: dict[str, int] = field(default_factory=dict)
    gap_seconds: int | None = None

    @property
    def business_date(self) -> dt.date:
        return self.event_time_min.date()


def _timestamps(spec: FixtureSpec) -> list[dt.datetime]:
    """Event timestamps, with an optional gap punched into the middle."""
    stamps: list[dt.datetime] = []
    current = spec.start
    for index in range(spec.timestamp_count):
        stamps.append(current)
        step = spec.interval_seconds
        if spec.gap_after_index is not None and index == spec.gap_after_index:
            step = spec.interval_seconds * (spec.gap_skipped_samples + 1)
        current += dt.timedelta(seconds=step)
    return stamps


def build_telemetry_csv(
    path: Path,
    spec: FixtureSpec | None = None,
    *,
    columns: Sequence[str] | None = None,
) -> FixtureExpectation:
    """Write a synthetic daily telemetry CSV and describe exactly what was written."""
    spec = spec or FixtureSpec()
    rng = random.Random(spec.seed)

    all_columns, behaviour = build_columns()
    header = list(columns) if columns is not None else all_columns
    index_of = {name: i for i, name in enumerate(header)}

    connectors = spec.emit_connectors if spec.emit_connectors is not None else spec.connectors
    smrs = spec.emit_smrs if spec.emit_smrs is not None else spec.smrs

    session_ids = [f"SESS-{spec.charger_id[-4:]}-{i + 1:03d}" for i in range(spec.session_count)]
    stamps = _timestamps(spec)

    constant_values: dict[str, str] = {
        "Charger ID": spec.charger_id,
        "OCPP ID": spec.ocpp_id,
        "Site ID": spec.site_id,
        "Firmware Version": "v3.14.2",
        "Hardware Version": "HW-REV-C",
    }

    rows: list[list[str]] = []
    sentinel_rows = 0
    row_counter = 0

    def make_row(stamp: dt.datetime, connector: int, smr: int, *, variant: int = 0) -> list[str]:
        """One raw telemetry row: one (timestamp, connector, SMR) observation."""
        nonlocal sentinel_rows, row_counter
        row = [""] * len(header)

        for name, value in constant_values.items():
            if name in index_of:
                row[index_of[name]] = value

        # Every alarm reports the explicit "Not alarm" state.
        for name in behaviour["constant"]:
            if name.startswith("Alarm ") and name in index_of:
                row[index_of[name]] = NOT_ALARM
            elif name.startswith("Config Parameter") and name in index_of:
                row[index_of[name]] = "1"

        elapsed = int((stamp - spec.start).total_seconds())
        session = session_ids[(elapsed // 3600) % len(session_ids)] if connector == 1 else ""

        # `variant` perturbs readings so a replayed frame carries genuinely
        # different values rather than an identical copy.
        jitter = variant * 0.7

        values: dict[str, str] = {
            "Event Time": stamp.strftime(EVENT_TIME_FORMAT),
            "Connector No": str(connector),
            "SMR No": str(smr),
            "Session ID": session,
            "Charger Status": CHARGER_STATES[(elapsed // 600) % len(CHARGER_STATES)],
            "Connector Status": "Charging" if session else "Available",
            "Cabinet Temperature": f"{28.5 + (elapsed % 90) / 10 + jitter:.1f}",
            "Ambient Temperature": f"{24.0 + (elapsed % 60) / 12:.1f}",
            "SMR Output Voltage": f"{398.0 + smr * 1.4 + jitter:.1f}",
            "SMR Output Current": f"{12.0 + connector * 2.0 + jitter:.2f}",
            "SMR Input Voltage": f"{415.0 + (elapsed % 7):.1f}",
            "SMR Status": "Running" if session else "Standby",
            "Gun Temperature": f"{31.0 + connector * 1.5:.1f}",
            "Gun Lock Status": "Locked" if session else "Unlocked",
            "Session Demand Voltage": f"{400.0 + (elapsed % 25):.1f}" if session else "",
            "Session Demand Current": f"{60.0 + (elapsed % 30):.1f}" if session else "",
            "Session Energy Delivered": f"{(elapsed % 3600) / 100:.3f}" if session else "",
            "Session Duration": str(elapsed % 3600) if session else "",
            "Session Start Time": stamp.strftime(EVENT_TIME_FORMAT) if session else "",
            "Session Stop Time": (
                (stamp + dt.timedelta(minutes=30)).strftime(EVENT_TIME_FORMAT) if session else ""
            ),
            "Meter Reading": f"{100000 + elapsed // 10}",
            "Grid Voltage R Phase": f"{239.5 + (elapsed % 11) / 10:.1f}",
            "Grid Voltage Y Phase": f"{240.1 + (elapsed % 13) / 10:.1f}",
            "Grid Voltage B Phase": f"{238.9 + (elapsed % 17) / 10:.1f}",
            "Grid Frequency": f"{49.9 + (elapsed % 3) / 100:.2f}",
            "Insulation Resistance Positive": f"{rng.randint(1800, 2400)}",
            "Insulation Resistance Negative": f"{rng.randint(1800, 2400)}",
            "Contactor Status": "Closed" if session else "Open",
            "Cooling Fan Speed": str(1200 + (elapsed % 400)),
            "Cooling Fan Status": "Running",
            "CCS Communication Status": "OK",
            "PLC Link Status": "Linked" if session else "Idle",
            "CAN Bus Status": "OK",
            "OCPP Connection Status": "Connected",
            "Signal Strength": f"-{rng.randint(60, 85)}",
            "Battery SOC": f"{rng.randint(20, 95)}" if session else "",
            "Battery Voltage": f"{rng.randint(350, 420)}" if session else "",
            "Total Session Counter": str(1420 + elapsed // 3600),
            "Total Energy Counter": str(892000 + elapsed // 5),
            "Uptime Seconds": str(864000 + elapsed),
        }

        # SMR internal temperature carries the -150 "probe unavailable" sentinel.
        if spec.sentinel_every_n_rows and row_counter % spec.sentinel_every_n_rows == 0:
            values["SMR RectifierinternalTemp"] = SMR_TEMPERATURE_SENTINEL
            sentinel_rows += 1
        else:
            values["SMR RectifierinternalTemp"] = f"{42.0 + smr * 2.1 + jitter:.1f}"

        for name, value in values.items():
            if name in index_of:
                row[index_of[name]] = value

        # Both occurrences of the duplicated header get values; occurrence 2 is
        # deliberately different so tests can prove they are not conflated.
        dup_positions = [i for i, name in enumerate(header) if name == DUPLICATE_HEADER_NAME]
        if len(dup_positions) >= 1:
            row[dup_positions[0]] = "EVStopped" if session else ""
        if len(dup_positions) >= 2:
            row[dup_positions[1]] = "Local" if session else ""

        row_counter += 1
        return row

    rows_per_timestamp: dict[dt.datetime, int] = {}

    for index, stamp in enumerate(stamps):
        frame = [make_row(stamp, c, s) for c in connectors for s in smrs]
        rows.extend(frame)

        extra_frames = 0
        if index in spec.replay_timestamp_indexes:
            # Byte-identical replay: same logical keys, same values.
            rows.extend([list(r) for r in frame])
            extra_frames += 1
        if index in spec.conflicting_timestamp_indexes:
            # Same logical keys, genuinely different readings.  These are the
            # observations Phase 1D must reconcile rather than discard.
            rows.extend([make_row(stamp, c, s, variant=1) for c in connectors for s in smrs])
            extra_frames += 1
        if index in spec.triple_frame_indexes:
            rows.extend([make_row(stamp, c, s, variant=2) for c in connectors for s in smrs])
            rows.extend([make_row(stamp, c, s, variant=3) for c in connectors for s in smrs])
            extra_frames += 2

        rows_per_timestamp[stamp] = len(frame) * (1 + extra_frames)

    # Verbatim whole-row duplicates scattered through the file.
    exact_duplicates = 0
    if spec.exact_duplicate_rows > 0 and rows:
        step = max(1, len(rows) // (spec.exact_duplicate_rows + 1))
        for i in range(spec.exact_duplicate_rows):
            source_index = min((i + 1) * step, len(rows) - 1)
            rows.append(list(rows[source_index]))
            exact_duplicates += 1
            stamp_text = rows[source_index][index_of["Event Time"]]
            stamp = dt.datetime.strptime(stamp_text, EVENT_TIME_FORMAT)
            rows_per_timestamp[stamp] = rows_per_timestamp.get(stamp, 0) + 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)

    # Expectations are *measured* from what was actually written, never
    # estimated - otherwise the tests would assert the builder's arithmetic
    # rather than the profiler's behaviour.
    row_tuples = [tuple(r) for r in rows]
    exact_duplicate_total = len(row_tuples) - len(set(row_tuples))

    key_positions = (index_of["Event Time"], index_of["Connector No"], index_of["SMR No"])
    groups: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for row_tuple in row_tuples:
        key = tuple(row_tuple[p] for p in key_positions)
        groups.setdefault(key, []).append(row_tuple)

    collision_total = sum(1 for members in groups.values() if len(members) > 1)
    conflicting_total = sum(1 for members in groups.values() if len(set(members)) > 1)
    max_per_key = max((len(members) for members in groups.values()), default=0)

    emitted_sessions = sorted(
        {r[index_of["Session ID"]] for r in row_tuples if r[index_of["Session ID"]]}
    )

    gap_seconds = (
        spec.interval_seconds * (spec.gap_skipped_samples + 1)
        if spec.gap_after_index is not None
        else None
    )

    return FixtureExpectation(
        path=path,
        spec=spec,
        column_count=len(header),
        row_count=len(rows),
        unique_timestamp_count=len(rows_per_timestamp),
        event_time_min=min(rows_per_timestamp),
        event_time_max=max(rows_per_timestamp),
        exact_duplicate_row_count=exact_duplicate_total,
        logical_collision_group_count=collision_total,
        conflicting_logical_group_count=conflicting_total,
        max_rows_per_logical_key=max_per_key,
        rows_per_timestamp={
            count: sum(1 for v in rows_per_timestamp.values() if v == count)
            for count in sorted(set(rows_per_timestamp.values()))
        },
        session_ids=emitted_sessions,
        sentinel_row_count=sentinel_rows,
        empty_columns=list(behaviour["empty"]),
        constant_columns=list(behaviour["constant"]),
        varying_columns=list(behaviour["varying"]),
        duplicate_header_names={DUPLICATE_HEADER_NAME: 2},
        gap_seconds=gap_seconds,
    )
