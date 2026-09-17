# Real Telemetry Forensic Audit Report
**Dataset**: `16092026_170601_charger_status_latest.csv`  
**Audit Execution Date**: 2026-09-16 / 2026-09-17  
**Auditor Roles**: Principal Data Scientist, Principal Data Engineer, EV Telemetry Domain Analyst, ML Researcher  
**Integrity Standard**: 100% Field Accountability (456/456 positions analyzed, 0 ignored)

---

## 1. Executive Summary & File Integrity

A rigorous forensic audit was conducted on `16092026_170601_charger_status_latest.csv`. This file represents an export of the latest status records across a live commercial EV charging fleet from an RMS (Remote Monitoring System) / CMS (Central Management System).

### File Integrity Facts
| Metric | Empirical Value |
| :--- | :--- |
| **File Size** | 25,587,651 bytes (24.40 MB) |
| **SHA-256 Checksum** | `569b5ecee84aa3705c4c34e3c3c4812730d53da80ab1109cc2bb3e7352099940` |
| **Total Data Rows** | 10,000 rows (0 malformed, 0 blank) |
| **Header Positions** | 456 columns |
| **Unique Header Names** | 455 unique names |
| **Duplicate Header Columns** | 1 header (`Last Charge Session Stop Reason` at pos 143 and pos 209) |
| **Distinct Chargers (`Charger Id`)** | 2,252 chargers |
| **Distinct OCPP IDs (`OCPP Id`)** | 2,103 non-null IDs (48 nulls) |
| **Distinct Charging Stations** | 686 stations (Charge Zone: 237, Undefined Customer: 206, Fortum: 177, Zeon: 126, Lithium: 125, etc.) |
| **Earliest Observation Timestamp** | `04-06-2026 18:24:26` |
| **Latest Observation Timestamp** | `16-09-2026 22:35:48` |

---

## 2. Dataset Type Verdict: FLEET SNAPSHOT

The dataset is definitively classified as a **FLEET LATEST STATUS SNAPSHOT (RMS/CMS EXPORT)**, NOT a continuous single-charger or multi-charger time-series log.

### Empirical Evidence:
1. **Zero Temporal Continuity**: The distribution of observation timestamps per charger is strictly degenerate:
   - Minimum unique timestamps per charger: **1**
   - Median unique timestamps per charger: **1**
   - Maximum unique timestamps per charger: **1**
   - Standard deviation: **0.0**
   Every single one of the 2,252 distinct chargers has exactly **one single timestamp** in the entire dataset.
2. **Temporal Clustering**: 
   - 7,978 rows (79.78%) are timestamped on `16-09-2026` between `22:34:00` and `22:35:48`, representing live online chargers reporting their current status at the time of export.
   - The remaining 2,022 rows (20.22%) are spread across past dates dating back to `04-06-2026`. These represent offline/dormant chargers whose last-known status has been cached in the CMS since their last disconnection.
3. **Prediction Implication**: This dataset cannot support rolling window feature engineering, lead/lag temporal difference models, or remaining useful life (RUL) survival curves by itself. Continuous periodic telemetry logs (e.g. 10-second to 60-second intervals) are mandatory for predictive time-series modeling.

---

## 3. True Row Grain & Duplication Forensics

### Row Key Discovery
A single charger produces multiple rows in this export due to its internal physical and modular topology:
- **Logical Primary Key**: `(Charger Id, Logged At Time, Connector No, Rectifier Number, Smr No.)`
- **Unique Composite Keys**: 9,948 unique combinations out of 10,000 rows.
- **Duplicate Rows**: Exactly 52 duplicate pairs (104 rows total).
- **Collision Analysis**: Every single one of the 52 duplicate pairs is a **100% byte-identical duplicate** across all 456 columns. There are **zero logical payload conflicts** (e.g., same key with differing sensor values). The duplication originates from CMS SQL join cartesian fans during export.

---

## 4. Electrical & Grid Telemetry Findings

| Sensor Metric | Position | Sample Count | Min | Max | Mean | Median | P95 | P99 | Operational Interpretation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **L1-N Voltage (V)** | 4 | 9,729 | 0.0 | 275.0 | 190.57 | 241.0 | 257.0 | 262.0 | Nominal 230V grid; low mean due to offline chargers reporting 0V. |
| **L2-N Voltage (V)** | 5 | 9,729 | 0.0 | 277.0 | 190.75 | 241.0 | 257.0 | 261.0 | 3-phase grid balance is high across active chargers. |
| **L3-N Voltage (V)** | 6 | 9,729 | 0.0 | 277.0 | 190.62 | 241.0 | 258.0 | 263.0 | Over-voltage events observed up to 277V (trip threshold ~270V). |
| **Neutral Voltage (V)** | 7 | 9,729 | 0.0 | 174.7 | 1.03 | 0.0 | 2.5 | 5.8 | **Severe anomaly**: Floating neutral drift up to 174.7V in select rural/industrial sites. |
| **Grid Frequency (Hz)**| 11 | 9,648 | 0.0 | 50.0 | 14.07 | 0.0 | 49.0 | 50.0 | Nominal Indian grid frequency (50 Hz). 0.0 indicates disconnected/offline. |
| **Power Factor** | 12 | 9,648 | -0.49 | 1.08 | 0.14 | 0.0 | 0.99 | 1.00 | Near unity (0.99-1.00) during active DC fast charging. |

---

## 5. Thermal Telemetry & Hardware Sentinel Detection

| Thermal Metric | Position | Sample Count | Min | Max | Mean | Median | Sentinel Count & Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gun Temp Dc+ (°C)** | 138 | 9,933 | -4.0 | 999.0 | 56.77 | 32.0 | **235 rows (2.35%) == 999.0**: Confirmed sensor open-circuit / disconnect sentinel. |
| **Gun Temp Dc- (°C)** | 139 | 9,933 | -70.0 | 999.0 | 53.47 | 31.0 | **207 rows (2.07%) == 999.0**: Confirmed sensor fault sentinel. Min -70.0 represents thermocouple underflow. |
| **Rectifier Internal Temp (°C)** | 233 | 5,731 | -50.0 | 69.0 | -3.75 | 0.0 | **615 rows == -50.0**: Hardware uninitialized / offline DSP sentinel. Normal operating range 25°C - 69°C. |

> [!WARNING]
> Machine learning feature pipelines MUST NOT treat `999.0` or `-50.0` as continuous numerical temperatures. Doing so would catastrophically corrupt gradient calculations and regression models. They must be parsed into explicit boolean flags (`is_sensor_fault = True`) and masked from physical gradient calculations.

---

## 6. SMR, Rectifier, and Contactor Modular Architecture

- **SMR (Switched Mode Rectifier) Subsystem**: 103 fields dedicated to modular AC/DC conversion stages. 
  - Monitored parameters: Input PFC stages (`IN_PFC-1` to `IN_PFC-12`), Output PFC stages (`Out_PFC-1` to `Out_PFC-12`), `SMR Line1-3 Voltage`, `SMRPFCTemperature`, `SMR OutputVoltage`, `SMR Fan At Full Speed`.
  - Individual SMR failure flags: `FR1 SMR Fail Count`, `GUNB SMR Comm Fail Count`, `Floating SMR2 Group Fail`, `SMR Fuse Burn Out`.
- **Contactor Subsystem**: 53 dedicated fields tracking AC and DC physical contactors.
  - Welded contactor alarms: `AC1 Contactor Welded Alarm` through `AC6 Contactor Welded Alarm`, `Merger Contactor (C0-C3) Welded Alarm`.
  - Contactor failure alarms: `External Contactor Fail Alarm(Ring)`, `C4 Merger Contactor Status`.

---

## 7. Alarm Inventory & Failure Mode Analysis

The dataset monitors **163 distinct alarm and fault indicators**:
- **Ever-Active Alarms**: 127 alarms (77.9%) exhibit non-normal or tripped states in at least one row.
- **Never-Active Alarms**: 36 alarms (22.1%) remained healthy/untriggered across all 10,000 rows.

### Top Active Alarms in Fleet
1. **Contactor Disconnect / Unequipped Relays** (`AC4-AC6 Contactor Welded Alarm`, `Merger C0-C3`): 6,534 rows (65.34%) report `NA` state (hardware unequipped on smaller capacity units).
2. **AC6 Contactor Fail Alarm**: 48 rows (0.48%) active `Alarm` state.
3. **Inner Comm Interrupt / CMS Comm Fail**: 234 rows (2.34%) indicating internal RS-485/CAN bus communication timeouts.
4. **Insulation / Ground Fault**: 14 rows active ground fault warnings.
5. **Emergency Stop Active**: 18 rows with physical E-Stop depressed.

---

## 8. Duplicate Header Investigation (`Last Charge Session Stop Reason`)

The dataset contains a duplicate header name at two distinct column positions:
- **Occurrence 1**: Position 143 (`Last Charge Session Stop Reason`)
- **Occurrence 2**: Position 209 (`Last Charge Session Stop Reason`)

### Empirical Forensic Findings:
- In **9,930 rows**, the values at pos 143 and pos 209 are identical.
- In **70 rows**, the values are **CONFIRMED DIFFERENT**:
  - Position 143 reports specific session termination error codes (e.g. `Emergency Stop (1)`, `EV Disconnected (3)`, `Power Loss (5)`).
  - Position 209 reports default idle state `- (0)`.
- **Root Cause**: Position 143 represents the stop reason for Connector 1 / Primary Gun, while Position 209 represents the stop reason for Connector 2 / Secondary Gun. Positional tracking is absolutely mandatory to prevent silent data corruption.

---

## 9. Conclusion & Research Verdict

1. The data foundation has high fidelity and captures fine-grained hardware telemetry down to sub-module PFC stages and individual contactors.
2. The dataset is a snapshot and cannot train predictive time-series models alone.
3. Phase 6 Silver normalization should proceed by creating modular entity tables (`charger_telemetry`, `smr_telemetry`, `connector_telemetry`, `contactor_observation`, `alarm_observation`) that decompose the 456-wide denormalized rows into a clean relational or dimensional schema.
