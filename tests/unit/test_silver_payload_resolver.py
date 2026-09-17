"""Unit tests for Silver payload resolver and normalizers (Phase 6)."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from pipelines.normalization.normalizers import (
    compute_configuration_hash,
    create_silver_records,
)
from pipelines.normalization.payload_resolver import (
    CanonicalFramePayloadResolver,
)
from pipelines.validation.dictionary import DictionaryRegistry


def test_payload_resolver_case_a_and_b() -> None:
    registry = DictionaryRegistry.load(Path("data/dictionaries"))
    resolver = CanonicalFramePayloadResolver(registry)

    headers = [
        "Charger Id",
        "OCPP Id",
        "Charging Station",
        "Logged At Time",
        "L1-N Voltage",
        "Neutral Voltage",
        "Connector No",
        "Gun Temp Dc+",
    ]

    # Two rows: identical voltage (Case A), one null Neutral Voltage (Case B)
    rows = [
        {
            "Charger Id": "CH-001",
            "OCPP Id": "OCPP-001",
            "Charging Station": "Station A",
            "Logged At Time": "16-09-2026 10:00:00",
            "L1-N Voltage": "230.5",
            "Neutral Voltage": "2.1",
            "Connector No": "1",
            "Gun Temp Dc+": "35.5",
        },
        {
            "Charger Id": "CH-001",
            "OCPP Id": "OCPP-001",
            "Charging Station": "Station A",
            "Logged At Time": "16-09-2026 10:00:00",
            "L1-N Voltage": "230.5",
            "Neutral Voltage": "",
            "Connector No": "1",
            "Gun Temp Dc+": "35.5",
        },
    ]

    payload = resolver.resolve_frame(
        frame_id=uuid.uuid4(),
        charger_id="CH-001",
        event_time=dt.datetime.now(dt.UTC),
        frame_sequence=0,
        raw_rows=rows,
        headers=headers,
    )

    assert not payload.conflicts
    assert payload.charger_telemetry["l1_n_voltage"].normalized_value == 230.5
    assert payload.charger_telemetry["neutral_voltage"].normalized_value == 2.1
    assert payload.connector_telemetry[1]["gun_temp_dc_positive"].normalized_value == 35.5


def test_payload_resolver_case_c_conflict() -> None:
    registry = DictionaryRegistry.load(Path("data/dictionaries"))
    resolver = CanonicalFramePayloadResolver(registry)

    headers = [
        "Charger Id",
        "L1-N Voltage",
        "Connector No",
    ]

    # Two rows with conflicting L1-N Voltage (230.5 vs 245.0)
    rows = [
        {"Charger Id": "CH-001", "L1-N Voltage": "230.5", "Connector No": "1"},
        {"Charger Id": "CH-001", "L1-N Voltage": "245.0", "Connector No": "1"},
    ]

    payload = resolver.resolve_frame(
        frame_id=uuid.uuid4(),
        charger_id="CH-001",
        event_time=dt.datetime.now(dt.UTC),
        frame_sequence=0,
        raw_rows=rows,
        headers=headers,
    )

    assert len(payload.conflicts) == 1
    assert payload.conflicts[0]["field"] == "l1_n_voltage"
    # Case C: normalized value must be None, never averaged or guessed!
    assert payload.charger_telemetry["l1_n_voltage"].normalized_value is None
    assert payload.charger_telemetry["l1_n_voltage"].has_conflict is True


def test_payload_resolver_sentinel_masking() -> None:
    registry = DictionaryRegistry.load(Path("data/dictionaries"))
    resolver = CanonicalFramePayloadResolver(registry)

    headers = [
        "Charger Id",
        "Connector No",
        "Gun Temp Dc+",
    ]

    # Row with gun thermocouple sentinel (999.0)
    rows = [
        {"Charger Id": "CH-001", "Connector No": "1", "Gun Temp Dc+": "999.0"},
    ]

    payload = resolver.resolve_frame(
        frame_id=uuid.uuid4(),
        charger_id="CH-001",
        event_time=dt.datetime.now(dt.UTC),
        frame_sequence=0,
        raw_rows=rows,
        headers=headers,
    )

    assert len(payload.sentinels_masked) == 1
    res = payload.connector_telemetry[1]["gun_temp_dc_positive"]
    assert res.normalized_value is None  # Masked!
    assert res.masked_sentinel is True
    assert res.raw_value == "999.0"  # Raw preserved!


def test_duplicate_stop_reason_disambiguation() -> None:
    registry = DictionaryRegistry.load(Path("data/dictionaries"))
    resolver = CanonicalFramePayloadResolver(registry)

    # Pos 144: occ 1 (Connector 1), Pos 210: occ 2 (Connector 2)
    # Replicate headers array with 250 headers
    headers = [f"Header_{i}" for i in range(250)]
    headers[0] = "Charger Id"
    headers[128] = "Connector No"
    headers[143] = "Last Charge Session Stop Reason"
    headers[209] = "Last Charge Session Stop Reason"

    rows = [
        {
            "Charger Id": "CH-001",
            "Connector No": "1",
            "Last Charge Session Stop Reason": "Local",
        },
        {
            "Charger Id": "CH-001",
            "Connector No": "2",
            "Last Charge Session Stop Reason": "EmergencyStop",
        },
    ]

    payload = resolver.resolve_frame(
        frame_id=uuid.uuid4(),
        charger_id="CH-001",
        event_time=dt.datetime.now(dt.UTC),
        frame_sequence=0,
        raw_rows=rows,
        headers=headers,
    )

    models, _ = create_silver_records(payload, source_file_id=uuid.uuid4())
    sessions = [
        m for m in models if getattr(m, "__tablename__", "") == "silver_session_observation"
    ]
    assert len(sessions) == 2
    sess_by_conn = {s.connector_id: s for s in sessions}
    assert sess_by_conn[1].stop_reason == "Local"
    assert sess_by_conn[2].stop_reason == "EmergencyStop"


def test_config_hash_determinism() -> None:
    config_a = {"charging_start_method": "APP", "charging_mode": "Auto"}
    config_b = {"charging_mode": "Auto", "charging_start_method": "APP"}
    config_c = {"charging_start_method": "RFID", "charging_mode": "Auto"}

    hash_a = compute_configuration_hash(config_a)
    hash_b = compute_configuration_hash(config_b)
    hash_c = compute_configuration_hash(config_c)

    assert hash_a == hash_b  # Key order independent!
    assert hash_a != hash_c
