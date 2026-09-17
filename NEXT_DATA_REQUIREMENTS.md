# NEXT DATA REQUIREMENTS FOR PREDICTIVE INTELLIGENCE PLATFORM

## 1. Executive Summary

The Charger Predictive Intelligence Platform has established a verified, production-grade telemetry pipeline up through **Phase 7 (Historical Continuity & Time-Series Research Layer)**. The software pipeline is capable of ingesting untrusted CSVs, validating 456 production positions, reconstructing multi-entity canonical frames, normalizing typed component data into relational Silver tables with complete provenance, and streaming longitudinal timelines.

However, **Software Readiness $\ne$ Data Readiness**.

The currently available production asset (`16092026_170601_charger_status_latest.csv`) is a single point-in-time fleet snapshot where all 2,252 chargers have exactly **one observation timestamp**. To transition from descriptive historical playback to statistical pattern discovery, anomaly detection, and failure prediction, specific external datasets must be acquired.

---

## 2. Requirements Matrix by Development Stage

### 2.1 Needed Now (To Exercise Historical Continuity on Real Fleet)
To transition the 2,252 production chargers from `is_snapshot_only: true` to continuous time-series research in Phase 7:

| Specification | Requirement |
| :--- | :--- |
| **Data Type** | Daily or intra-day recurring RMS/CMS telemetry exports (same 456-position schema) |
| **Minimum Useful History** | 7 consecutive calendar days |
| **Preferred History** | 14 to 30 consecutive calendar days |
| **Sampling Cadence** | Intra-day snapshots (e.g., hourly) or continuous operational logs (10s–60s) |
| **Identifiers Needed** | Consistent `Charger Id`, `OCPP Id`, `Charging Station` across all files |
| **Linkage Requirements** | Unaltered column header positions (1–456) matching `data/dictionaries/` |
| **Unlocks** | Multi-day sampling regularity, empirical telemetry gap identification, component presence evolution (`first_seen`/`last_seen`), monotonic lifecycle counter drift |

---

### 2.2 Needed For Pattern Discovery (Phase 9)
To statistically analyze recurring operational behaviors, thermal cycles, and component interactions:

| Specification | Requirement |
| :--- | :--- |
| **Data Type** | High-frequency continuous session and idle telemetry streams |
| **Minimum Useful History** | 14 consecutive days of active charging sessions |
| **Preferred History** | 30 to 60 days across distinct operational seasons (summer peak vs winter) |
| **Sampling Cadence** | High-resolution periodic interval: 10 seconds to 60 seconds during charging |
| **Identifiers Needed** | `Charger Id`, `Connector No` (1–2), `Rectifier Number` (1–6), `Smr No.` (1–6), `Session Id` |
| **Linkage Requirements** | Synchronized timestamps between power module metrics (SMR DC-DC temp, PFC temp) and connector delivery (gun voltage, current) |
| **Unlocks** | SMR thermal divergence, rectifier load imbalance, gun thermocouple heating rates, contactor state transition timing |

---

### 2.3 Needed For Anomaly Detection (Phase 11)
To construct normative behavioral baselines and detect multi-sigma statistical outliers:

| Specification | Requirement |
| :--- | :--- |
| **Data Type** | Longitudinal baseline fleet telemetry covering healthy operational periods |
| **Minimum Useful History** | 30 to 60 days of uninterrupted operation per charger |
| **Preferred History** | 90 days across varied geographic clusters and ambient temperature ranges |
| **Sampling Cadence** | 1-minute to 5-minute periodic continuous cadence |
| **Identifiers Needed** | Hardware model, firmware version cohort (`silver_configuration_snapshot.config_hash`), rated kW capacity |
| **Linkage Requirements** | Metadata grouping by identical hardware models (e.g., Exicom 120kW vs 60kW, Delta, Tritium) |
| **Unlocks** | Mahalanobis/PCA multivariate anomaly scores, peer-group divergence flags, thermal runaway precursor detection |

---

### 2.4 Needed For Failure Prediction & Remaining Useful Life (Phases 12–13)
To train supervised machine learning models that link operational precursors to confirmed hardware breakdowns:

| Specification | Requirement |
| :--- | :--- |
| **Data Type** | **External Ground-Truth Failure & Maintenance Records** (CMMS / Ticketing / Field Service Logs) |
| **Minimum Useful History** | At least 50–100 confirmed hardware failure events with corresponding historical telemetry |
| **Preferred History** | 6 to 12 months of paired maintenance logs and continuous telemetry (300+ failure events) |
| **Sampling Cadence** | Continuous telemetry available for at least 72 hours preceding each failure event |
| **Identifiers Needed** | Exact `Charger Id`, exact failed subcomponent ID (e.g., `smr_3`, `connector_1`, `rectifier_2`), component serial number |
| **Linkage Requirements** | 1. Precise failure timestamp ($t_{failure}$) or ticket creation timestamp.<br>2. Exact failure mode code (e.g., SMR power stage short, contactor weld, gun temperature probe failure, isolation breakdown).<br>3. Work order resolution confirmation (e.g., "SMR module replaced", "thermocouple harness repaired"). |
| **Unlocks** | Supervised classification of failure precursors, survival analysis / RUL estimation, actionable predictive maintenance alerts |

---

### 2.5 Nice To Have (Enrichment Context)

| Data Source | Format | Utility |
| :--- | :--- | :--- |
| **Site Weather / Ambient Data** | Hourly external ambient temperature, humidity, solar irradiation by GPS/PIN | Normalizing cabinet and SMR temperature baselines against ambient heat waves |
| **Grid Power Quality Logs** | Distribution transformer voltage sags, surges, THD at charging station | Isolating external grid faults from internal charger rectifier failures |
| **Raw OCPP Message Logs** | JSON/WSS message archives (`StatusNotification`, `MeterValues`, `StopTransaction`) | Corroborating telemetry state transitions with protocol-level error codes |
| **Component Serial Numbers** | Inventory ledger linking charger IDs to physical module serials | Tracking recurring batch defects across hardware supplier manufacturing runs |

---

## 3. Summary of Current Platform Boundary

```
[CURRENT ASSET: 1 Snapshot File, 2,252 Chargers, 1 Timestamp Each]
                             │
                             ▼
  [SOFTWARE CAPABILITY: Complete through Phase 7 Continuity Engine]
                             │
                             ▼
   ❌ BLOCKED ON DATA: Cannot compute rolling features or trends
                       for chargers with only 1 observation.
                             │
                             ▼
  [NEXT IMMEDIATE ACTION: Ingest consecutive daily fleet CSV exports]
```
