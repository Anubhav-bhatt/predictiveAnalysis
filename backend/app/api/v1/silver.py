"""Silver telemetry endpoints (Phase 6).

Provides access to normalization run execution, run metadata, and canonical
typed Silver observations for chargers and physical sub-components.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from backend.app.api.deps import (
    FileRepoDep,
    NormalizationServiceDep,
    SilverRepoDep,
)
from backend.app.schemas.common import Envelope, ok
from backend.app.schemas.silver import (
    NormalizationRunSummary,
    SilverChargerTelemetryDTO,
    SilverConnectorTelemetryDTO,
    SilverRectifierTelemetryDTO,
    SilverSmrTelemetryDTO,
)

router = APIRouter(tags=["silver"])


def _parse_uuid(raw: str, field: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} is not a valid UUID",
        ) from exc


@router.get(
    "/ingestion/files/{file_id}/normalization",
    response_model=Envelope[NormalizationRunSummary],
    summary="Get normalization execution summary for a file",
)
async def get_file_normalization(
    file_id: str,
    silver_repo: SilverRepoDep,
    file_repo: FileRepoDep,
) -> Envelope[NormalizationRunSummary]:
    parsed_id = _parse_uuid(file_id, "file_id")
    telemetry_file = await file_repo.get(parsed_id)
    if telemetry_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Telemetry file {file_id} not found",
        )

    run = await silver_repo.get_normalization_run(parsed_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No normalization run found for file {file_id}",
        )

    return ok(
        NormalizationRunSummary(
            id=run.id,
            file_id=run.file_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            frames_input=run.frames_input,
            frames_normalized=run.frames_normalized,
            frames_with_warnings=run.frames_with_warnings,
            frames_failed=run.frames_failed,
            conflicts_detected_count=run.conflicts_detected_count,
            sentinels_masked_count=run.sentinels_masked_count,
            records_created_by_table=run.records_created_by_table,
            error_message=run.error_message,
        )
    )


@router.post(
    "/ingestion/files/{file_id}/normalize",
    response_model=Envelope[NormalizationRunSummary],
    summary="Normalize canonical frames of a file into Silver layer",
)
async def normalize_file(
    file_id: str,
    service: NormalizationServiceDep,
    file_repo: FileRepoDep,
) -> Envelope[NormalizationRunSummary]:
    parsed_id = _parse_uuid(file_id, "file_id")
    telemetry_file = await file_repo.get(parsed_id)
    if telemetry_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Telemetry file {file_id} not found",
        )

    res = await service.normalize_file(telemetry_file)
    if res.run is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.skipped_reason or "Normalization failed",
        )

    run = res.run
    return ok(
        NormalizationRunSummary(
            id=run.id,
            file_id=run.file_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            frames_input=run.frames_input,
            frames_normalized=run.frames_normalized,
            frames_with_warnings=run.frames_with_warnings,
            frames_failed=run.frames_failed,
            conflicts_detected_count=run.conflicts_detected_count,
            sentinels_masked_count=run.sentinels_masked_count,
            records_created_by_table=run.records_created_by_table,
            error_message=run.error_message,
        )
    )


@router.get(
    "/chargers/{charger_id}/silver/latest",
    response_model=Envelope[SilverChargerTelemetryDTO | None],
    summary="Get latest cabinet telemetry observation for a charger",
)
async def get_latest_charger_telemetry(
    charger_id: str,
    silver_repo: SilverRepoDep,
) -> Envelope[SilverChargerTelemetryDTO | None]:
    record = await silver_repo.get_latest_charger_telemetry(charger_id)
    if record is None:
        return ok(None)

    dto = SilverChargerTelemetryDTO(
        id=record.id,
        charger_id=record.charger_id,
        event_time=record.event_time,
        frame_sequence=record.frame_sequence,
        frame_id=record.frame_id,
        ocpp_id=record.ocpp_id,
        input_voltage=record.l1_n_voltage,
        input_current=record.line_1_input_current,
        frequency=record.frequency,
        power_factor=record.power_factor,
        cabinet_temperature=record.cabinet_temperature,
        neutral_voltage=record.neutral_voltage,
        l1_n_voltage=record.l1_n_voltage,
        l2_n_voltage=record.l2_n_voltage,
        l3_n_voltage=record.l3_n_voltage,
    )
    return ok(dto)


@router.get(
    "/chargers/{charger_id}/silver/connectors",
    response_model=Envelope[list[SilverConnectorTelemetryDTO]],
    summary="Get connector telemetry observations for a charger",
)
async def get_charger_connectors(
    charger_id: str,
    silver_repo: SilverRepoDep,
) -> Envelope[list[SilverConnectorTelemetryDTO]]:
    records = await silver_repo.list_connectors_for_charger(charger_id)
    dtos = [
        SilverConnectorTelemetryDTO(
            id=r.id,
            charger_id=r.charger_id,
            connector_id=r.connector_id,
            event_time=r.event_time,
            frame_sequence=r.frame_sequence,
            frame_id=r.frame_id,
            connector_type=r.connector_type,
            connector_status=r.connector_status,
            plug_status=r.plug_status,
            gun_temp_dc_positive=r.gun_temp_dc_positive,
            gun_temp_dc_negative=r.gun_temp_dc_negative,
            gun_temp_dc_positive_raw=r.gun_temp_dc_positive_raw,
            gun_temp_dc_negative_raw=r.gun_temp_dc_negative_raw,
            gun_temp_dc_positive_masked=r.gun_temp_dc_positive_masked,
            gun_temp_dc_negative_masked=r.gun_temp_dc_negative_masked,
        )
        for r in records
    ]
    return ok(dtos)


@router.get(
    "/chargers/{charger_id}/silver/smrs",
    response_model=Envelope[list[SilverSmrTelemetryDTO]],
    summary="Get SMR modular telemetry observations for a charger",
)
async def get_charger_smrs(
    charger_id: str,
    silver_repo: SilverRepoDep,
) -> Envelope[list[SilverSmrTelemetryDTO]]:
    records = await silver_repo.list_smrs_for_charger(charger_id)
    dtos = [
        SilverSmrTelemetryDTO(
            id=r.id,
            charger_id=r.charger_id,
            smr_id=r.smr_id,
            event_time=r.event_time,
            frame_sequence=r.frame_sequence,
            frame_id=r.frame_id,
            smr_output_voltage=r.smr_output_voltage,
            smr_output_current=r.smr_output_current,
            smr_output_power=r.smr_output_power,
            smr_dc_dc_temperature=r.smr_dc_dc_temperature,
            smr_pfc_temperature=r.smr_pfc_temperature,
            smr_dc_dc_temperature_masked=r.smr_dc_dc_temperature_masked,
            smr_pfc_temperature_masked=r.smr_pfc_temperature_masked,
        )
        for r in records
    ]
    return ok(dtos)


@router.get(
    "/chargers/{charger_id}/silver/rectifiers",
    response_model=Envelope[list[SilverRectifierTelemetryDTO]],
    summary="Get rectifier telemetry observations for a charger",
)
async def get_charger_rectifiers(
    charger_id: str,
    silver_repo: SilverRepoDep,
) -> Envelope[list[SilverRectifierTelemetryDTO]]:
    records = await silver_repo.list_rectifiers_for_charger(charger_id)
    dtos = [
        SilverRectifierTelemetryDTO(
            id=r.id,
            charger_id=r.charger_id,
            rectifier_id=r.rectifier_id,
            event_time=r.event_time,
            frame_sequence=r.frame_sequence,
            frame_id=r.frame_id,
            rectifier_internal_temp=r.rectifier_internal_temp,
            rect_max_temperature=r.rect_max_temperature,
            rectifier_internal_temp_masked=r.rectifier_internal_temp_masked,
            rect_max_temperature_masked=r.rect_max_temperature_masked,
        )
        for r in records
    ]
    return ok(dtos)
