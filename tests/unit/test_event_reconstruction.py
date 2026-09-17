"""Unit test suite for Phase 8 pure event reconstruction algorithms.

Verifies charging session state machines, alarm interval aggregation, open alarms,
debounce merging, state transitions with same-second ordering, gap awareness, and
configuration change detection.
"""

from __future__ import annotations

import datetime as dt
import uuid

from backend.app.models.enums import (
    EventConfidence,
    EventQualityFlag,
    TerminationClass,
)
from pipelines.events.alarm_reconstructor import AlarmObservation, AlarmReconstructor
from pipelines.events.config_change_detector import (
    ConfigSnapshotObservation,
    ConfigurationChangeDetector,
)
from pipelines.events.models import TelemetryGapInterval
from pipelines.events.session_reconstructor import ConnectorObservation, SessionReconstructor
from pipelines.events.state_transition_detector import StateObservation, StateTransitionDetector


def test_basic_charging_session() -> None:
    """Available -> Preparing -> Charging -> Finishing -> Available produces 1 complete session."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    observations = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=1),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Preparing",
            session_id="SESS_1001",
            start_soc=20.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=2),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_1001",
            session_output_current=85.0,
            session_consumed_energy=2.5,
            start_soc=20.0,
            stop_soc=25.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=15),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_1001",
            session_output_current=80.0,
            session_consumed_energy=22.4,
            start_soc=20.0,
            stop_soc=80.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=16),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Finishing",
            session_id="SESS_1001",
            session_consumed_energy=22.4,
            stop_reason="Local",
            stop_soc=80.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=17),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
        ),
    ]

    sessions = reconstructor.reconstruct("CH_01", 1, observations)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_id == "SESS_1001"
    assert s.connector_id == 1
    assert s.start_time == t0 + dt.timedelta(minutes=1)
    assert s.end_time == t0 + dt.timedelta(minutes=17)
    assert s.duration_seconds == 16 * 60.0
    assert s.energy_delivered_kwh == 22.4
    assert s.start_soc == 20.0
    assert s.end_soc == 80.0
    assert s.stop_reason == "Local"
    assert s.termination_class == TerminationClass.USER_STOPPED
    assert s.confidence == EventConfidence.HIGH
    assert not s.has_gap


def test_multiple_sessions_same_connector() -> None:
    """Two consecutive sessions on the same connector produce two independent events."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    observations = [
        # Session 1
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_01",
            session_consumed_energy=10.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="RemoteStop",
        ),
        # Idle
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=20),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
        ),
        # Session 2
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=30),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_02",
            session_consumed_energy=15.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=45),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="EmergencyStop",
        ),
    ]

    sessions = reconstructor.reconstruct("CH_01", 1, observations)
    assert len(sessions) == 2
    assert sessions[0].session_id == "SESS_01"
    assert sessions[0].termination_class == TerminationClass.REMOTE_STOPPED
    assert sessions[1].session_id == "SESS_02"
    assert sessions[1].termination_class == TerminationClass.EMERGENCY_STOPPED


def test_session_with_telemetry_gap() -> None:
    """If telemetry drops during a session, has_gap is flagged and confidence is degraded."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    observations = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_GAP_01",
            session_consumed_energy=5.0,
        ),
        # Telemetry outage occurs from 10:05 to 10:35
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=40),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="Local",
        ),
    ]

    gaps = [
        TelemetryGapInterval(
            start_time=t0 + dt.timedelta(minutes=5),
            end_time=t0 + dt.timedelta(minutes=35),
        )
    ]

    sessions = reconstructor.reconstruct("CH_01", 1, observations, gaps=gaps)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.has_gap is True
    assert EventQualityFlag.EVENT_HAS_GAP.value in s.quality_flags
    assert s.confidence == EventConfidence.LOW


def test_session_energy_and_duration_consistency() -> None:
    """Discrepancies in meter delta and duration flag consistency quality warnings."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    observations = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_MISMATCH",
            session_consumed_energy=10.0,
            meter_energy=100.0,
            reported_charging_time=3600.0,  # Reported 1 hour
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=10),  # Observed 10 min
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            session_consumed_energy=10.0,
            meter_energy=120.0,  # Delta is 20 kWh, but consumed reported 10 kWh
            reported_charging_time=3600.0,
        ),
    ]

    sessions = reconstructor.reconstruct("CH_01", 1, observations)
    assert len(sessions) == 1
    s = sessions[0]
    assert EventQualityFlag.SESSION_ENERGY_MISMATCH.value in s.quality_flags
    assert EventQualityFlag.SESSION_DURATION_MISMATCH.value in s.quality_flags


def test_basic_alarm_interval() -> None:
    """Continuous OFF -> ON -> ON -> OFF creates exactly 1 closed alarm interval."""
    reconstructor = AlarmReconstructor()
    t0 = dt.datetime(2026, 9, 17, 12, 0, 0, tzinfo=dt.UTC)

    observations = [
        AlarmObservation(
            event_time=t0, frame_sequence=0, frame_id=uuid.uuid4(), is_active=False, state_str="0"
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=30),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=60),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=90),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=False,
            state_str="0",
        ),
    ]

    alarms = reconstructor.reconstruct_alarms(
        "CH_01", "smoke_alarm", "Smoke Alarm", "cabinet", None, observations
    )
    assert len(alarms) == 1
    a = alarms[0]
    assert a.alarm_code == "smoke_alarm"
    assert a.start_time == t0 + dt.timedelta(seconds=30)
    assert a.end_time == t0 + dt.timedelta(seconds=90)
    assert a.duration_seconds == 60.0
    assert a.is_open is False
    assert a.confidence == EventConfidence.HIGH


def test_open_alarm_event() -> None:
    """Alarm active at the end of the timeline is marked open with end_time=None."""
    reconstructor = AlarmReconstructor()
    t0 = dt.datetime(2026, 9, 17, 12, 0, 0, tzinfo=dt.UTC)

    observations = [
        AlarmObservation(
            event_time=t0, frame_sequence=0, frame_id=uuid.uuid4(), is_active=False, state_str="0"
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=30),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=60),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
    ]

    alarms = reconstructor.reconstruct_alarms(
        "CH_01", "emergency_stop", "Emergency Stop", "cabinet", None, observations
    )
    assert len(alarms) == 1
    a = alarms[0]
    assert a.is_open is True
    assert a.end_time is None
    assert a.duration_seconds == 30.0
    assert EventQualityFlag.ALARM_OPEN_ENDED.value in a.quality_flags


def test_repeated_alarm_and_debounce() -> None:
    """Without debounce, rapid flickering creates distinct events; with debounce, they merge."""
    t0 = dt.datetime(2026, 9, 17, 12, 0, 0, tzinfo=dt.UTC)
    observations = [
        AlarmObservation(
            event_time=t0, frame_sequence=0, frame_id=uuid.uuid4(), is_active=True, state_str="1"
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=False,
            state_str="0",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=15),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=25),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=False,
            state_str="0",
        ),
    ]

    # No debounce -> 2 events
    r_no_debounce = AlarmReconstructor(debounce_seconds=0.0)
    alarms_no_debounce = r_no_debounce.reconstruct_alarms(
        "CH_01", "grid_fail", "Grid Fail", "cabinet", None, observations
    )
    assert len(alarms_no_debounce) == 2

    # Debounce 10s -> gap is 5s, so they merge into 1 event
    r_debounce = AlarmReconstructor(debounce_seconds=10.0)
    alarms_debounce = r_debounce.reconstruct_alarms(
        "CH_01", "grid_fail", "Grid Fail", "cabinet", None, observations
    )
    assert len(alarms_debounce) == 1
    assert alarms_debounce[0].duration_seconds == 25.0


def test_state_transitions_respect_same_second() -> None:
    """State transition detector respects (event_time ASC, frame_sequence ASC)."""
    detector = StateTransitionDetector()
    t0 = dt.datetime(2026, 9, 17, 10, 15, 30, tzinfo=dt.UTC)

    observations = [
        StateObservation(event_time=t0, frame_sequence=0, state_val="Available"),
        StateObservation(event_time=t0, frame_sequence=1, state_val="Preparing"),
        StateObservation(
            event_time=t0 + dt.timedelta(seconds=5), frame_sequence=0, state_val="Charging"
        ),
        StateObservation(
            event_time=t0 + dt.timedelta(seconds=10), frame_sequence=0, state_val="Finishing"
        ),
    ]

    transitions = detector.detect_transitions(
        "CH_01", "connector", 1, "connector_status", observations
    )
    assert len(transitions) == 3
    assert transitions[0].from_state == "Available"
    assert transitions[0].to_state == "Preparing"
    assert transitions[0].transition_time == t0
    assert transitions[0].frame_sequence == 1

    assert transitions[1].from_state == "Preparing"
    assert transitions[1].to_state == "Charging"
    assert transitions[2].from_state == "Charging"
    assert transitions[2].to_state == "Finishing"


def test_configuration_change_detection() -> None:
    """Config change detector detects parameter diffs between consecutive snapshots."""
    detector = ConfigurationChangeDetector()
    t0 = dt.datetime(2026, 9, 17, 8, 0, 0, tzinfo=dt.UTC)

    snapshots = [
        ConfigSnapshotObservation(
            event_time=t0,
            config_hash="hash_v1",
            config_json={"firmware": "1.0.0", "max_current": 100.0, "power_limit": "60kW"},
        ),
        ConfigSnapshotObservation(
            event_time=t0 + dt.timedelta(hours=2),
            config_hash="hash_v1",
            config_json={"firmware": "1.0.0", "max_current": 100.0, "power_limit": "60kW"},
        ),
        ConfigSnapshotObservation(
            event_time=t0 + dt.timedelta(hours=4),
            config_hash="hash_v2",
            config_json={"firmware": "1.0.1", "max_current": 120.0, "power_limit": "60kW"},
        ),
    ]

    changes = detector.detect_changes("CH_01", snapshots)
    assert len(changes) == 1
    c = changes[0]
    assert c.old_config_hash == "hash_v1"
    assert c.new_config_hash == "hash_v2"
    assert c.change_time == t0 + dt.timedelta(hours=4)
    assert "firmware" in c.changed_fields_json
    assert c.changed_fields_json["firmware"] == {"old": "1.0.0", "new": "1.0.1"}
    assert c.changed_fields_json["max_current"] == {"old": 100.0, "new": 120.0}
    assert "power_limit" not in c.changed_fields_json  # Unchanged parameter excluded


def test_parallel_connector_sessions() -> None:
    """Connector 1 and Connector 2 charging simultaneously produce independent sessions."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    # Connector 1: 10:00 -> 10:30
    obs_conn1 = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_C1",
            session_consumed_energy=12.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=30),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="Local",
        ),
    ]

    # Connector 2: 10:10 -> 10:40 (overlapping)
    obs_conn2 = [
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_C2",
            session_consumed_energy=18.0,
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=40),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="RemoteStop",
        ),
    ]

    s1 = reconstructor.reconstruct("CH_01", 1, obs_conn1)
    s2 = reconstructor.reconstruct("CH_01", 2, obs_conn2)

    assert len(s1) == 1
    assert len(s2) == 1
    assert s1[0].connector_id == 1
    assert s1[0].session_id == "SESS_C1"
    assert s2[0].connector_id == 2
    assert s2[0].session_id == "SESS_C2"
    assert s1[0].start_time == t0
    assert s2[0].start_time == t0 + dt.timedelta(minutes=10)


def test_duplicate_stop_reasons_preserved() -> None:
    """Verifies duplicate stop reasons map accurately to independent connector sessions."""
    reconstructor = SessionReconstructor()
    t0 = dt.datetime(2026, 9, 17, 10, 0, 0, tzinfo=dt.UTC)

    # Connector 1 stop reason: "EmergencyStop"
    obs1 = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_1",
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="EmergencyStop",
        ),
    ]

    # Connector 2 stop reason: "RemoteStop"
    obs2 = [
        ConnectorObservation(
            event_time=t0,
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Charging",
            session_id="SESS_2",
        ),
        ConnectorObservation(
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            connector_status="Available",
            stop_reason="RemoteStop",
        ),
    ]

    res1 = reconstructor.reconstruct("CH_01", 1, obs1)
    res2 = reconstructor.reconstruct("CH_01", 2, obs2)

    assert res1[0].stop_reason == "EmergencyStop"
    assert res1[0].termination_class == TerminationClass.EMERGENCY_STOPPED
    assert res2[0].stop_reason == "RemoteStop"
    assert res2[0].termination_class == TerminationClass.REMOTE_STOPPED


def test_fault_event_reconstruction() -> None:
    """Reconstructs hardware protection trip faults with CRITICAL severity."""
    reconstructor = AlarmReconstructor()
    t0 = dt.datetime(2026, 9, 17, 14, 0, 0, tzinfo=dt.UTC)

    observations = [
        AlarmObservation(
            event_time=t0, frame_sequence=0, frame_id=uuid.uuid4(), is_active=False, state_str="0"
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=10),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=20),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=True,
            state_str="1",
        ),
        AlarmObservation(
            event_time=t0 + dt.timedelta(seconds=30),
            frame_sequence=0,
            frame_id=uuid.uuid4(),
            is_active=False,
            state_str="0",
        ),
    ]

    faults = reconstructor.reconstruct_faults(
        "CH_01", "short_circuit", "Short Circuit Protection", "cabinet", None, observations
    )
    assert len(faults) == 1
    f = faults[0]
    assert f.fault_code == "short_circuit"
    assert f.start_time == t0 + dt.timedelta(seconds=10)
    assert f.end_time == t0 + dt.timedelta(seconds=30)
    assert f.duration_seconds == 20.0
    assert f.is_open is False
