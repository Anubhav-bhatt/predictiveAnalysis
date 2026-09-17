"""Integration tests for Phase 9 ResearchService and scientific pattern discovery."""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.discrete_events import AlarmEvent, ChargingSessionEvent
from backend.app.models.enums import (
    AlarmSeverity,
    AnalyticalGrain,
    EventConfidence,
    PatternEvidenceLevel,
    TerminationClass,
)
from backend.app.models.silver_telemetry import SilverChargerTelemetry
from backend.app.services.factory import build_research_service

pytestmark = pytest.mark.integration


async def test_research_service_end_to_end(
    session: AsyncSession,
) -> None:
    """End-to-end integration test of ResearchService."""
    charger_id = "CH_RES_INT_01"
    t0 = dt.datetime(2026, 9, 1, 10, 0, 0, tzinfo=dt.UTC)

    # 1. Seed SilverChargerTelemetry records across 5 timepoints with low voltage anomaly
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
                l1_n_voltage=185.0,  # Below 200V threshold -> voltage anomaly
                l2_n_voltage=188.0,
                l3_n_voltage=187.0,
                line_1_input_current=45.0,
                line_2_input_current=46.0,
                line_3_input_current=15.0,  # Imbalance vs L1/L2
                cabinet_temperature=42.0,
            )
        )

    # 2. Seed a charging session event
    session.add(
        ChargingSessionEvent(
            id=uuid4(),
            charger_id=charger_id,
            connector_id=1,
            start_time=t0,
            end_time=t0 + dt.timedelta(minutes=8),
            duration_seconds=480.0,
            energy_delivered_kwh=12.5,
            confidence=EventConfidence.HIGH,
            has_gap=False,
            termination_class=TerminationClass.NORMAL,
            start_soc=20.0,
            end_soc=80.0,
        )
    )

    # 3. Seed an alarm event
    session.add(
        AlarmEvent(
            id=uuid4(),
            charger_id=charger_id,
            alarm_code="ERR_UNDERVOLT",
            alarm_name="Undervoltage Alarm",
            start_time=t0,
            end_time=t0 + dt.timedelta(minutes=4),
            duration_seconds=240.0,
            confidence=EventConfidence.HIGH,
            is_open=False,
            severity=AlarmSeverity.WARNING,
        )
    )

    await session.commit()

    svc = build_research_service(session)

    # 4. Test fleet EDA summary
    eda = await svc.get_fleet_eda_summary()
    assert eda.total_chargers >= 1
    assert eda.total_observations >= 5
    assert eda.total_sessions >= 1
    assert eda.total_alarms >= 1
    assert eda.temporal_span_start is not None
    assert eda.temporal_span_end is not None

    # 5. Test data readiness
    readiness = await svc.get_data_readiness()
    assert readiness.charger_count >= 1
    assert readiness.observation_count >= 5
    assert readiness.session_count >= 1
    assert readiness.overall_readiness in ("NOT_READY", "PARTIAL", "READY", "ADEQUATE")

    # 6. Test signal statistics
    stats = await svc.get_signal_statistics(charger_id)
    assert len(stats) > 0
    v1_stat = next((s for s in stats if s.signal_name == "l1_n_voltage"), None)
    assert v1_stat is not None
    assert v1_stat.non_null_count == 5
    assert v1_stat.mean == 185.0
    assert v1_stat.min_val == 185.0

    # 7. Test cross-signal correlations
    corrs = await svc.get_signal_correlations(charger_id)
    assert len(corrs.signal_names) > 0

    # 8. Test pattern scanning
    scan_res = await svc.scan_patterns(charger_id)
    assert scan_res.charger_id == charger_id
    assert scan_res.candidates_found >= 1
    assert scan_res.candidates_persisted == scan_res.candidates_found

    # 9. Test pattern queries
    patterns = await svc.get_pattern_candidates(charger_id)
    assert len(patterns) >= 1
    p0 = patterns[0]
    assert p0.charger_id == charger_id
    assert p0.confidence_score > 0.0

    # Test filtering
    filtered = await svc.get_pattern_candidates(
        charger_id,
        evidence_level=PatternEvidenceLevel.OBSERVATION.value,
    )
    assert all(p.evidence_level == PatternEvidenceLevel.OBSERVATION.value for p in filtered)

    # 10. Test dataset building
    ds_res = await svc.build_dataset(charger_id, grain=AnalyticalGrain.CHARGER_TIME)
    assert ds_res.charger_id == charger_id
    assert ds_res.grain == "CHARGER_TIME"
    assert ds_res.record_count >= 1
    assert ds_res.signal_count >= 1
