# Replay Detection

Recognising repeated telemetry without deleting it.

---

## 1. The classifications

| Classification | Meaning | Canonical? |
|---|---|---|
| `UNIQUE` | First frame at this event timestamp. | ✅ |
| `SAME_TIMESTAMP_DISTINCT_FRAME` | Same timestamp, **different** telemetry. A real observation. | ✅ |
| `FULL_FRAME_REPLAY` | Payload equals an earlier frame's. Adds no observation. | ❌ |
| `PARTIAL_FRAME_REPLAY` | A fragment whose positions all match the canonical frame. | ❌ |
| `EXACT_ROW_DUPLICATE` | Byte-identical rows, counted at row level. | ❌ |
| `AMBIGUOUS` | Shares no position with the canonical frame; boundary unconfirmable. | ✅ (reported) |

"Canonical" means Phase 1E consumes it by default. Non-canonical frames are still
**stored with full provenance** — they are excluded from downstream consumption, not
deleted.

---

## 2. Canonical frame selection

Deterministic, never random: **lowest `frame_sequence`**, which by construction is
the earliest source row order. A frame is only ever compared against frames that
preceded it.

Documented consequence: for cross-file overlap, the **earliest-received file** owns
the canonical frame, because `reconstruct_charger_day` processes files in receipt
order.

---

## 3. How a replay is recognised

1. Compute the frame fingerprint from its positions' row fingerprints.
2. If that fingerprint was already seen at this timestamp → `FULL_FRAME_REPLAY`,
   pointing at the first frame that carried it.
3. Otherwise compare against the earliest canonical frame, position by position:
   - **any position differs** → `SAME_TIMESTAMP_DISTINCT_FRAME`
   - **nothing differs, some positions shared** → `PARTIAL_FRAME_REPLAY`
   - **no positions shared** → `AMBIGUOUS`

---

## 4. Strict equality, no tolerance

Comparison is on schema-aware canonical fingerprints. There is **no floating-point
tolerance** in replay detection.

A tolerance would hide small genuine charger-reported changes: if `output_current`
moves from `12.5` to `12.6`, that is a real reading the charger sent, and treating
the frame as a replay would silently discard it. Tolerance belongs to later analytics,
not to deciding whether an observation exists.

---

## 5. Worked examples

### Full replay — the 16-row timestamp

```
T: 8 rows (C1/S1..C2/S4)  →  frame 0, UNIQUE, COMPLETE
T: 8 identical rows       →  frame 1, FULL_FRAME_REPLAY of 0, COMPLETE
```

Both frames stored. `canonical_frames = 1`.

### The 64-row timestamp

```
T: 8 positions x 8 occurrences = 64 rows
→ 8 frames, sequences 0..7
→ 1 canonical + 7 FULL_FRAME_REPLAY   (if payloads identical)
→ 8 canonical                         (if payloads differ)
```

All 64 rows remain accounted for: `rows_assigned = 64`, `rows_unassigned = 0`.

### Partial replay

```
T: 8 complete rows           →  frame 0, COMPLETE, UNIQUE
T: 4 more rows for C1 only   →  frame 1, PARTIAL, PARTIAL_FRAME_REPLAY of 0
```

The fragment keeps only the four positions that genuinely repeated. Nothing is
invented to round it up to 8.

If those four rows carried *different* values, the fragment becomes
`SAME_TIMESTAMP_DISTINCT_FRAME` instead — still `PARTIAL` structurally, but a real
observation.

---

## 6. Cross-file replay

Overlapping daily files carry the same telemetry twice:

```
File A  16:00–20:00
File B  18:00–23:59
```

Frames in `18:00–20:00` appear in both. Reconstruction looks up existing frames by
`(charger_id, frame_fingerprint, reconstruction_version)` before inserting, so file B
adds a **source mapping** to the existing canonical frame rather than a duplicate
frame:

```
Canonical frame
   ├── File A rows   (is_primary_source = true)
   └── File B rows   (is_primary_source = false, source_occurrence = 1)
```

Duplicating the frame per file would double-count every shared observation. The
lookup covers *all* classifications, not only canonical ones — a replay arriving in a
second file is still the same payload already held.

---

## 7. Auditability

The platform can answer "how many times did this frame arrive, and from where?":

```
GET /api/v1/frames/{frameId}
```

returns `replay_count`, every replay frame, and each contributing file with its
source row range. Provenance for a replay is never discarded — only its consumption
downstream is suppressed.

---

## 8. Exact row duplicates

Counted separately at row level during key building (`exact_duplicate_row_count`).
A row byte-identical to any earlier row anywhere in the file increments the counter;
the row itself is retained and still assigned to its frame. The measured value on the
representative fixture was **30**.

---

## 9. Severity

Configurable defaults (`DEFAULT_FRAME_SEVERITIES`):

| Rule | Default | Why |
|---|---|---|
| `FULL_FRAME_REPLAY` | INFO | Normal source behaviour, not a defect. |
| `SAME_TIMESTAMP_DISTINCT_FRAME` | INFO | Genuine telemetry. |
| `PARTIAL_FRAME_REPLAY` | WARNING | A partial retransmission is worth noticing. |
| `FRAME_MISSING_POSITION` | WARNING | Incomplete frame. |
| `FRAME_UNEXPECTED_POSITION` | WARNING | Topology contradiction. |
| `AMBIGUOUS_FRAME_BOUNDARY` | ERROR | We cannot say what the frame is. |
| `UNASSIGNED_RAW_ROW` | WARNING | Telemetry we cannot place. |

These are development defaults, not engineering assertions.

---

## Related

- [Frame reconstruction](frame-reconstruction.md)
- [Same-timestamp collisions](same-timestamp-collisions.md)
