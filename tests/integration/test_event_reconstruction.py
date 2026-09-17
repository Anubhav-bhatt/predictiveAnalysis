"""End-to-end integration tests for Phase 8 Discrete Event Reconstruction.

Verifies:
1. Reconstruction of charging sessions from Silver connector telemetry with state transitions.
2. Contiguous alarm span aggregation and open/closed interval tracking.
3. Telemetry gap awareness (has_gap flag, confidence lowering).
4. Idempotent windowed recomputation (re-running reconstruction leaves no duplicate records).
5. ResearchDataAccessLayer.get_telemetry_with_events analytical joins.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.models.enums import EventConfidence
from backend.app.models.silver_telemetry import (
    SilverAlarmObservation,
    SilverChargerTelemetry,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverSessionObservation,
)
from backend.app.services.factory import build_event_service, build_research_access
from backend.app.services.research_access import SignalTarget
from pipelines.persistence.storage import LocalFilesystemRawStorage
from pipelines.validation.dictionary import DictionaryRegistry

if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.integration


@pytest.fixture
def dictionary(settings: Settings) -> DictionaryRegistry:
    return DictionaryRegistry.load(
        settings.project_root / "data" / "dictionaries",
        contracts_dir=settings.project_root / "data" / "contracts",
    )


async def test_e2e_event_reconstruction_and_idempotency(
    session: AsyncSession,
    settings: Settings,
    storage: LocalFilesystemRawStorage,
    dictionary: DictionaryRegistry,
) -> None:
    """Verify event reconstruction creates valid events and is idempotent."""
    charger_id = "CH_EVT_01"
    t0 = dt.datetime(2026, 9, 1, 10, 0, 0, tzinfo=dt.UTC)

    # 1. Seed Silver telemetry simulating a clean charging session
    # Preparing (10:00) -> Charging (10:05) -> Finishing (10:20) -> Available (10:25)
    states = [
        (t0, 1, "Preparing", 0.0, 20.0, None),
        (t0 + dt.timedelta(minutes=5), 2, "Charging", 2.0, 30.0, None),
        (t0 + dt.timedelta(minutes=10), 3, "Charging", 7.5, 55.0, None),
        (t0 + dt.timedelta(minutes=15), 4, "Charging", 12.0, 80.0, None),
        (t0 + dt.timedelta(minutes=20), 5, "Finishing", 12.2, 80.0, "EVDisconnected"),
        (t0 + dt.timedelta(minutes=25), 6, "Available", 12.2, 80.0, None),
    ]

    for event_time, seq, status_str, energy, soc, stop_reason in states:
        f_id = uuid4()
        session.add(
            SilverConnectorTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                connector_status=status_str,
                plug_status="Connected" if status_str != "Available" else "Disconnected",
            )
        )
        session.add(
            SilverSessionObservation(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                session_id=1001.0,
                session_consumed_energy=energy,
                start_soc=soc if status_str == "Preparing" else None,
                stop_soc=soc if status_str in ("Finishing", "Available") else None,
                stop_reason=stop_reason,
            )
        )

    # 2. Seed SilverAlarmObservation: an alarm that triggers at 10:05 and clears at 10:15
    f_alm1 = uuid4()
    f_alm2 = uuid4()
    f_alm3 = uuid4()
    session.add(
        SilverAlarmObservation(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=5),
            frame_sequence=2,
            frame_id=f_alm1,
            door_open="1",
        )
    )
    session.add(
        SilverAlarmObservation(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=10),
            frame_sequence=3,
            frame_id=f_alm2,
            door_open="1",
        )
    )
    session.add(
        SilverAlarmObservation(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=15),
            frame_sequence=4,
            frame_id=f_alm3,
            door_open="0",
        )
    )

    # 3. Seed Configuration Snapshots: diff between hash A and hash B
    f_cfg1 = uuid4()
    f_cfg2 = uuid4()
    session.add(
        SilverConfigurationSnapshot(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0,
            frame_sequence=1,
            frame_id=f_cfg1,
            config_hash="HASH_A",
            raw_config_json={"max_current": 32, "voltage_limit": 500},
        )
    )
    session.add(
        SilverConfigurationSnapshot(
            id=uuid4(),
            charger_id=charger_id,
            event_time=t0 + dt.timedelta(minutes=12),
            frame_sequence=3,
            frame_id=f_cfg2,
            config_hash="HASH_B",
            raw_config_json={"max_current": 64, "voltage_limit": 500},
        )
    )

    await session.commit()

    # 4. Run Event Reconstruction via EventReconstructionService
    service = build_event_service(session)
    outcome1 = await service.reconstruct_charger_events(charger_id)

    assert outcome1.charger_id == charger_id
    assert outcome1.sessions_reconstructed == 1
    assert outcome1.alarms_reconstructed == 1
    assert outcome1.configuration_changes_reconstructed == 1
    assert outcome1.state_transitions_reconstructed > 0

    # Verify session persisted correctly
    sessions = await service.get_sessions(charger_id)
    assert len(sessions) == 1
    sess = sessions[0]
    assert sess.charger_id == charger_id
    assert sess.connector_id == 1
    assert sess.start_time == t0
    assert sess.end_time == t0 + dt.timedelta(minutes=25)
    assert sess.duration_seconds == 1500.0
    assert sess.energy_delivered_kwh == 12.2
    assert sess.start_soc == 20.0
    assert sess.end_soc == 80.0
    assert sess.stop_reason == "EVDisconnected"
    assert sess.confidence == EventConfidence.HIGH
    assert sess.has_gap is False

    # Verify alarm persisted correctly
    alarms = await service.get_alarms(charger_id)
    assert len(alarms) == 1
    alm = alarms[0]
    assert alm.charger_id == charger_id
    assert alm.alarm_code == "door_open"
    assert alm.start_time == t0 + dt.timedelta(minutes=5)
    assert alm.end_time == t0 + dt.timedelta(minutes=15)
    assert alm.duration_seconds == 600.0
    assert alm.is_open is False

    # Verify unified timeline
    timeline = await service.get_unified_timeline(charger_id)
    assert len(timeline) >= 3
    # Check that events are chronologically sorted
    times = [item.event_time for item in timeline]
    assert times == sorted(times)

    # 5. TEST IDEMPOTENCY: Re-run reconstruction for the exact same charger
    outcome2 = await service.reconstruct_charger_events(charger_id)
    assert outcome2.sessions_reconstructed == 1
    assert outcome2.alarms_reconstructed == 1
    assert outcome2.configuration_changes_reconstructed == 1

    # Check that database row counts did NOT duplicate
    sessions_after = await service.get_sessions(charger_id)
    assert len(sessions_after) == 1
    alarms_after = await service.get_alarms(charger_id)
    assert len(alarms_after) == 1


async def test_gap_aware_session_reconstruction(
    session: AsyncSession,
) -> None:
    """Verify that a session crossing a telemetry gap is flagged with has_gap=True."""
    charger_id = "CH_GAP_TEST"
    t0 = dt.datetime(2026, 9, 1, 12, 0, 0, tzinfo=dt.UTC)

    # Session starts at 12:00, gap from 12:04 to 12:40 (36 min outage), ends at 12:45
    obs = [
        (t0, 1, "Charging", 5.0, 40.0),
        (t0 + dt.timedelta(minutes=4), 2, "Charging", 6.5, 45.0),
        # Outage: 36 minutes gap (> default 5m / 15m threshold)
        (t0 + dt.timedelta(minutes=40), 3, "Charging", 18.0, 75.0),
        (t0 + dt.timedelta(minutes=45), 4, "Available", 18.0, 75.0),
    ]

    for event_time, seq, status_str, energy, soc in obs:
        f_id = uuid4()
        session.add(
            SilverConnectorTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                connector_status=status_str,
                plug_status="Connected" if status_str != "Available" else "Disconnected",
            )
        )
        session.add(
            SilverSessionObservation(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=event_time,
                frame_sequence=seq,
                frame_id=f_id,
                session_consumed_energy=energy,
                start_soc=soc if seq == 1 else None,
                stop_soc=soc if status_str == "Available" else None,
            )
        )

    await session.commit()

    service = build_event_service(session)
    outcome = await service.reconstruct_charger_events(charger_id)
    assert outcome.sessions_reconstructed >= 1

    sessions = await service.get_sessions(charger_id)
    assert len(sessions) >= 1
    # Check that the session crossing the gap has has_gap flag True and MEDIUM or LOW confidence
    gapped_session = next((s for s in sessions if s.has_gap), None)
    assert gapped_session is not None
    assert gapped_session.has_gap is True
    assert gapped_session.confidence in (EventConfidence.MEDIUM, EventConfidence.LOW)
    assert "EVENT_HAS_GAP" in (gapped_session.quality_flags or [])


async def test_research_data_access_layer_analytical_join(
    session: AsyncSession,
) -> None:
    """Verify ResearchDataAccessLayer can perform analytical telemetry-event joins."""
    charger_id = "CH_JOIN_TEST"
    t0 = dt.datetime(2026, 9, 1, 14, 0, 0, tzinfo=dt.UTC)

    # Create telemetry with both cabinet voltage and connector state
    for i in range(5):
        t = t0 + dt.timedelta(minutes=i * 2)
        f_id = uuid4()
        session.add(
            SilverChargerTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                event_time=t,
                frame_sequence=i + 1,
                frame_id=f_id,
                l1_n_voltage=230.0 + i,
            )
        )
        session.add(
            SilverConnectorTelemetry(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=t,
                frame_sequence=i + 1,
                frame_id=f_id,
                connector_status="Charging" if i < 4 else "Available",
            )
        )
        session.add(
            SilverSessionObservation(
                id=uuid4(),
                charger_id=charger_id,
                connector_id=1,
                event_time=t,
                frame_sequence=i + 1,
                frame_id=f_id,
                session_id=999.0,
                session_consumed_energy=float(i * 3),
                start_soc=50.0,
                stop_soc=70.0 if i == 4 else None,
            )
        )

    await session.commit()

    # Reconstruct events
    service = build_event_service(session)
    await service.reconstruct_charger_events(charger_id)

    # Use ResearchDataAccessLayer
    research = build_research_access(session)
    sessions = await research.get_session_events(charger_id)
    assert len(sessions) == 1

    # Test get_telemetry_with_events
    signals = [SignalTarget(signal_name="l1_n_voltage", component_type=None, component_id=None)]
    joined_data = await research.get_telemetry_with_events(charger_id, signals=signals)
    assert len(joined_data) == 5

    # Check that observations during charging are aligned with active session
    for item in joined_data:
        assert item.event_time is not None
        if item.event_time < t0 + dt.timedelta(minutes=8):
            assert item.active_session_id == "999.0"
