"""Silver table model builders and configuration hashing (Phase 6).

Transforms a ResolvedFramePayload into instantiated SQLAlchemy models ready for
persistence in the 11 typed Silver domain tables, plus comprehensive provenance records.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from backend.app.models.silver_telemetry import (
    SilverAlarmObservation,
    SilverChargerTelemetry,
    SilverCommunicationObservation,
    SilverConfigurationSnapshot,
    SilverConnectorTelemetry,
    SilverContactorObservation,
    SilverLifecycleCounterObservation,
    SilverObservationProvenance,
    SilverRectifierTelemetry,
    SilverSessionObservation,
    SilverSiteMetadata,
    SilverSmrTelemetry,
)
from pipelines.normalization.payload_resolver import FieldResolution, ResolvedFramePayload

__all__ = [
    "compute_configuration_hash",
    "create_silver_records",
]


def compute_configuration_hash(config_dict: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 over canonicalized key-value pairs.

    Excludes file and batch IDs to ensure hash reflects only device configuration.
    """
    sorted_pairs = sorted((k, str(v)) for k, v in config_dict.items() if v is not None)
    serialized = json.dumps(sorted_pairs, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _format_norm_val(val: Any) -> str | None:
    return str(val) if val is not None else None


def _make_provenance(
    *,
    table_name: str,
    record_id: uuid.UUID,
    frame_id: uuid.UUID,
    bronze_row_id: uuid.UUID | None,
    source_file_id: uuid.UUID,
    cname: str,
    res: FieldResolution,
) -> SilverObservationProvenance:
    return SilverObservationProvenance(
        silver_table_name=table_name,
        silver_record_id=record_id,
        frame_id=frame_id,
        bronze_row_id=bronze_row_id,
        source_file_id=source_file_id,
        source_position=res.source_position,
        canonical_name=cname,
        raw_value=res.raw_value,
        normalized_value=_format_norm_val(res.normalized_value),
        transformation_applied=res.transformation_applied,
        masked_sentinel=res.masked_sentinel,
    )


def create_silver_records(
    payload: ResolvedFramePayload,
    *,
    source_file_id: uuid.UUID,
    bronze_row_id: uuid.UUID | None = None,
) -> tuple[list[Any], list[SilverObservationProvenance]]:
    """Build Silver entity models and provenance records from resolved payload."""
    records: list[Any] = []
    provenance: list[SilverObservationProvenance] = []

    f_id = payload.frame_id
    c_id = payload.charger_id
    e_time = payload.event_time
    f_seq = payload.frame_sequence

    # 1. Site Metadata
    site_meta_id = uuid.uuid4()
    site_meta = SilverSiteMetadata(
        id=site_meta_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    for cname, res in payload.site_metadata.items():
        if hasattr(site_meta, cname):
            setattr(site_meta, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_site_metadata",
                record_id=site_meta_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(site_meta)

    # 2. Charger Telemetry
    charger_telem_id = uuid.uuid4()
    charger_telem = SilverChargerTelemetry(
        id=charger_telem_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    for cname, res in payload.charger_telemetry.items():
        if hasattr(charger_telem, cname):
            setattr(charger_telem, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_charger_telemetry",
                record_id=charger_telem_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(charger_telem)

    # 3. Connector Telemetry (per connector)
    for conn_id, fields in payload.connector_telemetry.items():
        conn_telem_id = uuid.uuid4()
        conn_telem = SilverConnectorTelemetry(
            id=conn_telem_id,
            charger_id=c_id,
            connector_id=conn_id,
            event_time=e_time,
            frame_sequence=f_seq,
            frame_id=f_id,
        )
        for cname, res in fields.items():
            if hasattr(conn_telem, cname):
                setattr(conn_telem, cname, res.normalized_value)
            if cname == "gun_temp_dc_positive":
                conn_telem.gun_temp_dc_positive_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                conn_telem.gun_temp_dc_positive_masked = res.masked_sentinel
            elif cname == "gun_temp_dc_negative":
                conn_telem.gun_temp_dc_negative_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                conn_telem.gun_temp_dc_negative_masked = res.masked_sentinel

            provenance.append(
                _make_provenance(
                    table_name="silver_connector_telemetry",
                    record_id=conn_telem_id,
                    frame_id=f_id,
                    bronze_row_id=bronze_row_id,
                    source_file_id=source_file_id,
                    cname=cname,
                    res=res,
                )
            )
        records.append(conn_telem)

    # 4. Rectifier Telemetry (per rectifier)
    for rect_id, fields in payload.rectifier_telemetry.items():
        rect_telem_id = uuid.uuid4()
        rect_telem = SilverRectifierTelemetry(
            id=rect_telem_id,
            charger_id=c_id,
            rectifier_id=rect_id,
            event_time=e_time,
            frame_sequence=f_seq,
            frame_id=f_id,
        )
        for cname, res in fields.items():
            if hasattr(rect_telem, cname):
                setattr(rect_telem, cname, res.normalized_value)
            if cname == "rectifier_internal_temp":
                rect_telem.rectifier_internal_temp_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                rect_telem.rectifier_internal_temp_masked = res.masked_sentinel
            elif cname == "rect_max_temperature":
                rect_telem.rect_max_temperature_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                rect_telem.rect_max_temperature_masked = res.masked_sentinel

            provenance.append(
                _make_provenance(
                    table_name="silver_rectifier_telemetry",
                    record_id=rect_telem_id,
                    frame_id=f_id,
                    bronze_row_id=bronze_row_id,
                    source_file_id=source_file_id,
                    cname=cname,
                    res=res,
                )
            )
        records.append(rect_telem)

    # 5. SMR Telemetry (per SMR)
    for smr_id, fields in payload.smr_telemetry.items():
        smr_telem_id = uuid.uuid4()
        smr_telem = SilverSmrTelemetry(
            id=smr_telem_id,
            charger_id=c_id,
            smr_id=smr_id,
            event_time=e_time,
            frame_sequence=f_seq,
            frame_id=f_id,
        )
        for cname, res in fields.items():
            if hasattr(smr_telem, cname):
                setattr(smr_telem, cname, res.normalized_value)
            if cname == "smr_dc_dc_temperature":
                smr_telem.smr_dc_dc_temperature_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                smr_telem.smr_dc_dc_temperature_masked = res.masked_sentinel
            elif cname == "smr_pfc_temperature":
                smr_telem.smr_pfc_temperature_raw = float(res.raw_value) if res.raw_value else None
                smr_telem.smr_pfc_temperature_masked = res.masked_sentinel
            elif cname == "smr_rectifierinternal_temp":
                smr_telem.smr_rectifierinternal_temp_raw = (
                    float(res.raw_value) if res.raw_value else None
                )
                smr_telem.smr_rectifierinternal_temp_masked = res.masked_sentinel
            elif cname == "smrdcdc_temperature":
                smr_telem.smrdcdc_temperature_raw = float(res.raw_value) if res.raw_value else None
                smr_telem.smrdcdc_temperature_masked = res.masked_sentinel
            elif cname == "smrpfc_temperature":
                smr_telem.smrpfc_temperature_raw = float(res.raw_value) if res.raw_value else None
                smr_telem.smrpfc_temperature_masked = res.masked_sentinel

            provenance.append(
                _make_provenance(
                    table_name="silver_smr_telemetry",
                    record_id=smr_telem_id,
                    frame_id=f_id,
                    bronze_row_id=bronze_row_id,
                    source_file_id=source_file_id,
                    cname=cname,
                    res=res,
                )
            )
        records.append(smr_telem)

    # 6. Contactor Observation
    contactor_obs_id = uuid.uuid4()
    contactor_obs = SilverContactorObservation(
        id=contactor_obs_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    for cname, res in payload.contactor_observation.items():
        if hasattr(contactor_obs, cname):
            setattr(contactor_obs, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_contactor_observation",
                record_id=contactor_obs_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(contactor_obs)

    # 7. Alarm Observation
    alarm_obs_id = uuid.uuid4()
    alarm_obs = SilverAlarmObservation(
        id=alarm_obs_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    active_alarms: list[str] = []
    for cname, res in payload.alarm_observation.items():
        if hasattr(alarm_obs, cname):
            setattr(alarm_obs, cname, res.normalized_value)
        if res.raw_value and res.raw_value.lower() in ("alarm", "trip", "active", "1", "true"):
            active_alarms.append(cname)
        provenance.append(
            _make_provenance(
                table_name="silver_alarm_observation",
                record_id=alarm_obs_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    alarm_obs.active_alarms_count = len(active_alarms)
    alarm_obs.active_alarm_codes = {"codes": active_alarms} if active_alarms else None
    records.append(alarm_obs)

    # 8. Session Observation (per connector)
    for conn_id, fields in payload.session_observation.items():
        sess_obs_id = uuid.uuid4()
        sess_obs = SilverSessionObservation(
            id=sess_obs_id,
            charger_id=c_id,
            connector_id=conn_id,
            event_time=e_time,
            frame_sequence=f_seq,
            frame_id=f_id,
        )
        for cname, res in fields.items():
            if hasattr(sess_obs, cname):
                setattr(sess_obs, cname, res.normalized_value)
            if cname in (
                "last_charge_session_stop_reason",
                "last_charge_session_stop_reason_secondary",
            ):
                sess_obs.stop_reason = str(res.normalized_value) if res.normalized_value else None

            provenance.append(
                _make_provenance(
                    table_name="silver_session_observation",
                    record_id=sess_obs_id,
                    frame_id=f_id,
                    bronze_row_id=bronze_row_id,
                    source_file_id=source_file_id,
                    cname=cname,
                    res=res,
                )
            )
        records.append(sess_obs)

    # 9. Lifecycle Counters
    lifecycle_obs_id = uuid.uuid4()
    lifecycle_obs = SilverLifecycleCounterObservation(
        id=lifecycle_obs_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    for cname, res in payload.lifecycle_counters.items():
        if hasattr(lifecycle_obs, cname):
            setattr(lifecycle_obs, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_lifecycle_counter_observation",
                record_id=lifecycle_obs_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(lifecycle_obs)

    # 10. Communication Observation
    comm_obs_id = uuid.uuid4()
    comm_obs = SilverCommunicationObservation(
        id=comm_obs_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
    )
    for cname, res in payload.communication_observation.items():
        if hasattr(comm_obs, cname):
            setattr(comm_obs, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_communication_observation",
                record_id=comm_obs_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(comm_obs)

    # 11. Configuration Snapshot
    config_dict = {
        cname: res.normalized_value for cname, res in payload.configuration_snapshot.items()
    }
    config_hash = compute_configuration_hash(config_dict)
    config_snap_id = uuid.uuid4()
    config_snap = SilverConfigurationSnapshot(
        id=config_snap_id,
        charger_id=c_id,
        event_time=e_time,
        frame_sequence=f_seq,
        frame_id=f_id,
        config_hash=config_hash,
        raw_config_json=config_dict if config_dict else None,
    )
    for cname, res in payload.configuration_snapshot.items():
        if hasattr(config_snap, cname):
            setattr(config_snap, cname, res.normalized_value)
        provenance.append(
            _make_provenance(
                table_name="silver_configuration_snapshot",
                record_id=config_snap_id,
                frame_id=f_id,
                bronze_row_id=bronze_row_id,
                source_file_id=source_file_id,
                cname=cname,
                res=res,
            )
        )
    records.append(config_snap)

    return records, provenance
