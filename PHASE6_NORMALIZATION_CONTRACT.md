# Phase 6 Silver Normalization Input Contract

**Document Version**: 1.0.0  
**Status**: APPROVED & AUTHORITATIVE  
**Governing Production Schema Revision**: `charger_status_v2.0.0` (`charger_status_v2`)  
**Target Ingestion Source**: Production Commercial DC Fast-Charger Telemetry (456 Positions)  
**Verification Baseline**: `16092026_170601_charger_status_latest.csv` (10,000 rows, 456 columns, 2,252 chargers)

> [!IMPORTANT]
> **Boundary Rule for Phase 6**:
> This document specifies the immutable inputs that Phase 6 (Canonical Silver Telemetry Normalization) may trust. Phase 6 must **NOT** guess field types, parse field names, or use substring heuristics. It must consume the authoritative definitions specified herein.

---

## 1. Schema Authority & Identity Model

### Production Schema Identification
- **Schema Name**: `charger_status_v2`
- **Revision**: `charger_status_v2.0.0`
- **Total Source Positions**: 456
- **Total Registered Fields**: 456 (100.0% coverage, 0 unmapped)
- **Header Fingerprint**: `d8b6710c57c1509fb64071075037285d1efbe9f0a135249f9496facd068b92b2`

### Field Identity Rule
Phase 6 must identify columns using the composite tuple:
$$\text{Field Identity} = (\text{source\_name}, \text{source\_occurrence}, \text{source\_position})$$

Under no circumstances may Phase 6 assume header names are unique across the 456 columns.

### Duplicate Header Binding
- **Literal Header**: `Last Charge Session Stop Reason`
- **Occurrence 1** (Pos 143):
  - Canonical Name: `last_charge_session_stop_reason`
  - Entity: `SESSION`
  - Silver Destination: `session_observation.stop_reason` (bound to Connector 1 / Gun A)
- **Occurrence 2** (Pos 209):
  - Canonical Name: `last_charge_session_stop_reason_secondary`
  - Entity: `SESSION`
  - Silver Destination: `session_observation.stop_reason` (bound to Connector 2 / Gun B)

---

## 2. Entity Ownership & Relational Topology

Phase 6 decomposes the flat 456-position Bronze row into a normalized relational model linked by explicit foreign keys:

```
[site_metadata]
       │ (station_name)
       ▼
[charger_telemetry] ────────┬───────────────┬───────────────┬──────────────────────┬────────────────────┐
       │                    │               │               │                      │                    │
       ▼                    ▼               ▼               ▼                      ▼                    ▼
[connector_telemetry] [rectifier_telem] [smr_telem] [contactor_obs]        [alarm_obs]         [comm_obs]
       │
       ▼
[session_observation]
```

### Component Breakdown
1. **`site_metadata`** (1 field): Site name / operational location (`Charging Station`).
2. **`charger_telemetry`** (74 fields): Cabinet-level telemetry, 3-phase grid voltages/currents (`L1-N Voltage`, `L2-N Voltage`, `L3-N Voltage`, `Line 1 Input Current`, etc.), grid frequency, cabinet temperature, power factor.
3. **`connector_telemetry`** (24 fields): Connector-level telemetry, gun temperatures (`Gun Temp Dc+`, `Gun Temp Dc-`), gun lock, plug state, DC output voltages/currents.
4. **`rectifier_telemetry`** (15 fields): Rectifier internal temperature, rectifier DC output voltages/currents, group rectifier fault status.
5. **`smr_telemetry`** (51 fields): Switched-mode rectifier modular telemetry, DC/DC voltages, PFC input/output stages 1–12, module PFC temperatures.
6. **`contactor_observation`** (28 fields): Auxiliary feedback switch states for `AC1` through `AC6` line contactors, `Merger Contactor C0` through `C3`, and ring contactors.
7. **`alarm_observation`** (204 fields): Active alarm edge signals, emergency stop buttons, insulation resistance faults, door open trips, grid voltage/frequency protection trips.
8. **`session_observation`** (16 fields): Active/historical charging transaction metrics: session energy delivered, meter values, `Charging Time` duration, start timestamp (`Begin Time`), and connector-specific stop reasons.
9. **`lifecycle_counters`** (14 fields): Monotonically increasing operational counters: AC cumulative kWh, DC cumulative kWh, cycle count, SMR failure counters.
10. **`communication_observation`** (9 fields): Cellular RF quality (`RSRP`, `RSRQ`), OCPP central station link status, SIM card status.
11. **`configuration`** (10 fields): Static charger settings: firmware versions, charging start method, EV voltage and current limits.

---

## 3. Data Types & Physical Unit Semantics

Phase 6 must coerce string Bronze values to canonical typed columns according to the following validated semantics:

### Canonical Data Types
- **`FLOAT`** (127 fields): Continuous physical telemetry, electrical measurements, temperatures, and counters.
- **`ENUM`** (306 fields): Discrete state machines, contactor auxiliary switches, and alarm flags (`Alarm`, `Not alarm`, `Normal`, `Trip`, `0`, `1`).
- **`IDENTIFIER`** (13 fields): Alphanumeric identifiers (`Charger Id`, `OCPP Id`, `Station`, `Connector No`, `Rectifier Number`, `Smr No.`).
- **`STRING`** (8 fields): Descriptive strings and firmware version codes.
- **`DATETIME`** (2 fields): ISO-8601 timestamps:
  - `Logged At Time` (Pos 3): Format `%d-%m-%Y %H:%M:%S` (source timezone: `Asia/Kolkata`).
  - `Begin Time` (Pos 205): Session start timestamp.

### Authoritative Physical Units
Only the closed set in `data/contracts/units.yaml` is permissible:
- **Voltage**: `V` (Volts AC and DC)
- **Current**: `A` (Amperes AC and DC)
- **Active Power**: `kW` (Kilowatts)
- **Reactive Power**: `kVAr` (Kilovar)
- **Apparent Power**: `kVA` (Kilovolt-Amperes)
- **Energy**: `kWh` (Kilowatt-hours)
- **Frequency**: `Hz` (Hertz)
- **Temperature**: `°C` (Degrees Celsius)
- **Resistance**: `kOhm` (Kilohms, insulation resistance)
- **Rotational Speed**: `rpm` (Revolutions per minute, cooling fans)
- **Duration**: `seconds` (`Charging Time`)
- **RF Signal Power**: `dBm` (`RSRP`)
- **RF Signal Quality**: `dB` (`RSRQ`)

All discrete alarm flags, switch states, and text identifiers have `unit: null`.

---

## 4. Sentinel Semantics & Cleansing Transformations

Bronze stores raw unedited strings. Phase 6 Silver transformations must apply the following sentinel rules:

### Authoritative Sensor Disconnect Sentinels
1. **Gun Thermocouples (`Gun Temp Dc+`, `Gun Temp Dc-`)**:
   - If raw value $\in \{999.0, 999\}$:
     - Set normalized column `temp_c = NULL`.
     - Set quality flag `is_sensor_fault = TRUE`.
     - Set fault code `gun_temp_sensor_disconnected`.
2. **Rectifier Internal Temperature (`Rectifier Internal Temp`)**:
   - If raw value $\in \{-50.0, -50\}$:
     - Set normalized column `temp_c = NULL`.
     - Set quality flag `is_uninitialized = TRUE`.
3. **SMR Modular Temperatures (`SMR DcDc Temp`, `SMR Pfc Temp`, `SMR RectifierinternalTemp`, etc.)**:
   - If raw value $\in \{-150.0, -150\}$:
     - Set normalized column `temp_c = NULL`.
     - Set quality flag `is_probe_unavailable = TRUE`.

### Physical Anomaly Flags (Value Retained)
- **Neutral Voltage Displacements**: When `Neutral Voltage` $> 20.0\,\text{V}$ (observed up to $174.7\,\text{V}$):
  - Retain the measured numerical value.
  - Set quality flag `neutral_voltage_displacement = TRUE`.

---

## 5. Frame & Temporal Semantics

### Grain of the Real Dataset
- The dataset `16092026_170601_charger_status_latest.csv` is a **cross-sectional fleet snapshot of latest status**.
- Exactly 2,252 chargers are observed, each with strictly 1 observation timestamp ($\sigma = 0.0$).
- Phase 6 must **NOT** attempt to compute rolling time-series degradation or temporal moving averages across this file.
- Individual chargers have between 1 and 64 rows per timestamp reflecting multi-connector and multi-SMR combinations:
  - 1 connector $\times$ 1 SMR = 1 row/timestamp
  - 2 connectors $\times$ 1 SMR = 2 rows/timestamp
  - 2 connectors $\times$ 2 SMRs = 4 rows/timestamp
  - 2 connectors $\times$ 3 SMRs = 6 rows/timestamp
  - 2 connectors $\times$ 4 SMRs = 8 rows/timestamp
  - 2 connectors $\times$ 6 SMRs = 12 rows/timestamp
  - 2 connectors $\times$ 10 SMRs = 20 rows/timestamp

### Logical Frame Key
Frames must be grouped and reconstructed using the composite key:
$$\text{Frame Key} = (\text{charger\_id}, \text{logged\_at\_time}, \text{connector\_no}, \text{rectifier\_number}, \text{smr\_no})$$

Omission of `charger_id` from the key is prohibited, as multiple chargers legitimately report the same second.

---

## 6. Provenance & Quality Flags

Every Silver row generated by Phase 6 must preserve end-to-end lineage:
- `source_file_id`: UUID of the ingested `telemetry_files` record.
- `source_file_path`: Relative or inbox file path.
- `source_row_number`: 1-indexed row number from the source CSV.
- `ingestion_batch_id`: UUID of manual upload batch or automated filesystem run.
- `schema_fingerprint`: SHA-256 fingerprint (`d8b6710c...`).
- `quality_scores`:
  - `schema_quality`: 100% (all 456 positions mapped).
  - `completeness_quality`: Proportion of non-null values for mandatory operating fields.
  - `validity_quality`: Compliance with range and closed enum checks.
  - `duplicate_quality`: 100% for non-duplicate rows; flagged for the 52 CMS SQL duplicate join pairs.
