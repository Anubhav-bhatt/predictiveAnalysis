"""Canonical frame payload resolver across contributing Bronze rows (Phase 6).

Implements deterministic resolution:
- Case A: Equal values across contributing rows -> accepted
- Case B: Agreeing non-null values (some null/empty) -> non-null value accepted
- Case C: Conflicting non-null values -> conflict logged (REPEATED_FIELD_CONFLICT or
  CONNECTOR_FIELD_CONFLICT), normalized value set to NULL, raw values preserved in provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pipelines.normalization.coercion import (
    coerce_boolean,
    coerce_datetime,
    coerce_float,
    coerce_integer,
    coerce_string,
    is_gun_temp_sentinel,
    is_rectifier_temp_sentinel,
    is_smr_temp_sentinel,
)
from pipelines.validation.dictionary import DictionaryRegistry, FieldSpec

__all__ = [
    "CanonicalFramePayloadResolver",
    "FieldResolution",
    "ProvenanceItem",
    "ResolvedFramePayload",
]


@dataclass(frozen=True, slots=True)
class FieldResolution:
    """The resolved outcome for a single field."""

    canonical_name: str
    source_position: int
    raw_value: str | None
    normalized_value: Any
    transformation_applied: str | None
    masked_sentinel: bool = False
    has_conflict: bool = False
    conflict_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProvenanceItem:
    """Lineage information for one field observation."""

    silver_table_name: str
    source_position: int
    canonical_name: str
    raw_value: str | None
    normalized_value: str | None
    transformation_applied: str | None
    masked_sentinel: bool
    bronze_row_id: uuid.UUID | None = None
    source_file_id: uuid.UUID | None = None


@dataclass(slots=True)
class ResolvedFramePayload:
    """Complete decomposed and resolved payload for one source frame."""

    frame_id: uuid.UUID
    charger_id: str
    event_time: Any
    frame_sequence: int
    site_metadata: dict[str, FieldResolution] = field(default_factory=dict)
    charger_telemetry: dict[str, FieldResolution] = field(default_factory=dict)
    connector_telemetry: dict[int, dict[str, FieldResolution]] = field(default_factory=dict)
    rectifier_telemetry: dict[int, dict[str, FieldResolution]] = field(default_factory=dict)
    smr_telemetry: dict[int, dict[str, FieldResolution]] = field(default_factory=dict)
    contactor_observation: dict[str, FieldResolution] = field(default_factory=dict)
    alarm_observation: dict[str, FieldResolution] = field(default_factory=dict)
    session_observation: dict[int, dict[str, FieldResolution]] = field(default_factory=dict)
    lifecycle_counters: dict[str, FieldResolution] = field(default_factory=dict)
    communication_observation: dict[str, FieldResolution] = field(default_factory=dict)
    configuration_snapshot: dict[str, FieldResolution] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    sentinels_masked: list[dict[str, Any]] = field(default_factory=list)


class CanonicalFramePayloadResolver:
    """Resolves contributing raw rows into canonical typed Silver structures."""

    def __init__(self, registry: DictionaryRegistry) -> None:
        self._registry = registry

    def resolve_frame(
        self,
        *,
        frame_id: uuid.UUID,
        charger_id: str,
        event_time: Any,
        frame_sequence: int,
        raw_rows: list[dict[str, Any]],
        headers: list[str],
        bronze_row_ids: list[uuid.UUID | None] | None = None,
        source_file_id: uuid.UUID | None = None,
    ) -> ResolvedFramePayload:
        """Resolve all 456 positions across contributing Bronze rows for one frame."""
        payload = ResolvedFramePayload(
            frame_id=frame_id,
            charger_id=charger_id,
            event_time=event_time,
            frame_sequence=frame_sequence,
        )

        if not raw_rows:
            return payload

        # Resolve field spec for each header position
        specs_by_pos: list[tuple[int, str, FieldSpec]] = []
        counts: dict[str, int] = {}
        for pos, h in enumerate(headers, 1):
            occ = counts.get(h, 0) + 1
            counts[h] = occ
            # Handle duplicate Last Charge Session Stop Reason
            if h == "Last Charge Session Stop Reason" and pos > 150:
                occ = 2
            reg_result = self._registry.resolve(
                h, occurrence=occ, position=pos, fallback_canonical=h
            )
            specs_by_pos.append((pos, h, reg_result.spec))

        # Group rows by connector, rectifier, and smr IDs
        rows_by_connector: dict[int, list[dict[str, Any]]] = {}
        rows_by_rectifier: dict[int, list[dict[str, Any]]] = {}
        rows_by_smr: dict[int, list[dict[str, Any]]] = {}

        for row in raw_rows:
            conn_no = coerce_integer(row.get("Connector No") or row.get("connector_no")) or 1
            rect_val = row.get("Rectifier Number") or row.get("rectifier_number")
            rect_no = coerce_integer(rect_val) or 1
            smr_no = coerce_integer(row.get("Smr No.") or row.get("smr_no")) or 1

            rows_by_connector.setdefault(conn_no, []).append(row)
            rows_by_rectifier.setdefault(rect_no, []).append(row)
            rows_by_smr.setdefault(smr_no, []).append(row)

        # Resolve each position
        for pos, h, spec in specs_by_pos:
            cname = spec.canonical_name
            orig = spec.origin

            if orig == "identity.yaml":
                if cname == "charging_station":
                    resolution = self._resolve_scalar_field(pos, h, spec, raw_rows)
                    payload.site_metadata[cname] = resolution
                # Other identity fields (charger_id, etc.) are already frame-level keys

            elif orig == "charger.yaml":
                resolution = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.charger_telemetry[cname] = resolution
                if resolution.has_conflict:
                    payload.conflicts.append(
                        {
                            "field": cname,
                            "position": pos,
                            "type": "REPEATED_FIELD_CONFLICT",
                            "values": resolution.conflict_values,
                        }
                    )

            elif orig == "connector.yaml":
                # Scoped per connector
                for conn_id, conn_rows in rows_by_connector.items():
                    res = self._resolve_scalar_field(pos, h, spec, conn_rows)
                    payload.connector_telemetry.setdefault(conn_id, {})[cname] = res
                    if res.masked_sentinel:
                        payload.sentinels_masked.append(
                            {
                                "field": cname,
                                "position": pos,
                                "connector_id": conn_id,
                                "raw": res.raw_value,
                            }
                        )
                    if res.has_conflict:
                        payload.conflicts.append(
                            {
                                "field": cname,
                                "position": pos,
                                "connector_id": conn_id,
                                "type": "CONNECTOR_FIELD_CONFLICT",
                                "values": res.conflict_values,
                            }
                        )

            elif orig == "rectifier.yaml":
                # Scoped per rectifier
                for rect_id, rect_rows in rows_by_rectifier.items():
                    res = self._resolve_scalar_field(pos, h, spec, rect_rows)
                    payload.rectifier_telemetry.setdefault(rect_id, {})[cname] = res
                    if res.masked_sentinel:
                        payload.sentinels_masked.append(
                            {
                                "field": cname,
                                "position": pos,
                                "rectifier_id": rect_id,
                                "raw": res.raw_value,
                            }
                        )
                    if res.has_conflict:
                        payload.conflicts.append(
                            {
                                "field": cname,
                                "position": pos,
                                "rectifier_id": rect_id,
                                "type": "RECTIFIER_FIELD_CONFLICT",
                                "values": res.conflict_values,
                            }
                        )

            elif orig == "smr.yaml":
                # Scoped per SMR
                for smr_id, smr_rows in rows_by_smr.items():
                    res = self._resolve_scalar_field(pos, h, spec, smr_rows)
                    payload.smr_telemetry.setdefault(smr_id, {})[cname] = res
                    if res.masked_sentinel:
                        payload.sentinels_masked.append(
                            {
                                "field": cname,
                                "position": pos,
                                "smr_id": smr_id,
                                "raw": res.raw_value,
                            }
                        )
                    if res.has_conflict:
                        payload.conflicts.append(
                            {
                                "field": cname,
                                "position": pos,
                                "smr_id": smr_id,
                                "type": "SMR_FIELD_CONFLICT",
                                "values": res.conflict_values,
                            }
                        )

            elif orig == "contactor.yaml":
                res = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.contactor_observation[cname] = res
                if res.has_conflict:
                    payload.conflicts.append(
                        {
                            "field": cname,
                            "position": pos,
                            "type": "REPEATED_FIELD_CONFLICT",
                            "values": res.conflict_values,
                        }
                    )

            elif orig == "alarm.yaml":
                res = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.alarm_observation[cname] = res
                if res.has_conflict:
                    payload.conflicts.append(
                        {
                            "field": cname,
                            "position": pos,
                            "type": "REPEATED_FIELD_CONFLICT",
                            "values": res.conflict_values,
                        }
                    )

            elif orig == "session.yaml":
                # Scoped per connector
                for conn_id, conn_rows in rows_by_connector.items():
                    # Check for connector-disambiguated stop reasons
                    if cname == "last_charge_session_stop_reason" and conn_id != 1:
                        continue
                    if cname == "last_charge_session_stop_reason_secondary" and conn_id != 2:
                        continue
                    res = self._resolve_scalar_field(pos, h, spec, conn_rows)
                    payload.session_observation.setdefault(conn_id, {})[cname] = res
                    if res.has_conflict:
                        payload.conflicts.append(
                            {
                                "field": cname,
                                "position": pos,
                                "connector_id": conn_id,
                                "type": "CONNECTOR_FIELD_CONFLICT",
                                "values": res.conflict_values,
                            }
                        )

            elif orig == "counters.yaml":
                res = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.lifecycle_counters[cname] = res

            elif orig == "communication.yaml":
                res = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.communication_observation[cname] = res
                if res.has_conflict:
                    payload.conflicts.append(
                        {
                            "field": cname,
                            "position": pos,
                            "type": "REPEATED_FIELD_CONFLICT",
                            "values": res.conflict_values,
                        }
                    )

            elif orig == "configuration.yaml":
                res = self._resolve_scalar_field(pos, h, spec, raw_rows)
                payload.configuration_snapshot[cname] = res

        return payload

    def _resolve_scalar_field(
        self,
        position: int,
        header: str,
        spec: FieldSpec,
        rows: list[dict[str, Any]],
    ) -> FieldResolution:
        """Resolve a single field across rows using Case A / B / C logic."""
        raw_vals: list[str] = []
        for r in rows:
            v = r.get(header)
            if v is None:
                v = r.get(spec.canonical_name)
            if v is not None:
                s = str(v).strip()
                if s and s.lower() not in ("null", "none", "nan", "na"):
                    raw_vals.append(s)

        if not raw_vals:
            # All null or empty
            return FieldResolution(
                canonical_name=spec.canonical_name,
                source_position=position,
                raw_value=None,
                normalized_value=None,
                transformation_applied="NULL",
            )

        unique_vals = sorted(set(raw_vals))

        if len(unique_vals) == 1:
            # Case A or Case B (agreeing values)
            raw_str = unique_vals[0]
            norm_val, masked, trans = self._coerce_value(raw_str, spec)
            return FieldResolution(
                canonical_name=spec.canonical_name,
                source_position=position,
                raw_value=raw_str,
                normalized_value=norm_val,
                transformation_applied=trans,
                masked_sentinel=masked,
            )
        # Case C: Conflicting non-null values
        return FieldResolution(
            canonical_name=spec.canonical_name,
            source_position=position,
            raw_value=unique_vals[0],
            normalized_value=None,
            transformation_applied="CONFLICT_MASKED",
            has_conflict=True,
            conflict_values=tuple(unique_vals),
        )

    def _coerce_value(self, raw_str: str, spec: FieldSpec) -> tuple[Any, bool, str]:
        """Apply type coercion and check for domain sentinels."""
        dtype = spec.data_type.value
        cname = spec.canonical_name

        if dtype == "FLOAT":
            val = coerce_float(raw_str)
            if val is not None:
                # Check field-specific sentinels
                if cname in (
                    "gun_temp_dc_positive",
                    "gun_temp_dc_negative",
                ) and is_gun_temp_sentinel(val):
                    return None, True, "SENTINEL_GUN_TEMP_DISCONNECTED"
                if cname in (
                    "rectifier_internal_temp",
                    "rect_max_temperature",
                ) and is_rectifier_temp_sentinel(val):
                    return None, True, "SENTINEL_RECTIFIER_TEMP_UNINITIALIZED"
                if cname in (
                    "smr_dc_dc_temperature",
                    "smr_pfc_temperature",
                    "smr_rectifierinternal_temp",
                    "smrdcdc_temperature",
                    "smrpfc_temperature",
                ) and is_smr_temp_sentinel(val):
                    return None, True, "SENTINEL_SMR_TEMP_UNAVAILABLE"
            return val, False, "COERCE_FLOAT"

        if dtype == "INTEGER":
            return coerce_integer(raw_str), False, "COERCE_INT"

        if dtype == "BOOLEAN":
            return coerce_boolean(raw_str), False, "COERCE_BOOL"

        if dtype == "DATETIME":
            return coerce_datetime(raw_str), False, "COERCE_DATETIME"

        # ENUM, STRING, IDENTIFIER
        return coerce_string(raw_str), False, "COERCE_STRING"
