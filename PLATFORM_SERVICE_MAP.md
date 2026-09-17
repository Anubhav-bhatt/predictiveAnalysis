# CHARGER PREDICTIVE INTELLIGENCE PLATFORM — SERVICE ARCHITECTURE MAP

## 1. Executive Overview

This document presents the authoritative service maps for the Charger Predictive Intelligence Platform:
1. **CURRENT ARCHITECTURE**: Represents only the operational, runtime-verified services implemented through Phase 7.
2. **TARGET ARCHITECTURE**: Represents the complete end-to-end predictive maintenance intelligence platform spanning ingestion to field service dispatch.

Status Legend:
- `[BUILT]`: Operational in source code, covered by automated integration tests, and verified in runtime.
- `[PARTIAL]`: Component partially implemented or active with operational constraints.
- `[PLANNED]`: Future stage designed in architecture roadmap; no production implementation exists.

---

## 2. CURRENT PLATFORM ARCHITECTURE (Phases 1A through 7)

```
                       DATA SOURCES
               ┌─────────────┬─────────────┐
               │             │             │
        Filesystem Inbox  Staging Upload  Future RMS
               │             │             │
            [BUILT]       [BUILT]      [PLANNED]
               └─────────────┼─────────────┘
                             │ Untrusted CSV
                             ▼
                 INGESTION & BRONZE SERVICE [BUILT]
                 ├── IngestionService
                 ├── FilesystemTelemetrySource / StagingUploadSource
                 └── RawObjectStorage (Immutable Partitioned Parquet/CSV)
                             │
                             ▼
                 SCHEMA INTELLIGENCE SERVICE [BUILT]
                 ├── HeaderParser (Position-aware, source-ordered)
                 ├── DictionaryRegistry (456 production positions)
                 └── SchemaRepository (Fingerprinting & versioning)
                             │
                             ▼
                 PROFILING & METRICS ENGINE [BUILT]
                 ├── FileProfiler (Pure Polars single-pass)
                 ├── EventTimeParser (Explicit formats, zero guess)
                 └── DuplicateDetector (Exact duplicates & collisions)
                             │
                             ▼
                 DATA QUALITY SERVICE [BUILT]
                 ├── QualityService (5 weighted pillars: Schema, Completeness,
                 │                   Validity, Duplication, Timestamps)
                 └── CoverageService (Daily fleet reconciliation & gaps)
                             │
                             ▼
                 FRAME RECONSTRUCTION SERVICE [BUILT]
                 ├── FrameTopologyResolver (Dynamic Connectors x SMRs x Rectifiers)
                 ├── TimestampGroupBuilder ((charger_id, event_time) isolation)
                 ├── FrameBuilder (Ordered frames, same-second sequencing)
                 └── CanonicalSerializer (SHA-256 frame payload hashing)
                             │
                             ▼
                 SILVER NORMALIZATION SERVICE [BUILT]
                 ├── NormalizationService
                 ├── PayloadResolver (Case A/B/C conflict resolution)
                 ├── SafeCoercion & SentinelMasker (999.0, -50.0, -150.0 -> NULL)
                 ├── 11 Physical Domain Repositories (SilverRepository)
                 └── SilverObservationProvenance (Atomic per-field lineage)
                             │
                             ▼
                 HISTORICAL CONTINUITY SERVICE [BUILT]
                 ├── HistoricalContinuityService (Zero redundant Silver copying)
                 ├── SamplingCadenceAnalyzer (Empirical delta statistics)
                 ├── EmpiricalGapDetector (Zero-imputation outage bounding)
                 ├── LifecycleCounterAnalyzer (Monotonic drift & reset detection)
                 ├── PhysicalTopologyTracker (first_seen, last_seen per subcomponent)
                 ├── PatternEligibilityEvaluator (Snapshot honesty enforcement)
                 └── ResearchDataAccessLayer (Programmatic Python time-series)
                             │
                             ▼
                     OPERATIONAL REST API [BUILT]
                 ├── /api/v1/ingestion/uploads (Batch upload & limits)
                 ├── /api/v1/data-operations/* (Daily fleet delivery & gaps)
                 ├── /api/v1/frames/* (Canonical reconstructed frames)
                 ├── /api/v1/chargers/{id}/silver/* (Typed component telemetry)
                 ├── /api/v1/chargers/{id}/history (Chronological streams)
                 └── /api/v1/chargers/{id}/summary (Sampling & continuity)
                             │
                             ▼
                   FRONTEND WEB APPLICATION [BUILT]
                 ├── Data Operations Console (Daily coverage, fleet delivery)
                 ├── File Upload & Ingestion Tracking (Upload batches, status)
                 ├── Charger Detail Console (Metadata, frames, gaps)
                 └── Historical Continuity Tab (Cadence, chart streams, gaps)
```

---

## 3. Current Service Data Flow Details

### 3.1 Ingestion & Bronze Storage Service
- **Input**: Raw telemetry CSV files (`data/inbox/` or multi-part HTTP upload).
- **Processing**: Enforces transport limits (512MB, 2000 columns, 5M rows); computes SHA-256; deduplicates identical byte arrivals idempotently; stores immutable raw bytes in `data/raw/YYYY/MM/DD/`.
- **Output**: `TelemetryFile` database record in `REGISTERED` state + immutable bronze storage reference.
- **Next Consumer**: Schema Intelligence & Profiling Engines.

### 3.2 Schema Intelligence Service
- **Input**: Local materialized path of raw CSV file.
- **Processing**: Extracts raw header positions (1–456); resolves names against `data/dictionaries/*.yaml` using explicit `(source_name, occurrence)` pairs; generates SHA-256 `header_fingerprint`; matches known schema versions.
- **Output**: `ResolvedSchema` with canonical mapping, physical data types, physical units, and target Silver entity routing for every position.
- **Next Consumer**: Profiling Engine and Quality Service.

### 3.3 Profiling Engine
- **Input**: Materialized CSV file + `RoleResolution` (identifies columns for event_time, charger_id, connector, SMR, rectifier).
- **Processing**: Single-pass scan computing row count, unique event timestamps, dominant business date, multi-day span, median sampling cadence, and exact duplicate rows.
- **Output**: `FileProfile` data structure.
- **Next Consumer**: Data Quality Service & Frame Reconstruction.

### 3.4 Data Quality & Fleet Coverage Service
- **Input**: `FileProfile` + `QualityContext`.
- **Processing**: Runs deterministic quality rules across 5 pillars (schema conformance, completeness, validity, duplicate ratio, timestamp parsing); computes composite 0–100 score; reconciles expected fleet arrivals against configured cutoff times; detects fleet delivery gaps.
- **Output**: `DataQualityIssue` rows, `ChargerDayCoverage` records, composite score in `TelemetryFile`.
- **Next Consumer**: Frame Reconstruction Service.

### 3.5 Frame Reconstruction Service
- **Input**: Untrusted raw rows + resolved roles + dynamic topology config.
- **Processing**: Groups raw rows by `(charger_id, event_time)`; resolves physical topology (e.g. 2 connectors x 4 SMRs = 8 rows); builds ordered frames sequenced by `frame_sequence`; detects same-second distinct captures; isolates replays; serializes frame canonical payload.
- **Output**: `TelemetrySourceFrame` and `TelemetryFrameRow` database records.
- **Next Consumer**: Silver Normalization Service.

### 3.6 Silver Normalization Service
- **Input**: Reconstructed frames + 456-position Dictionary Registry.
- **Processing**: De-multiplexes multi-row frame payloads; applies Case A/B/C conflict resolution; strictly coerces strings into typed floats, ints, booleans, and enums; masks hardware probe sentinels (`999.0`, `-50.0`, `-150.0`) to SQL NULL; computes SHA-256 `config_hash`; records atomic per-field lineage.
- **Output**: 11 typed Silver domain tables + `silver_observation_provenance`.
- **Next Consumer**: Historical Continuity Service.

### 3.7 Historical Continuity Service
- **Input**: Canonical Silver tables (`silver_charger_telemetry`, `silver_connector_telemetry`, `silver_smr_telemetry`, `silver_rectifier_telemetry`, etc.).
- **Processing**: Enforces global temporal ordering `(event_time ASC, frame_sequence ASC)`; analyzes sampling regularity ($\Delta t$ percentiles); detects empirical outages with ZERO imputation; tracks monotonic lifecycle counters; maintains subcomponent presence intervals; flags single-point snapshots.
- **Output**: Unified chronological observation streams, gap summaries, component presence records, and `ResearchDataAccessLayer` API.
- **Next Consumer**: Operational REST API, Frontend UI, and future Phase 8/9 engines.

---

## 4. TARGET END-STATE PLATFORM ARCHITECTURE (Phases 1 through 14)

```
                 COMMERCIAL EV CHARGER FLEET
                 (2,252+ Chargers, Multiple OEMs)
                               │
                               ▼
                 CONTINUOUS INGESTION LAYER
                 ├── Automated RMS / S3 Real-Time Stream [PLANNED]
                 ├── Staging Batch Manual Upload [BUILT]
                 └── Filesystem Drop Inbox [BUILT]
                               │
                               ▼
               IMMUTABLE BRONZE & FORENSIC AUDIT [BUILT]
                 ├── Raw Object Store (SHA-256 Immutable)
                 ├── Header Parser & 456-Position Registry
                 └── Profiling & Transport Quality Engine
                               │
                               ▼
                 CANONICAL RECONSTRUCTION LAYER [BUILT]
                 ├── Dynamic Hardware Topology Resolver
                 ├── Multi-Row De-multiplexer
                 └── Same-Second Deterministic Sequencer
                               │
                               ▼
                   TYPED SILVER DOMAIN LAYER [BUILT]
                 ├── 11 Physical Subcomponent Tables
                 ├── Hardware Sentinel Masking
                 └── Atomic Per-Field Provenance Engine
                               │
                               ▼
                HISTORICAL CONTINUITY RESEARCH STORE [BUILT]
                 ├── Temporal Ordering (event_time ASC, seq ASC)
                 ├── Zero-Imputation Gap & Outage Detector
                 ├── Monotonic Lifecycle Counter Engine
                 ├── Dynamic Physical Topology Tracker
                 └── Research Data Access Layer (RDAL)
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   DISCRETE EVENT RECONSTRUCTION         DISCRETE EVENT RECONSTRUCTION
   (Charging Sessions) [PLANNED]          (Alarms & Fault Spans) [PLANNED]
   ├── Plug-in -> Authorize -> Charge    ├── Start Time, End Time, Duration
   ├── Energy Delivered, Meter Drift     ├── Severity & Cluster Detection
   └── Disconnect & Stop Reason Codes    └── Pre-trip Transients
            └──────────────────┬──────────────────┘
                               │
                               ▼
                 SCIENTIFIC PATTERN DISCOVERY ENGINE [PLANNED]
                 ├── Fleet Cross-Sectional Cohort Analysis
                 ├── Temporal Degradation Trend Identification
                 └── Pre-Failure Signature Candidate Discovery
                               │
                               ▼
                 NORMATIVE BEHAVIORAL BASELINES [PLANNED]
                 ├── Component vs Self Historical Baseline
                 ├── Component vs Peer Modules in Same Cabinet
                 └── Charger vs Firmware / Hardware Peer Cohort
                               │
                               ▼
                 PREDICTIVE FEATURE STORE [PLANNED]
                 ├── Rolling Window Thermal Slopes (1h, 6h, 24h)
                 ├── Electrical Imbalance & Resistance Drifts
                 └── Alarm Clustering Frequencies
                               │
                               ▼
                 MULTIVARIATE ANOMALY DETECTION [PLANNED]
                 ├── Statistical Outlier Scoring (Mahalanobis / PCA)
                 └── Unsupervised Thermal Runaway & Drift Flags
                               │
                               ▼
                 FAILURE GROUND TRUTH LINKAGE [PLANNED]
                 ├── Ingestion of CMMS / Maintenance Work Orders
                 ├── Component Replacement & Breakdown Ground Truth
                 └── Labeled Machine Learning Training Sets
                               │
                               ▼
                 SUPERVISED PREDICTIVE MODELS [PLANNED]
                 ├── Failure Mode Classification (e.g. SMR, Gun, Contactor)
                 ├── Remaining Useful Life (RUL) Survival Curves
                 └── Calibrated Breakdown Risk Probabilities
                               │
                               ▼
                 ROOT CAUSE EXPLAINABILITY ENGINE [PLANNED]
                 ├── SHAP Value Feature Attribution
                 └── Physical Evidence Trace (Temperatures, Currents, Alarms)
                               │
                               ▼
                 MAINTENANCE INTELLIGENCE CONSOLE [PLANNED]
                 ├── Fleet Risk Ranking & Proactive Attention Queue
                 ├── Component-Level Diagnostic Worksheets
                 ├── Technician Guidance & Service Recommendations
                 └── Two-Way Dispatch to Operator CMS / Ticketing
```
