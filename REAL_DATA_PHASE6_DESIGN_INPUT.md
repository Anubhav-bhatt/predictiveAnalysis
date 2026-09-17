# Phase 6 Silver Normalization Design Input Specification
**Document Purpose**: Architectural inputs, entity modeling, and routing specifications for Phase 6 implementation based on empirical findings of `16092026_170601_charger_status_latest.csv`.

---

## 1. Entity Normalization Architecture

The 456 source positions must be routed into 7 normalized canonical Silver tables linked by clean foreign keys:

```
[site_metadata]
       │
       ▼
[charger_telemetry] ────────┬───────────────┬───────────────┬──────────────────────┬────────────────────┐
       │                    │               │               │                      │                    │
       ▼                    ▼               ▼               ▼                      ▼                    ▼
[connector_telemetry] [rectifier_telem] [smr_telem] [contactor_obs]        [alarm_obs]         [comm_obs]
       │
       ▼
[session_observation]
```

---

## 2. 456-Field Routing Summary

| Target Silver Entity / Table | Source Fields Routed | Primary Key / Grain | Key Content Description |
| :--- | :---: | :--- | :--- |
| **`site_metadata`** | 1 | `(station_name)` | `Charging Station` name, site operational grouping |
| **`charger_telemetry`** | 116 | `(charger_id, observation_timestamp)` | Cabinet telemetry, 3-phase grid voltages/currents, frequency, power factor, auxiliary fans, cabinet temp |
| **`connector_telemetry`** | 28 | `(charger_id, observation_timestamp, connector_no)` | Gun temps (DC+, DC-), gun lock/plug status, connector type, output DC voltage/current |
| **`rectifier_telemetry`** | 15 | `(charger_id, observation_timestamp, rectifier_number)` | Rectifier internal temperature, rectifier output current/voltage, group rectifier fault flags |
| **`smr_telemetry`** | 103 | `(charger_id, observation_timestamp, smr_no)` | SMR voltages, PFC input/output stages 1-12, SMR PFC temp, derating flags, SMR comm fail |
| **`contactor_observation`** | 28 | `(charger_id, observation_timestamp)` | AC1-AC6 contactor status/welded alarms, Merger C0-C4 contactors, ring contactor status |
| **`alarm_observation`** | 127 | `(charger_id, observation_timestamp, alarm_code)` | System-level alarm flags, emergency stop, insulation faults, ground faults, temperature alarms |
| **`session_observation`** | 15 | `(charger_id, connector_no, session_id)` | Active/last session energy delivered, meter values, duration, SoC, stop reasons (pos 143/209) |
| **`communication_observation`** | 9 | `(charger_id, observation_timestamp)` | `OCPP Id`, `RSRP`, `RSRQ`, CMS comm fail, SIM status, ring communication break |
| **`configuration`** | 10 | `(charger_id)` | Firmware version, charging start method, charge selected mode, hardware ratings |
| **`lifecycle_counters`** | 3 | `(charger_id, observation_timestamp)` | AC cumulative energy, DC cumulative energy, charging cycle count |
| **`auxiliary_power`** | 1 | `(charger_id, observation_timestamp)` | `BackupBatteryLow` status |
| **TOTAL ROUTED** | **456** | — | **100% Field Accountability (0 fields dropped)** |

---

## 3. Data Cleansing & Sentinel Masking Rules

1. **Non-Destructive Bronze Layer**: All 456 columns are ingested raw into Bronze with raw string values, exact header names, and row sequence numbers preserved.
2. **Silver Sentinel Transformation**:
   - `Gun Temp Dc+` / `Gun Temp Dc-` == `999.0` -> Transform to `NULL` (or mask) and set `is_sensor_fault = TRUE`.
   - `Rectifier Internal Temp` == `-50.0` -> Transform to `NULL` (or mask) and set `is_temp_uninitialized = TRUE`.
   - Neutral Voltage > 50V -> Retain physical voltage value, flag `is_neutral_imbalanced = TRUE`.
3. **Positional Stop Reason Resolution**:
   - Pos 143 mapped to `connector_1_last_stop_reason`.
   - Pos 209 mapped to `connector_2_last_stop_reason`.

---

## 4. Phase 6 Development Prerequisites

1. **Update Dictionary Registry**: Add all 456 real production columns with their positional occurrences to the contract system.
2. **Implement Multi-Table Silver Ingestion**: Build the Bronze-to-Silver normalizer pipeline to populate the decomposed tables.
3. **Await Time-Series Telemetry**: Before building predictive ML models, ingest continuous periodic telemetry to establish historical temporal depth.
