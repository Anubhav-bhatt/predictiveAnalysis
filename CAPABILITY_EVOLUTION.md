# CHARGER PREDICTIVE INTELLIGENCE PLATFORM — CAPABILITY EVOLUTION

## 1. Executive Summary

This document explains the progressive evolution of the Charger Predictive Intelligence Platform across each engineering checkpoint. It details what was impossible before each milestone, what was built, what became possible immediately after, a concrete telemetry example, and what remained missing.

---

## CHECKPOINT 1 — RAW INGESTION (Phase 1A)

### Before This Checkpoint
- The platform had no mechanism to accept telemetry.
- Telemetry files were manually emailed or dropped into ad-hoc folders.
- There was no audit trail, no duplicate detection, and no protection against corrupt uploads.

### What Was Built
- HTTP multipart batch upload endpoint and filesystem inbox watcher.
- Ingestion state machine tracking files from discovery through registration.
- SHA-256 byte-level content hashing and idempotent duplicate rejection.
- Immutable partitioned raw object storage (`data/raw/YYYY/MM/DD/`).
- Transport-level safety limits (512MB max size, 2000 columns, 5M rows).

### After This Checkpoint
- The platform can accept untrusted telemetry from operators or external scripts.
- Duplicate files uploaded under identical or different names are safely identified and deduplicated.
- Raw evidence is permanently preserved with bit-level fidelity.

### Concrete Example
```
Operator uploads: "EXICOM-BLR-001_20260727.csv" (16.5 MB)
System validates size, calculates SHA-256 (3a1b...c9), stores raw bytes at
"data/raw/2026/07/27/uuid__EXICOM-BLR-001_20260727.csv", and marks state REGISTERED.
Second upload of identical file is recognized as duplicate; bytes are discarded.
```

### Still Missing
- The platform cannot parse column headers, understand data types, or extract timestamps.
- It cannot detect whether the file is valid EV charger telemetry.

---

## CHECKPOINT 2 — SCHEMA INTELLIGENCE (Phase 1B & Phase 2)

### Before This Checkpoint
- Headers were treated as arbitrary strings.
- Vendors with duplicate column names in the same CSV (e.g. two columns named `Last Charge Session Stop Reason`) would corrupt parsers.
- There was no concept of canonical names, physical units, or hardware components.

### What Was Built
- Position-aware, source-ordered CSV header parser.
- YAML-based authoritative data dictionaries (`data/dictionaries/`).
- `DictionaryRegistry` mapping raw names and occurrences to canonical specifications.
- Positional SHA-256 header fingerprinting.

### After This Checkpoint
- The platform recognizes all 456 production header positions.
- Duplicate column names are disambiguated by position and occurrence index.
- Every field is bound to an authoritative canonical name, target entity, and physical unit.

### Concrete Example
```
Position 143: "Last Charge Session Stop Reason" (Occurrence 1)
  -> Canonical: "last_charge_session_stop_reason"
  -> Entity: CONNECTOR 1

Position 209: "Last Charge Session Stop Reason" (Occurrence 2)
  -> Canonical: "last_charge_session_stop_reason_secondary"
  -> Entity: CONNECTOR 2
```

### Still Missing
- Cannot evaluate column data distributions, identify telemetry outages, or reconstruct multi-row frames.

---

## CHECKPOINT 3 — PROFILING & METRICS (Phase 1B & Phase 3)

### Before This Checkpoint
- The internal structure of the file was unknown until complete processing.
- Multi-day files were indistinguishable from single-day files.
- Duplicate rows and cartesian join explosions were invisible.

### What Was Built
- Single-pass Polars/Python file profiler (`pipelines/profiling/profiler.py`).
- Deterministic event-time parsing across explicit date formats (no guessing).
- Empirical sampling cadence calculation (median delta $\Delta t$).
- Duplicate row and logical collision detection.

### After This Checkpoint
- The platform immediately extracts row count, unique timestamps, dominant business date, and sampling regularity.
- Identifies exact duplicate rows and logical collision groups.

### Concrete Example
```
File: "16092026_170601_charger_status_latest.csv"
Profiler discovers:
- 10,000 raw rows across 456 columns
- 700 unique event timestamps
- Median cadence: 1484.0 seconds (fleet-wide mixed snapshot)
- 53 exact byte-identical duplicate rows
- 0 conflicting logical collisions
```

### Still Missing
- Cannot score data quality, quarantine defective files, or isolate individual hardware frames.

---

## CHECKPOINT 4 — DATA QUALITY & FLEET COVERAGE (Phase 1C & Phase 4)

### Before This Checkpoint
- Corrupt, incomplete, or late-arriving files went unnoticed.
- Operators could not tell which chargers failed to deliver data for a given business date.
- Telemetry outages were not quantified.

### What Was Built
- Five-pillar quality rule evaluation suite (Schema, Completeness, Validity, Duplication, Timestamps).
- Composite 0–100 quality scoring with individual rule findings and severity ratings.
- Daily fleet coverage reconciliation engine (`CoverageService`).
- Non-destructive file quarantine mechanism (`data/quarantine/`).

### After This Checkpoint
- The platform scores every file's transport quality.
- Missing chargers, late arrivals, and telemetry gaps are tracked per business date.
- Structurally invalid files are quarantined with audit reasons.

### Concrete Example
```
Charger "D82510560390014" on Business Date 2026-07-27:
- Expected: 720 frames (2-minute cadence across 24h)
- Received: 680 frames
- Coverage Score: 94.4%
- Data Quality Score: 98.2 / 100
- Telemetry Gap Detected: 34-minute outage between 10:06 and 10:40
```

### Still Missing
- The raw rows remain cartesian multiplexed strings; physical telemetry frames are not yet assembled.

---

## CHECKPOINT 5 — CANONICAL FRAME RECONSTRUCTION (Phase 1D & Phase 5)

### Before This Checkpoint
- Wide CSVs with multiple rows per timestamp (due to connectors x SMRs x rectifiers) could not be queried as coherent observations.
- Same-second captures were either dropped as duplicates or scrambled.
- A single missing SMR row would corrupt the entire timestamp group.

### What Was Built
- Dynamic `FrameTopologyResolver` supporting heterogeneous fleet layouts (1x1, 2x6, 3x2, 2x10).
- Strict timestamp grouping by `(charger_id, event_time)`.
- Multi-row de-multiplexing and deterministic sequencing via `(event_time ASC, frame_sequence ASC)`.
- SHA-256 canonical frame payload hashing to detect exact replays.
- Partial frame isolation and diagnostic missing position tracking.

### After This Checkpoint
- Multi-row CSV groups are transformed into unified canonical observation frames.
- Legitimate same-second frames (`seq=0` vs `seq=1`) are preserved.
- Partial frames survive without losing valid observed sensor values.

### Concrete Example
```
A 120kW charger with 2 Connectors and 4 SMRs produces 8 raw rows at timestamp 14:30:00.
Frame Reconstruction combines these 8 rows into exactly 1 canonical frame:
- charger_id: "CH_01"
- event_time: "2026-07-27 14:30:00"
- frame_sequence: 0
- status: COMPLETE
- payload: JSON containing all unified sensor readings across cabinet, guns, and SMRs
```

### Still Missing
- The frame payload is an unstructured key-value dictionary; values are untyped strings; hardware probe sentinels are not masked.

---

## CHECKPOINT 6 — PRODUCTION CONTRACT ALIGNMENT (Phase 5.5)

### Before This Checkpoint
- The dictionary mappings were based on synthetic and early test fixtures (~449 positions).
- Real production telemetry (`16092026_170601_charger_status_latest.csv`) had 456 positions with unknown columns, unmapped alarms, and hardware probe sentinels.

### What Was Built
- Comprehensive forensic analysis of the 2,252-charger live production snapshot.
- Full dictionary expansion covering all 456 positions (0 unmapped).
- Explicit hardware sentinel bindings (e.g., `999.0` gun temp, `-50.0` rectifier temp, `-150.0` SMR temp).
- Strict validation that resistance telemetry is continuous float and alarm flags carry no units.

### After This Checkpoint
- The platform is contractually locked to 100% of the live commercial DC fast charger schema.
- Heterogeneous fleet topologies (1x1, 2x6, 3x2, 2x10) are fully supported.

### Concrete Example
```
Column 31: "Gun Temp Dc+" -> Bound to thermocouple open-circuit sentinel 999.0°C.
Column 89: "Rectifier Internal Temp" -> Bound to uninitialized probe sentinel -50.0°C.
Column 422: "Smoke Alarm" -> Bound to discrete ALARM_FLAG enum (no physical unit).
```

### Still Missing
- Records still exist only as raw frames and dictionaries; typed relational domain tables are not yet populated.

---

## CHECKPOINT 7 — CANONICAL SILVER NORMALIZATION (Phase 6)

### Before This Checkpoint
- Telemetry values were stored as raw text strings inside JSON blobs.
- SQL queries across specific physical components (e.g. "Find max temperature of SMR 3") required slow JSON scans.
- Probe disconnect sentinels (`999.0`) corrupted statistical averages.
- Lineage was lost once data was extracted from raw CSVs.

### What Was Built
- 11 physical relational domain tables (`silver_charger_telemetry`, `silver_connector_telemetry`, `silver_smr_telemetry`, `silver_rectifier_telemetry`, etc.).
- Safe typed coercion for floats, integers, booleans, enums, and ISO datetimes without fabrication.
- Hardware probe sentinel masking: replaces open-circuit sentinels with SQL `NULL` while preserving raw strings in provenance.
- Atomic per-field lineage in `silver_observation_provenance`.
- SHA-256 configuration snapshot hashing (`config_hash`).

### After This Checkpoint
- Telemetry is stored in typed, indexed, relational tables partitioned by component.
- Hardware sentinels no longer corrupt statistical calculations.
- Every single data cell can be traced back to its exact CSV file, row number, and source position (1–456).

### Concrete Example
```
Raw CSV Pos 31: "999"
  -> Frame Reconstruction: stored in payload as "999"
  -> Silver Normalization:
       silver_connector_telemetry.gun_temp_dc_positive = NULL
       silver_observation_provenance:
         field_name: "gun_temp_dc_positive"
         raw_value: "999"
         normalized_value: NULL
         was_sentinel: TRUE
         transformation: "MASKED_HARDWARE_SENTINEL"
```

### Still Missing
- Cross-file longitudinal continuity: observations are stored as individual frames; multi-day timelines are not yet indexed or summarized.

---

## CHECKPOINT 8 — HISTORICAL CONTINUITY & TIME-SERIES RESEARCH (Phase 7 - CURRENT)

### Before This Checkpoint
- Observations across different files, uploads, and days were disconnected.
- Ingestion order or autoincrement database IDs dictated query sequences.
- Outages across days were not detected.
- Single-point snapshots were not distinguished from longitudinal time-series.

### What Was Built
- `HistoricalContinuityService` querying Silver domain tables directly (zero duplicate storage).
- Global temporal ordering: `(event_time ASC, frame_sequence ASC)`.
- Empirical sampling cadence analyzer: median delta, percentiles (P05/P95), same-second frame counting.
- Empirical gap detector: detects outages relative to cadence with **ZERO imputation**.
- Monotonic counter analyzer: classifies intervals as `UNCHANGED`, `INCREASED`, `DECREASED`, `RESET_CANDIDATE`.
- Physical component presence tracker: `first_seen`, `last_seen`, `active_days_count` per subcomponent.
- Snapshot honesty: flags single-point snapshots (`is_snapshot_only = true`) and disqualifies them from premature pattern research.
- `ResearchDataAccessLayer`: sub-5ms programmatic time-series retrieval for Phase 9 research.
- Full interactive frontend timeline UI tab with charts, statistics grid, and gap viewer.

### After This Checkpoint
- Telemetry streams seamlessly across multiple files, days, and uploads.
- Missing intervals are surfaced as empirical absences rather than silently interpolated.
- Downstream research pipelines have sub-5ms programmatic access to clean, ordered, provenance-backed time-series data.

### Concrete Example
```
Query: "GET /api/v1/chargers/CH_HIST_01/history"
Result:
- Returns 1,440 continuous observations in 3.40 ms
- Correctly isolates a 34-minute telemetry outage from 10:06 to 10:40
- Identifies an SMR 3 thermal rise from 41.0°C to 61.0°C
- Flags a counter drop from 118 kWh to 3 kWh as RESET_CANDIDATE
- Tracks SMR 1-4 active across all 7 days, SMR 5-6 active only on Days 6-7
```

### Still Missing
- **Discrete Event Reconstruction (Phase 8)**: Continuous states not grouped into discrete sessions or alarm event spans.
- **Pattern Discovery (Phase 9)**: Cannot yet discover empirical precursor signatures or compute cross-signal correlations.
- **Anomaly Detection (Phase 11)**: Cannot yet compute multi-variate anomaly scores.
- **Failure Prediction (Phase 13)**: Cannot predict Remaining Useful Life without maintenance ground truth.

---

## CHECKPOINT 9 — DISCRETE OPERATIONAL EVENT RECONSTRUCTION (Phase 8)

### Before This Checkpoint
- Telemetry was strictly a sequence of timestamped point observations (`charger/component/signal/time`).
- The platform could not determine when a charging session started, ended, or how much energy was consumed overall.
- Alarms were isolated single-point observations rather than contiguous active duration spans.
- Hardware protection fault states could not be distinguished from ordinary operational states.
- Configuration change diffs across time were invisible.

### What Was Built
- `EventReconstructionService` and pure pipeline engines (`pipelines/events/`):
  - Session reconstructor: state transition tracking (`Preparing` -> `Charging` -> `Finishing` -> `Available`), energy delta, SoC progression, termination classification (`NORMAL`, `USER_STOPPED`, `REMOTE_STOPPED`, `FAULT`, `COMM_FAILURE`).
  - Alarm span aggregator: contiguous interval tracking, debounce windowing, open/closed lifecycle resolution.
  - Hardware fault extractor: isolation of critical protection trips and inverter errors.
  - State transition tracker: physical connector status and plug transitions with microsecond/occurrence resolution.
  - Configuration change detector: parameter-level JSON diffs between configuration snapshots.
- Relational schema with composite indexes and uniqueness constraints for idempotent re-computation.
- `EventTimelineTab` UI with filterable event streams, session summaries, and re-triggerable reconstruction.

### After This Checkpoint
- Continuous telemetry is transformed into structured operational events (`event_type/start/end/duration/context`).
- Every event preserves honest gap awareness (`has_gap=true`) and confidence levels (`HIGH`, `MEDIUM`, `LOW`).
- Downstream research pipelines can analyze complete charging sessions and alarm spans alongside continuous telemetry.

### Concrete Example
```
Reconstruction on "CH_EVT_01":
- Reconstructs a 15-minute charging session on Connector 1: 10:05 -> 10:20, 10.0 kWh delivered, SoC 35% -> 75%.
- Aggregates an intermittent smoke alarm into an 8-minute active span (10:05 -> 10:13) with confidence HIGH.
- Detects an emergency stop transition at 10:13:00 causing premature session termination.
```

### Still Missing
- **Scientific Pattern Discovery (Phase 9)**: Cannot yet compute cross-signal correlations, descriptive statistics, or detect precursor candidates.
- **Unsupervised Anomaly Detection (Phase 11)**: Cannot compute anomaly scores.
- **Predictive Maintenance (Phase 13)**: Cannot predict component failure without ground truth.

---

## CHECKPOINT 10 — SCIENTIFIC PATTERN DISCOVERY & ANALYTICAL DATASET CONSTRUCTION (Phase 9 - CURRENT)

### Before This Checkpoint
- No automated descriptive statistical profiling of continuous Silver signals (distributions, sentinels, missing rates).
- No cross-signal correlation matrix to discover co-movement (e.g. current vs cabinet temperature).
- No domain pattern scanning to detect precursor candidates (thermal drift, voltage anomalies, current imbalance, session degradation, alarm clustering).
- No analytical unit-of-analysis datasets at defined scientific grains (`CHARGER_TIME`, `CONNECTOR_TIME`, `SESSION_LEVEL`, `EVENT_CENTERED`).
- No honest evaluation of dataset readiness before attempting predictive ML.

### What Was Built
- Pure, IO-free analytical pipeline modules (`pipelines/research/`):
  - `SignalStatistician`: descriptive distributions (mean, std, min, max, P05, P25, P50, P75, P95, skewness, kurtosis), honest sentinels counting, missing rate, Pearson $r$, Spearman rank correlation $\rho$.
  - `PatternScanner`: domain pattern scanning with graduated evidence scoring (`OBSERVATION`, `WEAK_CANDIDATE`, `MODERATE_CANDIDATE`, `STRONG_CANDIDATE`, `CONFIRMED_PRECURSOR`), supporting evidence dataclasses, confidence scoring.
  - `ResearchDatasetBuilder`: unit-of-analysis alignment across 6 grains with honest gap awareness (windows crossing outages flagged, zero imputation).
  - `FleetProfiler`: fleet-wide exploratory data analysis (EDA) and data readiness gating.
- Relational schema & Alembic migration (`f60ecb16d021_add_research_tables`):
  - `pattern_candidate`: persisted precursor candidates with JSON supporting evidence and confidence scores.
  - `analytical_dataset_run`: provenance-tracked audit records of constructed datasets.
- Research API (`backend/app/api/v1/research.py`) with 7 high-performance REST endpoints:
  - `GET /api/v1/research/fleet-eda`
  - `GET /api/v1/research/data-readiness`
  - `GET /api/v1/research/chargers/{id}/signal-stats`
  - `GET /api/v1/research/chargers/{id}/correlations`
  - `GET /api/v1/research/chargers/{id}/patterns`
  - `POST /api/v1/research/chargers/{id}/scan-patterns`
  - `POST /api/v1/research/chargers/{id}/build-dataset`
- Frontend Research Lab:
  - `ResearchLabTab.tsx`: Charger-level signal statistics table, pairwise correlation explorer, pattern candidate cards with collapsible supporting evidence, scan triggers, dataset construction triggers.
  - `FleetResearchPage.tsx`: Fleet-wide EDA metrics, ML data readiness evaluation with blockers and actionable recommendations, per-charger discovery breakdown.
  - UI routing via `/research` and tab integration in `ChargerDetail.tsx`.

### After This Checkpoint
- The platform is a fully equipped scientific research environment.
- Researchers can discover empirical precursor patterns with mathematical confidence scores and graduated evidence levels.
- Signals can be compared across time, siblings, and fleet baselines.
- Analytical datasets are assembled deterministically with zero artificial imputation.
- The platform explicitly tells engineers whether telemetry data is ready or not for predictive machine learning models.

### Concrete Example
```
POST /api/v1/research/chargers/CH_01/scan-patterns
Result:
- Analyzed 5 continuous Silver observations and 1 reconstructed session in 2.1 ms
- Discovered 2 pattern candidates:
  1. "Voltage anomaly detected on l1_n_voltage": Undervoltage (185.0V < 200V threshold)
     Confidence: 40% (OBSERVATION)
  2. "Phase current imbalance detected": Input currents show 64.3% maximum deviation (Line 3: 15A vs Line 1/2: 45A/46A)
     Confidence: 80% (MODERATE_CANDIDATE)
- Evaluated data readiness: Overall readiness = "PARTIAL", Blocker = "Insufficient temporal depth (< 7 days)", Recommendation = "Ingest longitudinal multi-day telemetry".
```

### Still Missing
- **Feature Engineering & Transformation (Phase 10)**: Time-series lag features, rolling windows, wavelet transforms.
- **Unsupervised Anomaly Detection (Phase 11)**: Isolation Forests, Mahalanobis distance, reconstruction error autoencoders.
- **Health Index & Degradation Scoring (Phase 12)**: Composite 0-100 component health score.
- **Failure Prediction & Remaining Useful Life (Phase 13)**: Supervised survival analysis and RUL estimators.

