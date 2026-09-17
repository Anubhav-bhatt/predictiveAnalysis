# Phase 5.5 Existing Forensic Implementation Audit

**Target File**: `16092026_170601_charger_status_latest.csv` (10,000 rows, 456 columns)  
**Evaluation Scope**: Existing Real Data Forensic Analyzer (`analyze_real_data.py`, `update_artifacts.py`), Core Profiling Modules (`pipelines/profiling/`), and Validation Contract System (`pipelines/validation/`, `data/dictionaries/`).  
**Audit Purpose**: Identify what is production-ready, what is research-only, what is broken/missing, and eliminate heuristic guesswork from production data contracts.

---

## 1. Capability Audit Matrix

| Capability | Existing Implementation | Evidence / File | Production Ready? | Problem / Limitation | Required Change |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Raw Positional Header Extraction** | `RawHeaderField` parser reads raw line, strips BOM, handles camelCase/acronym boundaries, computes SHA-256 fingerprint. | `pipelines/profiling/header_parser.py:54-180` | `ALREADY_PRODUCTION_READY` | None. Correctly extracts all 456 columns in physical sequence without data loss. | Retain unchanged in production. |
| **Duplicate Header Occurrence Tracking** | Tracks running count per header name, creating `(source_name, occurrence)` identity tuple. | `pipelines/profiling/header_parser.py:145-175` | `ALREADY_PRODUCTION_READY` | None. Correctly identifies `Last Charge Session Stop Reason` at pos 143 (occ 1) and pos 209 (occ 2). | Retain unchanged in production. |
| **Key Column Role Resolution** | `resolve_roles` maps structural roles (`EVENT_TIME`, `CHARGER_ID`, `OCPP_ID`, `CONNECTOR`, `SMR`). | `pipelines/profiling/column_roles.py:49-94` | `PARTIALLY_IMPLEMENTED` | **Failed on Real Data**: `ColumnRole.EVENT_TIME` did not recognize `Logged At Time` (canonical `logged_at_time`), causing event timestamp analysis to fail with `<unresolved>`. Also lacks `RECTIFIER` role. | Add `logged_at_time` to `ColumnRole.EVENT_TIME.exact` and regex patterns; add `RECTIFIER` role for multi-tier topologies. |
| **Event Time Parsing & Cadence** | `analyse_event_time` attempts candidate `strptime` formats in order, handles timezones, computes interval cadences. | `pipelines/profiling/event_time.py:90-210` | `ALREADY_PRODUCTION_READY` | Once role is resolved, correctly parses `%d-%m-%Y %H:%M:%S`. Cadence is `None` because dataset is a point-in-time snapshot (1 timestamp/charger). | Retain parser logic; ensure pipeline handles `FLEET_SNAPSHOT` without expecting regular temporal cadence. |
| **Exact Duplicate Row Detection** | Polars hash-based grouping across all 456 columns to detect identical byte rows. | `pipelines/profiling/profiler.py:340-365` | `ALREADY_PRODUCTION_READY` | None. Successfully identifies all 52 duplicate pairs (104 rows) produced by CMS SQL join cartesian fans. | Retain unchanged in production. |
| **Logical Collision & Replay Analysis** | Groups rows by logical key to differentiate identical replays from conflicting payloads. | `pipelines/profiling/profiler.py:366-430` | `INCORRECT` | Key grouping in `profiler.py` was hardcoded as `(event_time, connector, smr)`. In a fleet snapshot with 2,252 chargers, chargers sharing timestamps were falsely flagged as collisions because `charger_id` was omitted from the key! | Update logical composite key to include `charger_id` (and `rectifier_number`): `(charger_id, event_time, connector, rectifier, smr)`. |
| **Vectorized Summary Statistics** | Computes min, max, mean, median, stddev across continuous numeric fields using Polars. | `pipelines/profiling/profiler.py:220-280` | `ALREADY_PRODUCTION_READY` | Efficient single-pass vectorization. Handled 10,000 rows in <500ms. | Retain unchanged in production. |
| **Extended Percentile & Distribution Metrics** | Computes P01, P05, P25, P50, P75, P95, P99, plus exact zero counts and negative counts. | `scratch/analyze_real_data.py:100-140` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Exists only in research script (`analyze_real_data.py`), missing from production `FieldProfile` dataclass and `profiler.py`. | Promote quantile and zero/negative counting into production `FieldProfile` and `pipelines/profiling/profiler.py`. |
| **Variability Classification** | Categorizes columns into `ALL_NULL`, `CONSTANT`, `NEAR_CONSTANT`, `LOW_VARIABILITY`, `HIGH_VARIABILITY`, `VARIABLE`. | `pipelines/profiling/profiler.py:180-215` | `ALREADY_PRODUCTION_READY` | Accurately segments static vs dynamic columns (e.g. 73 constant, 86 near-constant, 297 variable). | Retain unchanged in production. |
| **Automated Sentinel Candidate Discovery** | Scans unique values against candidate set (`-150`, `-50`, `999`, `65535`, etc.) and counts frequencies. | `scratch/analyze_real_data.py:70-95` & `pipelines/profiling/profiler.py:280-305` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Research code applies a global static list across all columns. Generic scanning produces false positives (e.g. 0 treated as sentinel, -1 treated as sentinel in coordinates). | Sentinels must be bound to specific fields in the authoritative data contract (`sentinel_values` in `FieldSpec`), not guessed globally. |
| **Production Dictionary Registry Governance** | Resolves source fields through explicit identity -> explicit name -> pattern rules -> Level 4 classifier. | `pipelines/validation/dictionary.py:370-525` | `INCORRECT` | **Severe Mismatch**: Existing dictionary contains only 48 curated fields designed for old 449 synthetic fixture. Only 8 real fields matched! 448 real fields (98.2%) fell through to Level 4 heuristic classifier. | Replace synthetic contracts with authoritative YAML dictionary specs covering all 456 production positions. |
| **Entity Inference** | Classifies fields into entities (`CHARGER`, `CONNECTOR`, `SMR`, `RECTIFIER`, `CONTACTOR`, `ALARM`, etc.). | `pipelines/validation/classifier.py:65-75` & `scratch/classify_all_fields.py` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Substring matching is inherently brittle (e.g. "rectifier" in alarm name, "fan" on charger vs SMR). | Hardcode authoritative `FieldEntity` inside YAML dictionary contracts for all 456 positions. Eliminate heuristic fallback. |
| **Field-Class Inference** | Categorizes fields into `ALARM_FLAG`, `STATE`, `CONTINUOUS_TELEMETRY`, `IDENTIFIER`, `COUNTER`, etc. | `pipelines/validation/classifier.py:130-180` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Blindly assumes "numeric = CONTINUOUS_TELEMETRY" and "low cardinality = STATE", misclassifying numeric error codes and discrete levels. | Hardcode authoritative `FieldClass` in YAML dictionary contracts based on empirical physical verification. |
| **Unit Assignment & Validation** | Enforces unit strings against closed set in `data/contracts/units.yaml`. | `pipelines/validation/dictionary.py:153-180` | `ALREADY_PRODUCTION_READY` | Unit validation against `units.yaml` is solid and fails loudly on unknown symbols. | Retain registry validation; populate explicit units for all real electrical and thermal fields in YAML contracts. |
| **Alarm Inventory & State Extraction** | Identifies alarm columns, counts active trips, extracts non-normal states. | `scratch/analyze_real_data.py:160-185` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Research script assumed `NA` was an active alarm state, exaggerating unequipped contactor alarm rates to 65.34%. | Differentiate between `ACTIVE_TRIP` ("Alarm"), `HEALTHY` ("Not alarm", "0"), and `UNEQUIPPED` ("NA") in production contracts. |
| **Predictive Signal Classification** | Tags fields as `HIGH`, `MEDIUM`, `LOW`, `CONTEXT`, `LEAKAGE_RISK`. | `scratch/analyze_real_data.py:190-215` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Heuristic hypotheses (e.g. all alarms = HIGH). Cannot be authoritative without failure labels and model training. | Keep as research artifact (`REAL_DATA_PREDICTIVE_SIGNAL_CANDIDATES.csv`). In production contract, populate `ml_candidate` strictly where verified. |
| **Proposed Silver Routing** | Maps 456 fields into 7-12 target relational tables. | `scratch/update_artifacts.py:115-140` | `ALREADY_EXISTS_BUT_RESEARCH_ONLY` | Research guidance only. Does not implement physical SQL DDL or typed transformations. | Retain as Phase 6 design input specification; do not pollute Bronze validation contracts with premature routing strings. |

---

## 2. Research Logic vs Production Contract Classification

To prevent converting research heuristics into pseudo-facts, every important semantic inference is categorized under the five standard epistemic confidence levels:

### A. MEASURED (Empirically Extracted from 10,000 Rows)
*These facts are mathematically proven by physical observation of the dataset and carry zero inference risk:*
1. **Row Count & Dimensions**: Exactly 10,000 rows, 456 column positions.
2. **Duplicate Header Identity**: Pos 143 and Pos 209 both carry the literal string `Last Charge Session Stop Reason`.
3. **Stop Reason Divergence**: Pos 143 and Pos 209 contain different values in exactly 70 rows (e.g. Pos 143 has error code while Pos 209 has `- (0)`).
4. **Dataset Granularity & Temporal Depth**: Exactly 2,252 distinct `Charger Id`s, each with strictly 1 observation timestamp ($\sigma = 0.0$).
5. **Exact Duplicate Count**: Exactly 52 pairs (104 rows) are 100% byte-identical across all 456 columns.
6. **Nullity and Variability Profiles**: 6 all-null columns, 73 constant columns, 86 near-constant columns, 297 variable columns.
7. **Empirical Numerical Bounds**:
   - Grid Voltages: Min 0.0V, Max 277.0V, Median 241.0V across L1, L2, L3.
   - Neutral Voltage: Max 174.7V (floating neutral spike).
   - Frequency: Min 0.0Hz, Max 50.0Hz, Median 0.0Hz (idle/offline units).
   - Gun Temperatures: Valid readings 18°C–54°C; sentinel cluster at 999.0°C (235 rows DC+, 207 rows DC-).
   - Rectifier Internal Temperature: Valid readings 22°C–69°C; sentinel cluster at -50.0°C (615 rows).
   - Cellular RF: RSRP -138 to 0 dBm (median -84 dBm); RSRQ -20 to 0 dB (median -10 dB).

### B. DOCUMENTED (Grounded in Standards, Protocols & Hardware Specs)
*These semantics are established by international engineering standards:*
1. **Grid Electrical Standards (CEA / IS 17017)**: 3-phase AC 415V line-to-line, 240V nominal phase-to-neutral, 50 Hz nominal grid frequency in India.
2. **Cellular Telemetry (3GPP TS 36.214)**: `RSRP` measured in dBm (Reference Signal Received Power); `RSRQ` measured in dB (Reference Signal Received Quality).
3. **OCPP 1.6-J Protocol**: `OCPP Id` as Central System Charge Box identifier; standard stop reason codes (`EmergencyStop`, `EVDisconnected`, `PowerLoss`, `Local`).
4. **Thermocouple Failure Modes**: Digital temperature transmitters output `999.0` or `1024` on open circuit / disconnected probe.

### C. INFERRED_HIGH_CONFIDENCE (High Inductive Support from Data & Physics)
*Semantics that are not explicitly documented in an OEM manual but are overwhelmingly verified by physical laws and co-occurrence:*
1. **Positional Stop Reason Mapping**: Pos 143 represents Connector 1 / Gun A, Pos 209 represents Connector 2 / Gun B. (Verified because Pos 143 aligns with Connector 1 telemetry block, Pos 209 aligns with Connector 2 telemetry block).
2. **Thermal Sentinels**: `999.0` in `Gun Temp Dc+`/`Dc-` is an open-circuit sensor fault; `-50.0` in `Rectifier Internal Temp` is an uninitialized/offline DSP register.
3. **SMR Subsystem Mapping**: Columns named `IN_PFC-1..12` and `Out_PFC-1..12` represent individual Power Factor Correction stages for modular switched-mode rectifiers.
4. **Contactor Welded Alarms**: `AC1..AC6 Contactor Welded Alarm` represent physical feedback auxiliary contact switches on AC line input contactors.
5. **Floating Neutral Anomaly**: Neutral voltages exceeding 20V (up to 174.7V) represent physical neutral ground displacement rather than sensor scale errors, as line-to-neutral voltages concurrently exhibit phase unbalance.

### D. INFERRED_LOW_CONFIDENCE (Heuristic Hypotheses Requiring Domain Confirmation)
*Heuristic guesses that must NEVER be silently promoted into the production contract without OEM validation:*
1. **Unequipped Relay States**: In `AC4..AC6 Contactor Welded Alarm` and `Merger Contactor C0..C3`, 6,534 rows contain `NA`. It is hypothesized that `NA` means "contactor hardware unequipped on 60kW/120kW chassis", but OEM firmware could also use `NA` for unread CAN communication frames.
2. **Internal Module Register Semantics**: Fields like `Out_PFC-7`, `MDL Fault`, `FR1 SMR Fail Count`, and `MDL Id Repetition` have clear general meanings (PFC output, module fault, frame 1 SMR count), but exact failure threshold bits remain undocumented.
3. **Predictive Signal Importance (HIGH/MEDIUM/LOW)**: The research tagging in `REAL_DATA_PREDICTIVE_SIGNAL_CANDIDATES.csv` is based on general EV charging intuition, NOT empirical feature importance from trained ML models.
4. **Leakage Risk Attribution**: Tagging `Last Charge Session Stop Reason` as `LEAKAGE_RISK` assumes an end-of-session failure prediction task; for an in-session anomaly detection task, it may serve as an input state.

### E. UNKNOWN (Zero Documented or Empirical Meaning)
1. **Unpopulated Reserved Expansion Registers**: 6 all-null columns in the real dataset carry opaque register labels with zero data variance.
2. **Legacy Synthetic Config Parameters**: The 279 columns in the old synthetic fixture (`Config Parameter 1..217`, `Reserved Spare 1..62`) have zero physical existence in the real fleet data and are marked for immediate deprecation.

---

## 3. Action Plan for Phase 5.5 Production Alignment

1. **Retain Unchanged**:
   - `pipelines/profiling/header_parser.py` (positional extraction, occurrence tracking, fingerprinting).
   - `pipelines/profiling/event_time.py` (safe date parsing, timezone handling).
   - `pipelines/validation/dictionary.py:UnitRegistry` and `MissingValueRegistry`.

2. **Correct**:
   - `pipelines/profiling/column_roles.py`: Add `logged_at_time` to `ColumnRole.EVENT_TIME`.
   - `pipelines/profiling/profiler.py`: Include `charger_id` in logical duplicate key grouping to avoid false fleet collisions.

3. **Promote from Research to Production**:
   - Extend `FieldProfile` and `pipelines/profiling/profiler.py` to calculate P01, P05, P25, P50, P75, P95, P99 percentiles, zero counts, and negative counts.
   - Promote field-specific sentinel masking rules (`999.0` for gun temps, `-50.0` for rectifier temp) into explicit dictionary contracts.

4. **Retain as Research-Only**:
   - `scratch/analyze_real_data.py` heuristic substring classifiers.
   - `REAL_DATA_PREDICTIVE_SIGNAL_CANDIDATES.csv` heuristic predictive ratings.
   - Preliminary Silver routing proposals.

5. **Newly Implement**:
   - Production YAML dictionary specifications in `data/dictionaries/` governing all 456 real production positions, fully eliminating Level 4 runtime heuristic fall-through.
   - Comprehensive integration test verifying 100% dictionary mapping across all 456 positions with zero `UNKNOWN` or unmapped fields.
