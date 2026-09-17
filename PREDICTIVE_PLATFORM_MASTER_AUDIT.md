# CHARGER PREDICTIVE INTELLIGENCE PLATFORM
## MASTER PRODUCT FORENSIC AUDIT & END-TO-END PRODUCT ROADMAP

**Document Type**: Authoritative Repository Forensic Audit, Technical Capability Baseline & Product Roadmap  
**Audit Execution Date**: 2026-09-17  
**Repository State**: Commit HEAD (Branch: `main`)  
**Overall Verdict**: **WORKING THROUGH PHASE 7** (Historical Continuity & Time-Series Research Layer Operational)  
**Current Production Bottleneck**: **Data Depth** (1 Fleet Snapshot Available vs Software Ready for Continuous Time-Series)

---

## 1. Executive Summary

This master forensic audit establishes the empirical, verified ground truth of the Charger Predictive Intelligence Platform as of September 17, 2026. Every statement in this document has been independently confirmed against active source code, SQLAlchemy models, database migrations, REST endpoints, UI components, automated tests, and runtime behavior.

### Key Audit Findings:
1. **Software Readiness (Phases 1A through 7: BUILT & VERIFIED)**:
   - The platform has successfully implemented and verified every layer from raw CSV intake up through longitudinal historical time-series streaming.
   - 241 backend tests pass in 54 seconds (100% pass rate, 0 failures, 0 skips when real sample path is set).
   - 56 frontend tests pass in Vitest with 0 lint warnings and clean TypeScript compilation.
   - Database schema is fully synced with Alembic (`alembic check` reports 0 schema drifts).
2. **Production Contract Verified (Phase 5.5)**:
   - 456 of 456 positions from real commercial fast charger telemetry (`16092026_170601_charger_status_latest.csv`) are authoritatively mapped in `data/dictionaries/` with 0 unmapped columns.
   - Repeated headers (e.g. `Last Charge Session Stop Reason` at pos 143 and 209) are disambiguated to Connector 1 and Connector 2 without data collision.
   - Field-specific hardware thermocouple sentinels (`999.0` gun temp, `-50.0` rectifier temp, `-150.0` SMR temp) are bound and masked to `NULL` while preserving raw values in provenance.
3. **Canonical Silver Telemetry (Phase 6)**:
   - Decomposes multi-entity frames into 11 typed relational domain tables covering grid electricals, connectors, rectifiers, SMR power modules, contactors, alarms, sessions, and configuration.
   - Preserves atomic per-field lineage in `silver_observation_provenance`.
4. **Historical Continuity Research Layer (Phase 7)**:
   - Enforces strict temporal ordering: `(event_time ASC, frame_sequence ASC)` globally.
   - Guarantees **Zero Data Imputation**: missing intervals are surfaced as empirical absences rather than manufactured data.
   - Features sub-5ms query performance (0.88 ms – 4.80 ms) and provides `ResearchDataAccessLayer` for downstream ML research.
5. **Data Depth Reality**:
   - The single available production asset (`16092026_170601_charger_status_latest.csv`, 24.4 MB, 10,000 rows, 2,252 chargers) is an instantaneous **fleet latest-status snapshot**, where each charger has exactly **1 observation timestamp**.
   - The platform honestly flags these chargers as `is_snapshot_only = true` and refuses premature pattern research until continuous daily files are ingested.

---

## 2. Current Product Capability

Today, an operator or data engineer can:
1. **Upload & Ingest**: Upload untrusted multi-megabyte CSV files via the Web UI or drop them into `data/inbox/`. Files are validated, hashed (SHA-256), deduplicated idempotently, and stored in immutable Bronze storage.
2. **Profile & Validate**: Ingest files through a pure-Polars profiling engine that extracts sampling cadence, detects multi-day spans, identifies duplicate rows, and evaluates a 5-pillar data quality score.
3. **Reconcile Fleet Delivery**: Track expected vs received charger telemetry per business date, identify missing chargers, and highlight late arrivals past cutoffs.
4. **Reconstruct Physical Frames**: De-multiplex multi-row cartesian CSV rows into canonical telemetry frames, resolving dynamic hardware topologies (e.g., 2 connectors x 4 SMRs = 8 rows/frame) while preserving same-second distinct captures.
5. **Query Typed Silver Telemetry**: Retrieve typed, normalized electrical, thermal, and alarm telemetry across 11 physical domain tables with hardware sentinels cleanly masked.
6. **Stream Longitudinal History**: Query continuous multi-day telemetry timelines ordered strictly by event time, inspect empirical data gaps, track monotonic counter drift/resets, and view physical component lifecycles.
7. **Interactive Web Dashboard**: Navigate from fleet delivery summaries down to individual charger frames, component telemetry charts, and gap timelines in a React/TypeScript interface.

---

## 3. Repository Architecture

```
predictiveAnalysis/
├── backend/                         # FastAPI Backend Application
│   ├── alembic/                     # Database Migrations (5 versions, up to Silver tables)
│   └── app/
│       ├── api/v1/                  # REST Routers (chargers, data_ops, frames, silver, history, uploads)
│       ├── core/                    # App configuration, structured logging
│       ├── db/                      # SQLAlchemy async engine and session factory
│       ├── models/                  # 32 registered SQLAlchemy database models
│       ├── repositories/            # Data access layer (fleet, frames, ingestion, quality, schema, silver)
│       ├── schemas/                 # Pydantic v2 validation DTOs (common, fleet, frames, history, silver, uploads)
│       └── services/                # Business logic (coverage, frame, history, ingestion, normalization, research_access)
├── data/
│   ├── contracts/                   # Missing values and physical unit specifications
│   ├── dictionaries/                # Authoritative YAML dictionaries (456 production positions, 0 unmapped)
│   ├── inbox/                       # Ingestion drop directory for automated file discovery
│   ├── raw/                         # Partitioned immutable Bronze storage (YYYY/MM/DD)
│   └── quarantine/                  # Isolated invalid/corrupted files with audit reasons
├── frontend/                        # React 18 + TypeScript + Vite Web Application
│   ├── src/
│   │   ├── components/              # GapTimeline, DailySummaryPanel, tables, status, frames, uploads
│   │   ├── lib/                     # API client, TypeScript interfaces, formatting utilities
│   │   └── pages/                   # DataOperations, UploadData, UploadHistory, ChargerDetail, HistoryTab, FramesTab
│   └── dist/                        # Production build bundle (verified clean)
├── pipelines/                       # Pure Analytical & Data Transformation Engines
│   ├── frame_reconstruction/        # Dynamic topology resolver, timestamp grouping, same-second sequencing
│   ├── historical/                  # Sampling cadence, gap detection, counter analysis, topology tracking, eligibility
│   ├── ingestion/                   # File day builder, coverage engine, ingestion state machine
│   ├── normalization/               # Safe type coercion, sentinel masking, Case A/B/C payload resolution
│   ├── persistence/                 # Raw object storage abstraction
│   ├── profiling/                   # Position-aware header parser, Polars profiler, column roles
│   ├── quality/                     # Deterministic 5-pillar scoring rules and daily coverage rules
│   ├── sources/                     # Filesystem inbox and manual upload source adapters
│   └── validation/                  # Schema compatibility, DictionaryRegistry
└── tests/                           # Complete Verification Test Suite (241 tests)
    ├── fixtures/                    # Deterministic test fixtures, 456-position builders, 7-day multi-charger files
    ├── integration/                 # End-to-end integration tests (API, frames, history, silver, benchmarks)
    └── unit/                        # Pure unit tests (coverage, frame builder, historical analytics, normalization)
```

---

## 4. Development Inventory

| Development Area | Capability | Implementation | Tests | Runtime Verified | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Bronze Ingestion** | Secure file intake, SHA-256 deduplication, immutable raw storage | `pipelines/ingestion/`, `backend/app/services/ingestion_service.py` | `test_manual_upload.py`, `test_api_uploads.py` | YES | `WORKING` | Max 512MB, 2000 cols, 5M rows |
| **Schema Discovery** | Position-aware header parser, SHA-256 header fingerprinting | `pipelines/profiling/header_parser.py`, `pipelines/validation/dictionary.py` | `test_production_contract.py` | YES | `WORKING` | Preserves CSV source order |
| **Data Dictionary** | 456 production positions cataloged, duplicate name disambiguation | `data/dictionaries/*.yaml`, `pipelines/validation/dictionary.py` | `test_production_contract.py` | YES | `WORKING` | 0 unmapped columns |
| **File Profiling** | Single-pass Polars metrics, median cadence, duplicate row forensics | `pipelines/profiling/profiler.py` | `test_known_sample_regression.py` | YES | `WORKING` | Detects multi-day spans & collisions |
| **Data Quality Engine** | 5-pillar scoring (Schema, Completeness, Validity, Duplication, Timestamps) | `pipelines/quality/`, `backend/app/services/quality_service.py` | `test_reconciliation.py` | YES | `WORKING` | Composite 0-100 score + findings |
| **Fleet Coverage** | Daily fleet reconciliation, missing chargers, cutoff tracking | `backend/app/services/coverage_service.py` | `test_coverage_engine.py` | YES | `WORKING` | Section 48 operational metrics |
| **Frame Reconstruction** | Dynamic topology demuxing, same-second deterministic sequencing | `pipelines/frame_reconstruction/` | `test_frame_reconstruction.py`, `test_frame_persistence.py` | YES | `WORKING` | Preserves (T, seq=0) vs (T, seq=1) |
| **Silver Normalization** | 11 typed domain tables, sentinel masking, atomic field provenance | `pipelines/normalization/`, `backend/app/services/normalization_service.py` | `test_silver_normalization.py`, `test_silver_coercion.py` | YES | `WORKING` | Case A/B/C conflict resolution |
| **Historical Continuity** | Cross-file timelines, zero-imputation gaps, counter drift tracking | `pipelines/historical/`, `backend/app/services/history_service.py` | `test_historical_continuity.py`, `test_history_benchmark.py` | YES | `WORKING` | Sub-5ms query response |
| **Research Access Layer** | Programmatic time-series extraction for scientific notebooks | `backend/app/services/research_access.py` | `test_historical_continuity.py` | YES | `WORKING` | Preserves raw event timestamps |
| **Snapshot Honesty** | Refusal of pattern research on single-observation chargers | `pipelines/historical/eligibility_evaluator.py` | `test_historical_continuity.py` | YES | `WORKING` | Flags 2,252-charger snapshot |
| **Frontend Web App** | Daily coverage, batch uploads, charger frames, historical charts | `frontend/src/` (React, TypeScript, Vite) | 56 Vitest tests | YES | `WORKING` | Zero ESLint / TS errors |
| **Discrete Events** | Charging session reconstruction & alarm/fault durations | `None` | `None` | NO | `NOT_IMPLEMENTED` | Phase 8 target |
| **Pattern Discovery** | Statistical correlation mining & pre-failure candidate discovery | `None` | `None` | NO | `NOT_IMPLEMENTED` | Phase 9 target |
| **Anomaly Detection** | Multivariate deviation scoring & peer divergence detection | `None` | `None` | NO | `NOT_IMPLEMENTED` | Phase 11 target |
| **Predictive Models** | Supervised failure risk & Remaining Useful Life (RUL) models | `None` | `None` | NO | `NOT_IMPLEMENTED` | Phase 13 target |

---

## 5. Phase-by-Phase Forensic Audit

### Phase 0 — Forensic Data Understanding
- **Objective**: Forensically profile the real production telemetry export (`16092026_170601_charger_status_latest.csv`) to establish actual schema, grain, and physical topology.
- **Actual Implementation**: Standalone forensic analyzer executed; generated `REAL_DATA_FORENSIC_AUDIT.md`, `REAL_DATA_FIELD_PROFILE.csv`, `REAL_DATA_FIELD_CATALOG.csv`, `REAL_DATA_ALARM_INVENTORY.csv`, `REAL_DATA_TOPOLOGY_REPORT.md`.
- **Inputs**: Real production CSV (25,587,651 bytes, 10,000 rows, 456 columns).
- **Processing**: Header extraction, duplicate header detection, column type inference, percentile distributions, sentinel candidate identification, row grain key discovery.
- **Outputs**: Discovered that file is an instantaneous **fleet latest-status snapshot** covering 2,252 chargers, where each charger has exactly 1 timestamp.
- **Verdict**: `COMPLETE`

### Phase 1 — Data Intake / Bronze
- **Objective**: Accept untrusted CSV telemetry files, reject duplicates, and persist immutable raw copies.
- **Actual Implementation**: `IngestionService`, `RawObjectStorage`, `TelemetryFileRepository`.
- **Inputs**: Multi-part HTTP uploads or filesystem inbox drops.
- **Processing**: Size and column limit validation, SHA-256 calculation, duplicate check, storage in `data/raw/YYYY/MM/DD/`.
- **Outputs**: `TelemetryFile` records with status `REGISTERED` or `DUPLICATE`.
- **Tests**: `test_manual_upload.py`, `test_api_uploads.py`.
- **Verdict**: `COMPLETE`

### Phase 2 — Schema Discovery & Field Intelligence
- **Objective**: Parse headers without pandas, compute fingerprints, and map source names to canonical specifications.
- **Actual Implementation**: `pipelines/profiling/header_parser.py`, `pipelines/validation/dictionary.py`, `backend/app/services/schema_service.py`.
- **Inputs**: Materialized CSV header row.
- **Processing**: Source-ordered parsing, SHA-256 fingerprinting, DictionaryRegistry resolution with (name, occurrence) disambiguation.
- **Outputs**: `SchemaVersion`, `FieldDefinition` records.
- **Tests**: `test_production_contract.py`.
- **Verdict**: `COMPLETE`

### Phase 3 — Profiling
- **Objective**: Single-pass metrics extraction across file content.
- **Actual Implementation**: `pipelines/profiling/profiler.py`, `pipelines/profiling/column_roles.py`.
- **Inputs**: Materialized CSV file.
- **Processing**: Polars scan for row counts, unique event times, dominant business date, median cadence, exact duplicate rows, collision groups.
- **Outputs**: `FileProfile` data structure.
- **Tests**: `test_known_sample_regression.py`.
- **Verdict**: `COMPLETE`

### Phase 4 — Data Quality & Trust
- **Objective**: Measure transport and representation quality; reconcile daily fleet delivery.
- **Actual Implementation**: `pipelines/quality/`, `backend/app/services/quality_service.py`, `backend/app/services/coverage_service.py`.
- **Inputs**: `FileProfile` + `QualityContext`.
- **Processing**: 5-pillar rule evaluation, composite 0-100 scoring, fleet delivery reconciliation, gap detection.
- **Outputs**: `DataQualityIssue` records, `ChargerDayCoverage` records.
- **Tests**: `test_reconciliation.py`, `test_coverage_engine.py`.
- **Verdict**: `COMPLETE`

### Phase 5 — Grain / Topology / Frame Reconstruction
- **Objective**: De-multiplex multi-row cartesian CSV rows into coherent physical observation frames.
- **Actual Implementation**: `pipelines/frame_reconstruction/`.
- **Inputs**: Untrusted raw rows + `RoleResolution`.
- **Processing**: Dynamic topology resolution, timestamp grouping by `(charger_id, event_time)`, deterministic sequencing by `frame_sequence`, canonical frame hashing.
- **Outputs**: `TelemetrySourceFrame` and `TelemetryFrameRow` database records.
- **Tests**: `test_frame_reconstruction.py`, `test_frame_persistence.py`.
- **Verdict**: `COMPLETE`

### Phase 5.5 — Production Data Contract Alignment
- **Objective**: Align data dictionary and contract system with 100% of the live commercial production dataset.
- **Actual Implementation**: `data/dictionaries/*.yaml`, `pipelines/validation/dictionary.py`.
- **Inputs**: `16092026_170601_charger_status_latest.csv` (456 positions).
- **Processing**: Bound all 456 positions (0 unmapped); bound sentinels (`999.0`, `-50.0`, `-150.0`); verified resistance as continuous float and alarms as discrete flags.
- **Outputs**: 100% production contract alignment verified.
- **Tests**: `test_production_contract.py` (7 tests, all passing).
- **Verdict**: `COMPLETE`

### Phase 6 — Canonical Silver Telemetry Normalization
- **Objective**: Convert reconstructed frames into typed, normalized relational domain tables with complete provenance and sentinel masking.
- **Actual Implementation**: `backend/app/models/silver_telemetry.py`, `pipelines/normalization/`, `backend/app/services/normalization_service.py`.
- **Inputs**: Canonical frames from Phase 5.
- **Processing**: Safe typed coercion, hardware sentinel masking (to NULL), Case A/B/C conflict resolution, SHA-256 config hashing, atomic per-field provenance tracking.
- **Outputs**: 11 Silver domain tables + `silver_observation_provenance`.
- **Tests**: `test_silver_normalization.py`, `test_silver_coercion.py`, `test_silver_payload_resolver.py`.
- **Verdict**: `COMPLETE`

### Phase 7 — Historical Continuity & Time-Series Research Layer
- **Objective**: Connect Silver observations across files and days into continuous, ordered timelines with zero data imputation.
- **Actual Implementation**: `pipelines/historical/`, `backend/app/services/history_service.py`, `backend/app/services/research_access.py`, `backend/app/api/v1/history.py`, `frontend/src/pages/HistoryTab.tsx`.
- **Inputs**: Canonical Silver tables.
- **Processing**: Global temporal sorting `(event_time ASC, frame_sequence ASC)`, empirical sampling cadence analysis, empirical outage gap detection, monotonic counter tracking, subcomponent presence tracking, snapshot honesty enforcement.
- **Outputs**: REST endpoints, frontend timeline tab, `ResearchDataAccessLayer` programmatic API.
- **Tests**: `test_historical_continuity.py`, `test_api_history.py`, `test_history_benchmark.py` (all passing).
- **Verdict**: `COMPLETE`

---

## 6. Checkpoint Capability Map

### CHECKPOINT 1 — RAW INGESTION
```
Telemetry File ──► Transport Validation ──► SHA-256 Hash ──► Immutable Bronze Store
```
- **Platform can now**: Accept untrusted CSVs via upload or inbox; enforce size/column safety limits; reject duplicate uploads idempotently; preserve bit-identical raw evidence.
- **Platform still cannot**: Parse headers, understand data types, or extract timestamps.

### CHECKPOINT 2 — SCHEMA INTELLIGENCE
```
Raw CSV Header ──► Position-Aware Parser ──► Dictionary Registry ──► Canonical Specs
```
- **Platform can now**: Recognize 456 production header positions; disambiguate duplicate column names; assign canonical names, entities, and physical units.
- **Platform still cannot**: Profile data distributions or detect hardware probe sentinels.

### CHECKPOINT 3 — PROFILING
```
Materialized File ──► Polars Single-Pass Profiler ──► Cadence & Duplicates Profile
```
- **Platform can now**: Extract row counts, unique event timestamps, dominant business date, median cadence; detect multi-day files and duplicate rows.
- **Platform still cannot**: Score quality or assemble multi-row frames.

### CHECKPOINT 4 — DATA QUALITY & FLEET COVERAGE
```
File Profile ──► 5-Pillar Rule Evaluation ──► Quality Score & Daily Fleet Reconciliation
```
- **Platform can now**: Assign composite 0–100 quality scores; isolate corrupt files in quarantine; reconcile daily fleet arrivals against cutoffs; identify missing chargers.
- **Platform still cannot**: Reconstruct physical frames or query typed subcomponent telemetry.

### CHECKPOINT 5 — CANONICAL FRAME RECONSTRUCTION
```
Multiplexed Rows ──► Topology Resolver ──► Group by (Charger, Time) ──► Ordered Canonical Frames
```
- **Platform can now**: De-multiplex multi-row cartesian CSV rows; resolve dynamic hardware topologies (connectors x SMRs x rectifiers); preserve same-second captures (`seq=0` vs `seq=1`).
- **Platform still cannot**: Query typed values (values remain string key-value dictionaries) or mask sentinels.

### CHECKPOINT 6 — PRODUCTION CONTRACT ALIGNMENT
```
456-Position Schema ──► Positional Registry ──► Sentinel Bindings ──► Contract Lock
```
- **Platform can now**: Guarantee 100% field mapping of live commercial fleet data; bind hardware thermocouple sentinels (`999.0`, `-50.0`, `-150.0`).
- **Platform still cannot**: Query relational typed tables directly.

### CHECKPOINT 7 — CANONICAL SILVER NORMALIZATION
```
Canonical Frames ──► Safe Coercion & Sentinel Masker ──► 11 Typed Silver Domain Tables
```
- **Platform can now**: Query typed relational tables partitioned by subcomponent; mask hardware sentinels to `NULL`; trace every cell via atomic provenance.
- **Platform still cannot**: Query cross-file continuous timelines or analyze multi-day sampling regularity.

### CHECKPOINT 8 — HISTORICAL CONTINUITY & RESEARCH LAYER (CURRENT)
```
Silver Tables ──► Temporal Sorter (Time ASC, Seq ASC) ──► Gap Detector & Research Access Layer
```
- **Platform can now**: Stream continuous timelines across files and days; detect empirical outages with ZERO imputation; track monotonic counter drift/resets; track subcomponent lifecycles (`first_seen`/`last_seen`); access clean time-series programmatically in $< 5 \text{ ms}$.
- **Platform still cannot**: Group continuous states into discrete charging sessions; detect multi-variate anomalies; predict equipment failure risk.

---

## 7. Current Service Map

```
[Untrusted CSV] ──► [IngestionService] ──► [RawObjectStorage (Bronze)]
                             │
                             ▼
                    [SchemaService] ──► [DictionaryRegistry (456 Positions)]
                             │
                             ▼
                    [FileProfiler] ──► [FileProfile Data Structure]
                             │
                             ▼
                    [QualityService] ──► [DataQualityIssue / Coverage]
                             │
                             ▼
             [FrameReconstructionService] ──► [TelemetrySourceFrame (Canonical)]
                             │
                             ▼
               [NormalizationService] ──► [11 Silver Domain Tables + Provenance]
                             │
                             ▼
            [HistoricalContinuityService] ──► [Continuous Timelines & Gap Engine]
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [REST API Endpoints]             [ResearchDataAccessLayer]
            │                                 │
            ▼                                 ▼
   [Frontend Web Console]           [Future Phase 8/9 Analytics]
```

---

## 8. Data Transformation Map

### Example 1: Gun Temperature DC+ (Continuous Telemetry with Hardware Sentinel)
```
1. Untrusted CSV:
   Position 31 header: "Gun Temp Dc+"
   Value: "999.0" (Hardware thermocouple open-circuit disconnect)

2. Bronze Layer:
   Preserved raw string "999.0" in immutable Parquet/CSV object.

3. Schema Contract:
   Position 31 resolved to canonical "gun_temp_dc_positive".
   Entity: CONNECTOR (ID: "1"). Unit: "°C". Type: FLOAT.
   Bound Sentinel: [999.0].

4. Frame Reconstruction:
   Captured in canonical frame payload: {"gun_temp_dc_positive": "999.0"}.
   Order: (charger_id="CH_01", event_time=2026-09-16 10:15:00, seq=0).

5. Silver Normalization:
   Safe coercion evaluates 999.0 == bound sentinel.
   Output in silver_connector_telemetry:
     gun_temp_dc_positive = NULL
   Output in silver_observation_provenance:
     raw_value = "999.0", normalized_value = NULL, was_sentinel = TRUE,
     transformation = "MASKED_HARDWARE_SENTINEL"

6. Historical Continuity:
   Observation streamed in true chronological sequence.
   Value returned: None (provenance flag indicates masked sentinel).
   Cadence and gap detection treat frame as present; thermal averages are not corrupted.
```

### Example 2: SMR PFC Temperature (Continuous Thermal Telemetry)
```
1. Untrusted CSV:
   Position 88 header: "SMR Pfc Temperature"
   Value: "52.4"

2. Bronze Layer:
   Preserved raw string "52.4".

3. Schema Contract:
   Position 88 resolved to canonical "smr_pfc_temperature".
   Entity: SMR (ID: "3"). Unit: "°C". Type: FLOAT.

4. Frame Reconstruction:
   Captured in canonical frame payload: {"smr_pfc_temperature": "52.4"}.

5. Silver Normalization:
   Parsed as valid float 52.4.
   Output in silver_smr_telemetry:
     smr_id = "3", smr_pfc_temperature = 52.4

6. Historical Continuity:
   Queried via GET /api/v1/chargers/CH_01/components/smr/3/history.
   Evaluated for thermal rise over time; subcomponent presence recorded as active.
```

### Example 3: Phase 1 to Neutral Voltage (Grid Electrical Telemetry)
```
1. Untrusted CSV:
   Position 5 header: "Phase 1 - Neutral Voltage"
   Value: "238.6"

2. Bronze Layer:
   Preserved raw string "238.6".

3. Schema Contract:
   Position 5 resolved to canonical "grid_voltage_v1".
   Entity: CHARGER. Unit: "V". Type: FLOAT.

4. Frame Reconstruction:
   Captured in canonical frame payload: {"grid_voltage_v1": "238.6"}.

5. Silver Normalization:
   Parsed as valid float 238.6.
   Output in silver_charger_telemetry:
     grid_voltage_v1 = 238.6

6. Historical Continuity:
   Queried via GET /api/v1/chargers/CH_01/signals/grid_voltage_v1/history.
   Returns clean float series (event_time, seq, 238.6).
```

### Example 4: Cellular Signal Strength (RSRP - Communication Metric)
```
1. Untrusted CSV:
   Position 122 header: "RSRP"
   Value: "-92"

2. Bronze Layer:
   Preserved raw string "-92".

3. Schema Contract:
   Position 122 resolved to canonical "rsrp".
   Entity: COMMUNICATION. Unit: "dBm". Type: INTEGER.

4. Frame Reconstruction:
   Captured in canonical frame payload: {"rsrp": "-92"}.

5. Silver Normalization:
   Parsed as integer -92.
   Output in silver_communication_observation:
     rsrp = -92

6. Historical Continuity:
   Queried via ResearchDataAccessLayer.
   Surfaces communication fades preceding telemetry gaps.
```

### Example 5: Emergency Stop (Alarm / Protection Flag)
```
1. Untrusted CSV:
   Position 425 header: "Emergency Stop"
   Value: "1"

2. Bronze Layer:
   Preserved raw string "1".

3. Schema Contract:
   Position 425 resolved to canonical "emergency_stop".
   Entity: ALARM. Class: ALARM_FLAG. Unit: None. Type: ENUM.

4. Frame Reconstruction:
   Captured in canonical frame payload: {"emergency_stop": "1"}.

5. Silver Normalization:
   Parsed as discrete enum / boolean flag True.
   Output in silver_alarm_observation:
     emergency_stop = "ACTIVE" / "1"

6. Historical Continuity:
   Temporal stream preserves exact second of E-Stop activation.
   [Next Phase 8 Target]: Converts recurring active states into discrete event spans.
```

---

## 9. Data State Evolution

| Data State | Meaning | Platform Status |
| :--- | :--- | :--- |
| **SOURCE DATA** | Untrusted external CSV files on network, disk, or API | **BUILT** |
| **RAW DATA** | Immutable, SHA-256 hashed Bronze storage in partitioned directories | **BUILT** |
| **TRUSTED RAW DATA** | File validated for size, columns, row bounds, and transport safety | **BUILT** |
| **UNDERSTOOD DATA** | Header positions mapped to canonical dictionary specs with units | **BUILT** |
| **PROFILED DATA** | Single-pass metrics: row counts, timestamps, cadence, duplicate rows | **BUILT** |
| **QUALITY-ASSESSED DATA** | Scored across 5 pillars; coverage reconciled; gaps quantified | **BUILT** |
| **RECONSTRUCTED DATA** | Multi-row cartesian CSV rows de-multiplexed into canonical frames | **BUILT** |
| **NORMALIZED DATA** | 11 typed Silver domain tables with masked sentinels and provenance | **BUILT** |
| **HISTORICAL DATA** | Continuous cross-file timelines ordered strictly by event time | **BUILT** |
| **EVENT DATA** | Discrete charging sessions, alarm event spans, config changes | `NOT BUILT` (Phase 8) |
| **PATTERN DATA** | Statistical correlations, thermal drift trends, peer distributions | `NOT BUILT` (Phase 9) |
| **FEATURE DATA** | Rolling window slopes, electrical imbalances, cycle counts | `NOT BUILT` (Phase 10) |
| **ANOMALY DATA** | Multivariate outlier scores, Mahalanobis distances, drift flags | `NOT BUILT` (Phase 11) |
| **LABELED FAILURE DATA** | Telemetry linked to external CMMS work orders & failure ground truth | `NOT BUILT` (Phase 12) |
| **PREDICTIVE DATA** | Supervised failure risk probabilities, Remaining Useful Life (RUL) | `NOT BUILT` (Phase 13) |

---

## 10. Capability Maturity Ladder

```
LEVEL 10: Can predict failure risk & Remaining Useful Life (RUL)  [NOT BUILT]
LEVEL 9:  Can link telemetry precursors to real failure records  [NOT BUILT]
LEVEL 8:  Can identify statistical anomalies & peer divergence   [NOT BUILT]
LEVEL 7:  Can discover behavioral degradation patterns          [NOT BUILT]
LEVEL 6:  Can reconstruct discrete operational & alarm events    [NOT BUILT]
─────────────────────────────────────────────────────────────────────────────
LEVEL 5:  Can construct continuous component history timelines   [CURRENT - BUILT]
LEVEL 4:  Can convert telemetry into clean, typed Silver data   [BUILT]
LEVEL 3:  Can reconstruct what the charger actually reported     [BUILT]
LEVEL 2:  Can determine whether telemetry is trustworthy         [BUILT]
LEVEL 1:  Can understand schema semantics and physical units     [BUILT]
LEVEL 0:  Can store immutable raw telemetry files                [BUILT]
```

**Current Platform Position**: **LEVEL 5 (Continuous Component History)**.

---

## 11. Detailed Phase 6 Explanation

### What Enters Phase 6?
Untrusted reconstructed canonical frames produced by Phase 5 (`TelemetrySourceFrame`). Each frame contains a dictionary of string key-value pairs (e.g., `{"Gun Temp Dc+": "999.0", "Phase 1 Voltage": "238.6"}`) along with its natural key `(charger_id, event_time, frame_sequence)`.

### What Does Phase 6 Do?
Phase 6 maps every position in the raw payload into 11 specialized physical relational tables. It applies safe typed parsers (floats, ints, booleans, enums), binds hardware sentinels, resolves multi-row payload conflicts (Cases A, B, and C), calculates SHA-256 configuration hashes, and records atomic per-field provenance.

### What Does "Normalization" Mean Here?
Normalization means converting flat, multi-entity string dictionaries into a **typed 3rd-normal-form relational model** reflecting the physical hardware architecture of an EV charger (Cabinet, Connectors, SMRs, Rectifiers, Contactors, Alarms, Sessions, Configuration).

### Is Phase 6 "Cleaning"?
**NO.** Phase 6 does NOT clean data by inventing, interpolating, smoothing, or guessing values.
- **Cleaning vs Normalization**: Cleaning alters data to look "nice". Normalization coerces strings into authoritative typed representations.
- **Sentinel Handling**: When a thermocouple disconnects, it reports `999.0`. Silver normalizes this to SQL `NULL` to avoid corrupting arithmetic, but **preserves the raw text `"999.0"` in provenance**.
- **Conflict Resolution**: If two rows in the same frame claim contradictory values for the same sensor, Silver coerces the field to `NULL`, logs a conflict warning, and records both raw values in provenance. Nothing is guessed.

### What Comes Out?
11 typed relational domain tables (`silver_charger_telemetry`, `silver_connector_telemetry`, `silver_smr_telemetry`, etc.) and the `silver_observation_provenance` audit table.

### Why Is Phase 6 Required?
Downstream historical continuity, anomaly detection, and ML models cannot run efficiently or safely over unindexed JSON strings containing raw string sentinels like `"999.0"` or `"-50.0"`. Phase 6 establishes relational query performance and type safety.

### What Can the Product Do After Phase 6 That It Could Not Do Before?
- Execute indexed SQL queries on physical components (e.g. `SELECT AVG(smr_dc_dc_temperature) FROM silver_smr_telemetry WHERE smr_id = '3'`).
- Compute arithmetic metrics without `999.0` sentinels causing false overheating alarms.
- Provide complete forensic auditability from any database cell back to the exact source CSV position.

### What Can It Still NOT Do?
- Cannot assemble cross-file longitudinal continuous streams (handled by Phase 7).
- Cannot reconstruct discrete session lifecycles or alarm event spans (Phase 8).
- Cannot detect degradation patterns or predict failures (Phases 9–13).

---

## 12. Current Product Flow

```
[USER / OPERATOR]
       │
       ▼
Upload Telemetry CSV ──────────────────────────► 🟢 WORKING
       │
       ▼
Transport Validation & SHA-256 Deduplication ──► 🟢 WORKING
       │
       ▼
Immutable Bronze Storage ──────────────────────► 🟢 WORKING
       │
       ▼
Position-Aware Schema Recognition (456 Fields) ─► 🟢 WORKING
       │
       ▼
Single-Pass Polars Profiling & Cadence ────────► 🟢 WORKING
       │
       ▼
5-Pillar Data Quality Scoring ────────────────► 🟢 WORKING
       │
       ▼
Daily Fleet Coverage Reconciliation ───────────► 🟢 WORKING
       │
       ▼
Dynamic Topology & Frame Reconstruction ───────► 🟢 WORKING
       │
       ▼
Canonical Silver Normalization (11 Tables) ────► 🟢 WORKING
       │
       ▼
Historical Continuity & Zero-Imputation Gaps ──► 🟢 WORKING
       │
       ▼
Discrete Event Reconstruction (Sessions/Alarms) ─► 🔴 NOT BUILT (Phase 8 Target)
       │
       ▼
Scientific Pattern Discovery ──────────────────► 🔴 NOT BUILT (Phase 9 Target)
       │
       ▼
Behavioral Baselines & Anomaly Detection ──────► 🔴 NOT BUILT (Phases 10-11 Target)
       │
       ▼
Predictive Failure Risk & Maintenance Intel ────► 🔴 NOT BUILT (Phases 12-14 Target)
```

---

## 13. User-Facing Product Today

### Backend Capabilities:
- 34 REST API endpoints across `/api/v1/`:
  - 5 Upload & Ingestion endpoints
  - 8 Data Operations & Coverage endpoints
  - 5 Frame Reconstruction endpoints
  - 6 Silver Normalization endpoints
  - 8 Historical Continuity & Timeline endpoints
  - 1 Health check endpoint
- Keyset cursor pagination for high-volume time-series streaming.
- Programmatic `ResearchDataAccessLayer` for Python notebooks and analytics.

### User-Visible UI Capabilities:
- **Data Operations Console**: View fleet delivery summaries for any business date; filter chargers by delivery status (`ON_TIME`, `LATE`, `MISSING`); inspect daily rule findings.
- **Upload Data Screen**: Drag-and-drop or select multi-file telemetry batches with progress feedback and staging limits.
- **Upload History Screen**: Inspect historical upload batches, file processing statuses (`REGISTERED`, `PROFILING`, `NORMALIZED`), quality scores, and quarantine reasons.
- **Charger Detail Console**:
  - General Info: Identifiers (`Charger Id`, `OCPP Id`), station, model, firmware.
  - Reconstructed Frames Tab: Browse canonical frames, diff two frames position-by-position, inspect collision groups and replays.
  - Historical Continuity Tab:
    - Summary Stats: Total observations, time span, median cadence, same-second frames, detected gaps.
    - Snapshot Honesty Alert: Prominently warns user when only 1 observation is available.
    - Interactive Time-Series: Select component (Cabinet, Connector 1-2, SMR 1-6, Rectifier 1-6) and canonical signal (voltage, current, temperature) to render live chronological charts.
    - Observation Table: Detailed data grid with timestamps, frame sequences, and electrical readings.
    - Data Gaps Explorer: Table of empirical outages detailing start/end timestamps, durations, and missing intervals.

---

## 14. Remaining Development Roadmap

```
PHASE 7 (Complete) ──► PHASE 8 ──► PHASE 9 ──► PHASE 10 ──► PHASE 11 ──► PHASE 12 ──► PHASE 13 ──► PHASE 14
Historical            Discrete     Pattern     Behavioral   Anomaly      Failure      Predictive   Maintenance
Continuity            Events       Discovery   Baselines    Detection    Ground Truth Models       Intelligence
```

### Phase 8: Discrete Event Reconstruction
- **Objective**: Transform continuous status readings into discrete operational event spans.
- **Inputs**: Canonical Silver observations and historical timelines.
- **Development**:
  - Reconstruct charging session lifecycle: `PLUG_IN -> AUTHENTICATED -> CHARGING -> FINISHING -> DISCONNECTED`.
  - Reconstruct alarm and fault event spans: `ALARM_ON -> ACTIVE_HOLD -> ALARM_OFF` with start time, end time, duration, and severity.
  - Reconstruct configuration state changes: parameter diffs with exact timestamps.
- **Outputs**: `event_charging_session`, `event_alarm_span`, `event_configuration_change` tables.
- **Capability Unlocked**: "How many times did Gun 1 trip on over-temperature in August, and how long did each fault last?"

### Phase 9: Scientific Pattern Discovery
- **Objective**: Identify statistical correlations, degradation signatures, and precursor candidates.
- **Inputs**: Multi-day continuous telemetry + operational event spans.
- **Development**:
  - Fleet cross-sectional cohort analysis (distribution of thermal metrics across 2,252 chargers).
  - Longitudinal trend analysis (drift in SMR PFC temperature or internal resistance over 30 days).
  - Precursor candidate identification (transient electrical noise preceding contactor trips).
- **Outputs**: Verified degradation candidate signals and statistical pattern inventory.
- **Capability Unlocked**: "Statistical identification that SMR 3 exhibits positive thermal drift relative to peer modules."

### Phase 10: Normative Behavioral Baselines
- **Objective**: Establish mathematical definitions of "normal" operating behavior across 3 tiers.
- **Inputs**: Historical telemetry and pattern catalog.
- **Development**:
  - Tier 1: Component vs Self Historical Baseline (e.g. normal heating rate for Connector 1).
  - Tier 2: Component vs Internal Peers (e.g. SMR 3 vs SMR 1, 2, 4 in the same cabinet).
  - Tier 3: Charger vs Fleet Cohort (e.g. Charger vs all 120kW Exicom units in same ambient temperature band).
- **Outputs**: Normative baseline profiles and parameter distribution models.
- **Capability Unlocked**: Objective detection of when a module deviates from expected behavior.

### Phase 11: Multivariate Anomaly Detection
- **Objective**: Compute continuous statistical anomaly scores without labeling equipment failure.
- **Inputs**: Real-time telemetry + behavioral baselines.
- **Development**:
  - Multivariate distance metrics (Mahalanobis distance, PCA reconstruction error, z-score clustering).
  - Thermal divergence detectors, electrical imbalance alarms, communication fade clusters.
- **Outputs**: Continuous anomaly scores and prioritized operational alerts.
- **Capability Unlocked**: "Flag Charger CH_01: SMR 3 is running 12°C hotter than peers at identical current draw."

### Phase 12: Failure Ground Truth Linkage
- **Objective**: Ingest external maintenance records to link telemetry precursors with confirmed physical failures.
- **Inputs**: Anomaly data + external CMMS / ticketing logs (work orders, component replacement dates).
- **Development**:
  - Data ingestion pipeline for maintenance ticketing (SAP, Jira, ServiceNow).
  - Failure event matching: correlate ticket timestamps with preceding telemetry anomalies.
  - Supervised training set construction with verified ground-truth labels.
- **Outputs**: Curated, labeled machine learning training datasets.
- **Capability Unlocked**: Confirmed correlation between observed telemetry degradation and actual hardware breakdown.

### Phase 13: Supervised Predictive Models
- **Objective**: Estimate failure risk probability and Remaining Useful Life (RUL).
- **Inputs**: Labeled training datasets from Phase 12.
- **Development**:
  - Failure mode classifiers (Random Forest, XGBoost, Temporal Convolutional Networks).
  - Survival analysis & Remaining Useful Life estimation (Weibull / Cox proportional hazards).
  - Feature attribution & explainability engine (SHAP values).
- **Outputs**: Calibrated breakdown probability scores and RUL estimates.
- **Capability Unlocked**: "Charger CH_01 has an 82% probability of SMR 3 power stage failure within 7 days."

### Phase 14: Maintenance Intelligence Console
- **Objective**: Field operations dashboard providing prioritized maintenance recommendations.
- **Inputs**: Predictive models + failure risk scores.
- **Development**:
  - Fleet risk ranking and proactive dispatch queues.
  - Component diagnostic worksheets with physical evidence trails.
  - Two-way API dispatch to operator CMS / ticketing systems.
- **Outputs**: Production maintenance intelligence dashboard.
- **Capability Unlocked**: Proactive field technician dispatch before catastrophic charger outage occurs.

---

## 15. Pattern Identification Path

Pattern identification cannot be unlocked in a single step. It has three distinct milestones:

```
[Phase 7 Complete] ──► MILESTONE 1: Cross-Sectional Patterns (Fleet Snapshot)
                              │
[Phase 8 Complete] ──► MILESTONE 2: Temporal Patterns (Continuous Multi-Day Data)
                              │
[Phase 12 Complete] ─► MILESTONE 3: Pre-Failure Patterns (Telemetry + Failure Ground Truth)
```

1. **Cross-Sectional Patterns (Unlocked NOW in Phase 7)**:
   - Possible across the 2,252 chargers in `16092026_170601_charger_status_latest.csv`.
   - Examples: Distribution of grid voltages across India; correlation between ambient cabinet temperature and SMR temperatures at a single point in time; ratio of online vs offline chargers by operator.
2. **Temporal Patterns (Requires Phase 8 + Multi-Day Continuous Telemetry)**:
   - Possible once consecutive daily files or streaming logs are ingested.
   - Examples: Diurnal thermal cycling; contactor closing delay trends; degradation of insulation resistance over weeks; charging session completion ratios.
3. **Pre-Failure Patterns (Requires Phase 12 + Maintenance Ground Truth)**:
   - Possible ONLY after external maintenance and breakdown records are ingested.
   - Examples: Identifying which specific thermal or electrical patterns reliably precede an SMR rectifier short or a contactor weld.

---

## 16. Comprehensive Test Results

Actual fresh test results executed on 2026-09-17:

### Backend Test Suite (`pytest`)
- **Command**: `CPI_REAL_SAMPLE_PATH=16092026_170601_charger_status_latest.csv .venv/bin/pytest`
- **Collected**: 241 test items across unit, integration, and contract suites.
- **Result**: **241 passed in 54.11 seconds** (100% pass rate, 0 failed, 0 skipped, 0 xfailed).
- **Coverage**:
  - Data operations & fleet coverage: 27 tests
  - Reconstructed frames & persistence: 29 tests
  - Historical continuity & benchmarks: 14 tests
  - Known sample & production contract: 12 tests
  - Manual upload & file day builder: 33 tests
  - Silver normalization & payload resolver: 33 tests
  - Unit coverage engine & frame reconstruction: 56 tests
  - Historical analytical engines: 10 tests
  - Coercion & sentinel masking: 27 tests

### Static Analysis & Type Checking
- **Linter (`ruff check .`)**: **All checks passed!** (0 errors).
- **Code Formatting (`ruff format --check .`)**: 95 files formatted; 65 historical files would be reformatted by ruff (preserved per non-destructive audit rule).
- **Type Checker (`mypy backend/app pipelines tests`)**: **Success: no issues found in 133 source files**.
- **Database Migrations (`alembic check`)**: **No new upgrade operations detected** (PostgreSQL schema is in 100% exact parity with SQLAlchemy models).

### Frontend Verification (`npm`)
- **Linter (`npm run lint`)**: **0 warnings, 0 errors** (ESLint clean).
- **Type Checker (`npm run typecheck`)**: **0 errors** (`tsc --noEmit` clean).
- **Unit & Component Tests (`npm test -- --run`)**: **56 passed across 5 suites in 680ms**.
- **Production Bundle (`npm run build`)**: **Built cleanly in 329ms** (`dist/index.html` 0.41 kB, `dist/assets/index.js` 232 kB).

---

## 17. Architectural Risks

1. **Fleet Snapshot vs Time-Series Conflation**: The production sample `16092026_170601_charger_status_latest.csv` contains only 1 timestamp per charger. Attempting to train predictive ML models on this file alone will fail. The platform's `is_snapshot_only` check must remain strictly enforced.
2. **PostgreSQL Large-Table Growth**: `silver_observation_provenance` records atomic lineage per field. For a 456-column file with 10,000 rows, this generates up to 4.5 million provenance rows per file. In production, provenance retention policies (e.g. partition drop after 90 days) or columnar storage will be required.
3. **External Maintenance Ground Truth Dependency**: Predictive maintenance cannot be completed purely with telemetry. Without access to CMMS work orders or component replacement records, the platform cannot advance past Phase 11 (Anomaly Detection) to Phase 13 (Supervised Failure Prediction).

---

## 18. Dead / Legacy / Obsolete Development

1. **Synthetic Column Count Expectations (~449 vs 456)**: Early Phase 1C fixtures in `tests/fixtures/builders.py` used 449 positions based on synthetic specs. The authoritative standard is now 456 positions as verified in `test_production_contract.py`. The 449-position builder remains useful for legacy regression testing but should not be used for new production tests.
2. **Old In-Memory Dictionary Assumptions**: Early validation scripts assumed in-memory dictionaries without occurrences. The system now universally uses `DictionaryRegistry` with explicit `(name, occurrence)` tuple keys.

---

## 19. Product Completion Definition

The Charger Predictive Intelligence Platform reaches **Commercial Completion** when:
1. **Continuous Telemetry Ingestion**: Automated ingestion from live RMS streams across 2,000+ chargers.
2. **Proven Canonical Normalization**: Continuous conversion to Silver domain tables with 100% field accountability.
3. **Discrete Event Intelligence**: Automated extraction of charging sessions and alarm event spans.
4. **Statistical Anomaly Scoring**: Continuous multivariate anomaly scores highlighting thermal, electrical, and communication degradation.
5. **Calibrated Breakdown Predictions**: Supervised machine learning models estimating Remaining Useful Life (RUL) with $\ge 80\%$ precision on confirmed hardware failures.
6. **Actionable Operations Console**: Web UI providing prioritized maintenance queues with SHAP root-cause evidence, enabling proactive technician dispatch before chargers trip offline.
