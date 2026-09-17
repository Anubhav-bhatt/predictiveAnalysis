# Real Data Schema Difference Report
**Comparison**: Real Telemetry (`16092026_170601_charger_status_latest.csv`) vs Old Synthetic Scaffolding (`tests/fixtures/builders.py`)

---

## 1. Summary of Structural Divergence

The historical pipeline development relied on an initial synthetic fixture containing **449 columns**. The actual production RMS export contains **456 columns**. Beyond the difference of +7 positions, the semantic and qualitative composition of the schema is completely different.

### Key Metrics
| Category | Old Fixture (`builders.py`) | Real Dataset (`16092026...csv`) | Variance / Impact |
| :--- | :--- | :--- | :--- |
| **Total Positions** | 449 | 456 | +7 positions |
| **Synthetic Placeholders** | 279 columns (`Config Parameter 1..217`, `Reserved Spare 1..62`) | 0 columns | Synthetic placeholders completely absent in real data |
| **Hardware Module Fields** | Minimal generic columns | 103 SMR & PFC module fields | Real hardware telemetry is deeply granular |
| **Contactor Relays** | Generic contactor 1-3 | 53 specific contactor fields (AC1-AC6, Merger C0-C4) | High modularity across multi-cabinet topologies |
| **Cellular Telemetry** | None | Real RF telemetry (`RSRP`, `RSRQ`) | Live network health monitoring available |
| **Duplicate Column Names** | Assumed unique | 1 duplicate header at pos 143 & pos 209 | Mandatory occurrence/position-based addressing |

---

## 2. Real Telemetry Fields Absent from Old Fixture (Sample of Key Additions)

The real data includes genuine hardware telemetry fields that were never modeled in the synthetic fixture:

1. **Power Factor & Grid Dynamics**:
   - `Power Factor` (pos 12)
   - `L1-L2 Voltage`, `L2-L3 Voltage`, `L3-L1 Voltage` (pos 13, 14, 15)
   - `Neutral Voltage` (pos 7)
   - `Reactive Power` (pos 24)
2. **Cellular Connectivity**:
   - `RSRP` (Reference Signal Received Power, pos 45)
   - `RSRQ` (Reference Signal Received Quality, pos 46)
   - `SIM not inserted Alarm` (pos 100)
3. **Modular SMR & PFC Hardware**:
   - `IN_PFC-1` through `IN_PFC-12` (pos 321 - 332)
   - `Out_PFC-1` through `Out_PFC-12` (pos 333 - 344)
   - `SMR Line1-3 Voltage` (pos 303 - 305)
   - `SMR OutputVoltage` (pos 306)
   - `SMRPFCTemperature` (pos 308)
   - `SMR Output Derating Temp`, `SMR Output Derating AC` (pos 311, 312)
   - `SMR Module Comm Fail`, `SMR Fuse Burn Out`, `SMR Input Unbalance` (pos 314, 315, 316)
4. **Heavy Contactor Architecture**:
   - `AC1 Contactor Welded Alarm` through `AC6 Contactor Welded Alarm` (pos 413 - 418)
   - `Merger Contactor (C0) Welded Alarm` through `(C3) Welded Alarm` (pos 431 - 434)
   - `External Contactor Fail Alarm(Ring)` (pos 435)

---

## 3. Synthetic Columns in Old Fixture That Do Not Exist in Real Data

The old synthetic builder generated arbitrary placeholder columns that must be purged from the canonical dictionary registry:
- `Config Parameter 1` through `Config Parameter 217`
- `Reserved Spare 1` through `Reserved Spare 62`
- Generic alarms like `Alarm Surge Protection 1..4`, `Alarm Overload Protection 1..4`

---

## 4. Required Data Contract & Dictionary Updates

1. **Purge Synthetic Contracts**: Remove placeholder definitions from `data/dictionaries/` and `data/contracts/`.
2. **Positional Key Resolution**: Update `DictionaryRegistry` to resolve definitions based on `(source_name, occurrence)` or `position` rather than relying solely on raw column name string matching.
3. **Add Hardware Schemas**: Incorporate SMR, PFC, Contactor, and Cellular field definitions into the dictionary catalog.
