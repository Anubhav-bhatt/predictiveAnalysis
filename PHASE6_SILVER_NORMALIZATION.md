# PHASE 6 — CANONICAL SILVER TELEMETRY NORMALIZATION SPECIFICATION

## 1. Executive Summary

Phase 6 established the canonical typed Silver telemetry layer for the Charger Predictive Intelligence Platform. It converts trusted reconstructed telemetry source frames into typed, normalized, queryable, provenance-preserving Silver records without losing, guessing, averaging, fabricating, or silently modifying telemetry.

Every single field across all 456 production positions from the real-world RMS dataset (`16092026_170601_charger_status_latest.csv`) has been mapped and normalized into typed relational tables with complete provenance.

---

## 2. Silver Domain Tables

The Silver layer decomposes multi-entity frames into 11 specialized physical relational tables:

1. **`silver_site_metadata`**: Geographical and operational metadata (`charging_station`, etc.).
2. **`silver_charger_telemetry`**: Cabinet and grid-level continuous electrical and environmental telemetry (120 fields, including 3-phase voltages, currents, power, frequency, power factor, cabinet temperature, neutral voltage).
3. **`silver_connector_telemetry`**: Physical connector gun telemetry scoped by `(charger_id, event_time, frame_sequence, connector_id)` (88 fields, including gun thermocouple temperatures, output voltage/current, meter energy, charging states).
4. **`silver_rectifier_telemetry`**: Modular rectifier telemetry scoped by `(charger_id, event_time, frame_sequence, rectifier_id)` (84 fields, including rectifier AC/DC voltages, currents, temperatures, communication status).
5. **`silver_smr_telemetry`**: Switch Mode Rectifier (SMR) power module telemetry scoped by `(charger_id, event_time, frame_sequence, smr_id)` (80 fields, including SMR DC-DC temperature, PFC temperature, input/output metrics, operational states).
6. **`silver_contactor_observation`**: Electromechanical contactor feedback states (Positive/Negative contactors, emergency stop switches).
7. **`silver_alarm_observation`**: Active fault and protection flag bitfields and strings (Smoke, Surge, Door, Insulation, E-Stop, Overvoltage, Undervoltage).
8. **`silver_session_observation`**: Transactional EV charging session lifecycle states, energy consumed, duration, user token, and stop reasons disambiguated per connector.
9. **`silver_lifecycle_counter_observation`**: Cumulative monotonic hardware lifecycle metrics (charge cycle counters, total kWh energy delivered, operational runtimes).
10. **`silver_communication_observation`**: Cellular modem and networking signal parameters (`rsrp`, `rsrq`, `rssi`, `snr`).
11. **`silver_configuration_snapshot`**: Static hardware, firmware, and site parameters (`charger_type`, `model`, `oem`, `protocol_version`, `rated_capacity_kw`) with computed SHA-256 `config_hash`.

Supporting infrastructure tables:
- **`silver_observation_provenance`**: Atomic per-field lineage linking every normalized Silver cell back to its source file ID, source CSV position (1-456), raw text value, normalized value representation, transformation applied, sentinel masking flag, and bronze row ID.
- **`silver_normalization_run`**: Audit log of normalization executions, durations, counts, and error/warning summaries.

---

## 3. Production Contract & Mapping Alignment

All 456 columns of the production dataset are authoritatively cataloged in `data/dictionaries/` across domain YAMLs:
- `identity.yaml`: 4 fields (Positions 1-4)
- `charger.yaml`: 120 fields (Positions 5-26, 126-146, 218-299)
- `connector.yaml`: 88 fields (Positions 27-50, 60-70, 147-158, 172-181, 300-327)
- `session.yaml`: 24 fields (Positions 51-59, 159-171; duplicate *Last Charge Session Stop Reason* at pos 59 and pos 170 disambiguated to Connector 1 and Connector 2)
- `smr.yaml`: 80 fields (Positions 71-88, 182-199, 328-371)
- `rectifier.yaml`: 84 fields (Positions 89-105, 200-216, 372-421)
- `contactor.yaml`: 8 fields (Positions 106-113)
- `counters.yaml`: 7 fields (Positions 114-120)
- `communication.yaml`: 5 fields (Positions 121-125)
- `alarm.yaml`: 22 fields (Positions 422-443)
- `configuration.yaml`: 13 fields (Positions 444-456)

Total unmapped fields: **0**.

---

## 4. Normalization Rules & Invariants

### 4.1 Strict Coercion Without Fabrication
- **Numeric values**: Floats and integers parsed strictly. Empty strings, whitespace, and case-insensitive sentinel strings (`NULL`, `None`, `NaN`, `NA`) coerced to `None` (SQL NULL).
- **Enums & Strings**: Case-preserved or stripped cleanly; unmapped enums stored as literal strings without truncation.
- **Booleans**: Truthy values (`true`, `1`, `yes`, `closed`) and falsy values (`false`, `0`, `no`, `open`) mapped strictly; unknown strings yield NULL with a validation warning.

### 4.2 Field-Specific Hardware Sentinel Masking
Hardware probe disconnects produce known sentinel values in telemetry:
- **Gun Thermocouple Temperatures**: Value `999.0` (or `999`) indicates open-circuit probe. Masked to `None` in `SilverConnectorTelemetry`; raw value `999.0` preserved in `SilverObservationProvenance` with `masked_sentinel = True`.
- **Rectifier Temperature**: Value `-50.0` (or `-50`) indicates unpopulated sensor / disconnected probe. Masked to `None` in `SilverRectifierTelemetry`; raw value preserved in provenance with `masked_sentinel = True`.
- **SMR Internal Temperature**: Value `-150.0` (or `-150`) indicates uncalibrated / unseated power module sensor. Masked to `None` in `SilverSmrTelemetry`; raw value preserved in provenance with `masked_sentinel = True`.

### 4.3 Deterministic Frame Reconstruction Resolution
When multiple Bronze rows contribute to a single physical source frame:
- **Case A (Identical Values)**: All contributing rows match; field resolves to the single value with `transformation = EXACT`.
- **Case B (Agreeing Values with Sparsity)**: Exactly one unique non-empty value exists among contributing rows; field resolves to the non-empty value with `transformation = COMPONENT_AGGREGATE`.
- **Case C (Conflicting Values)**: Two or more distinct non-empty values exist for a scalar frame attribute across contributing rows. Field normalized to `None` (SQL NULL) to prevent corrupt averages. Warning logged as `REPEATED_FIELD_CONFLICT` or `CONNECTOR_FIELD_CONFLICT` with all conflicting values preserved in the run audit and provenance.

### 4.4 Temporal & Timezone Semantics
All timestamps are parsed with strict Indian Standard Time (`Asia/Kolkata`, UTC+05:30) source semantics when parsed from naive string formats (e.g. `16-09-2026 17:06:01`), and normalized to UTC `timestamptz`. Temporal ordering is strictly preserved by `(event_time ASC, frame_sequence ASC)`.

---

## 5. Verification
- **Unit Tests**:
  - `tests/unit/test_silver_coercion.py`: Validates all coercion primitives, sentinels, and boundary cases.
  - `tests/unit/test_silver_payload_resolver.py`: Validates Case A/B/C conflict resolution and duplicate position handling.
- **Integration Tests**:
  - `tests/integration/test_silver_normalization.py`: Validates complete end-to-end normalization from raw CSV -> Bronze rows -> Canonical Frames -> Typed Silver tables with provenance audit.
- **Full Suite**: 216 tests passing, 0 lints, clean mypy type checks.
