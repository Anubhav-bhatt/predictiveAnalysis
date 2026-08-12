# Source Frame Reconstruction

Turning raw source rows into trusted logical frames.

---

## 1. Why this phase exists

The source repeats each event timestamp once per entity position. For the known
charger:

```
2 connectors x 4 SMRs = 8 raw rows per event timestamp
```

But the real sample also contains timestamps with **16** and **64** rows, 60 exact
duplicate rows, and — critically — repeated rows sharing
`(timestamp, connector, SMR)` that carry **different** telemetry.

So this is unsafe and is never done:

```python
drop_duplicates(subset=["timestamp", "connector", "smr"])   # ❌ deletes real data
```

Those rows are not duplicates. They are separate observations the charger reported
within the same second, and dropping one destroys a genuine state transition.

**Phase 1D classifies repetition. It never deletes it.**

---

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Raw row** | One row exactly as the source file represents it. |
| **Logical position** | A row's entity slot in a frame — `(connector_id, smr_id)`, rendered `C1/S3`. |
| **Source frame** | One coherent charger snapshot at one event timestamp: the set of logical positions reported together. |
| **Frame sequence** | Which frame this is among several sharing the *same* event timestamp. |
| **Canonical frame** | A frame that carries an observation Phase 1E should consume. |
| **Replay** | A repeated frame whose payload matches one already seen. Adds no observation. |
| **Collision** | Several *non-equivalent* frames at one event timestamp. |

Identifiers are **strings**, not integers. The source contract does not guarantee
numeric connector or SMR ids, and a charger reporting `GUN-A` must not crash
reconstruction.

---

## 3. Pipeline

```
Raw rows
   ↓  logical_keys.py      identity + occurrence index, in source order
   ↓  topology.py          expected frame shape, by documented precedence
   ↓  timestamp_groups.py  group by (charger, event_time), describe occupancy
   ↓  frame_builder.py     slice into frame candidates
   ↓  canonical_serializer schema-aware canonical text
   ↓  fingerprint           row + frame SHA-256
   ↓  replay_detector.py   replay / collision / ambiguous classification
Canonical source frames
```

Everything above is pure: no IO, no database. `FrameReconstructionService` supplies
the data and persists the result, which is why every rule is testable without a
session.

---

## 4. Expected topology

**2×4 is never hard-coded.** `FrameTopologyResolver` applies this precedence:

| Tier | Source | Basis recorded |
|---|---|---|
| 1 | Charger registry `expected_connector_count` / `expected_smr_count` | `CHARGER_CONFIGURATION` |
| 2 | Configured global default (`CPI_INGEST_EXPECTED_*`) | `CONFIGURED_DEFAULT` |
| 3 | Observed identities, stability-guarded | `OBSERVED_STABLE` |
| — | Nothing usable | `UNRESOLVED` |

The basis is stored on every frame, so a completeness verdict can always be
explained.

### The stability guard

Tier 3 counts the number of **timestamp groups** a position appeared in, not the
number of rows. A single anomalous 64-row timestamp contributes 1 to that count no
matter how many rows it holds, so it cannot redefine what a frame is. A position
must appear in at least half the groups (configurable) to be considered part of the
topology.

### Declared counts are authoritative

When a charger declares 4 SMRs and the file contains SMRs `1,2,3,4,9`, the expected
set stays `1..4` and **SMR 9 is reported as an unexpected position**. Letting the
observation expand the topology would absorb the anomaly and make it invisible —
the frame would read as merely "partial" instead of malformed.

---

## 5. Occurrence indexing

Within each `(charger, event_time, position)`, rows are numbered `0, 1, 2…` in
**source order**. `source_row_number` is captured from the file's original ordering
before any sort, so nothing depends on a DataFrame index that changes meaning after
a re-sort. Ordering never depends on telemetry values.

---

## 6. Frame candidates

Frame *k* takes occurrence *k* of every logical position. For the clean case — every
position present exactly N times — that yields N complete frames, which is what a
whole-frame retransmission looks like.

Two guards keep this honest:

**Occurrence count alone is not proof of a boundary.** Even occupancy is treated as
coherent; uneven occupancy is not forced into whole frames.

**Missing observations are never manufactured.** Given:

```
C1/S1..S4 → 2 occurrences each
C2/S1..S4 → 1 occurrence each
```

the result is **one COMPLETE frame plus one PARTIAL frame** holding only the four
positions that genuinely occurred twice — not two complete frames with four invented
rows.

A configurable ceiling (`max_frames_per_timestamp`, default 64) stops a corrupt file
generating unbounded frames; groups beyond it are marked `AMBIGUOUS`.

---

## 7. Frame status

Structural verdict only:

| Status | Meaning |
|---|---|
| `COMPLETE` | Every expected position present. |
| `PARTIAL` | Some positions absent. |
| `SEVERELY_INCOMPLETE` | Below the configured share (default 50%). |
| `MALFORMED` | Contains a position the topology does not expect. |
| `AMBIGUOUS` | Frame boundaries cannot be determined. |

Duplication is a **separate dimension**. A frame can be both `COMPLETE` and a
`FULL_FRAME_REPLAY` — that is the normal shape of a retransmitted frame.

---

## 8. Canonical serialization and fingerprints

Fingerprints are only as trustworthy as the text they hash, so:

- **Never hash a Python `repr`.** Every value goes through an explicit rule.
- **Nulls are one token.** Empty, whitespace-only and configured null literals all
  canonicalise to a single sentinel — which is *not* `0`. A missing sensor and a
  zero reading are different observations.
- **Numeric equality follows the declared type.** Whether `1` and `1.0` are the same
  value is a schema question. For a numeric field they canonicalise identically; for
  a STRING field they do not, because there the characters *are* the value. `Decimal`
  is used rather than `float`, so exact source text stays exact.

Excluded from every fingerprint: database ids, `received_at`, `processed_at`,
storage references, file ids and quality-issue ids. Identical telemetry arriving in a
second overlapping file **must** fingerprint identically, and it cannot if the file's
identity is baked in.

A frame fingerprint is built from its positions' row fingerprints, keyed by position
and sorted — so a frame's identity does not depend on the order its rows happened to
appear in the file.

---

## 9. Frame identity

```
(charger_id, event_time, frame_sequence, reconstruction_version)
```

`(charger_id, event_time)` alone is **insufficient**: distinct same-second frames
demonstrably exist and would collide on exactly the data this phase preserves.

`reconstruction_version` is part of the identity so re-running a newer algorithm is
additive and historical output stays attributable to the code that produced it.

### Sequence allocation across files

The algorithm assigns `frame_sequence` per file, so two overlapping files would both
start at 0. Persistence therefore allocates the next free sequence per
`(charger, event_time)`, preserving the file's relative order within a timestamp. For
the common single-file case this is a no-op.

---

## 10. Unassigned rows

A row whose connector or SMR cannot be resolved is **not dropped**. It is marked
`unassigned=True`, persisted in `telemetry_frame_row`, counted in
`rows_unassigned`, and reported as `UNASSIGNED_RAW_ROW`. It is excluded from frame
payloads while remaining queryable.

Rows with no parsable event time cannot join any frame; they are retained the same
way.

---

## 11. Business date

Computed from the frame's own event time **in the charger's source timezone**, using
the same precedence as Phase 1C (charger override, then configured default).

Taking `.date()` off the UTC instant would place every IST timestamp before 05:30 on
the previous day, disagreeing with the Phase 1C business date for the very same
telemetry. Because the date is derived per frame, a cross-midnight file attributes
each frame to the day it belongs to.

---

## 12. Persistence

| Table | Holds |
|---|---|
| `telemetry_source_frame` | One frame: identity, structure, fingerprint, classification. |
| `telemetry_frame_source` | Which files contributed rows. A frame may have several. |
| `telemetry_frame_row` | Frame → raw row: position, occurrence, fingerprint. |

`telemetry_frame_row` deliberately stores **no telemetry values**. Bronze remains
their only copy; duplicating 449 columns here would make the table a second copy of
the source.

Diagnostics go through the **existing** Phase 1 quality framework as `FRAME`-scope
`data_quality_issue` rows — one issue system, not two. They are aggregated per rule
code, so a file with 700 replays produces one INFO finding carrying the count, not
700 rows.

---

## 13. Idempotency

Reconstruction is scoped to `(telemetry_file, reconstruction_version)` and replaces
that scope wholesale. Re-running the same immutable file changes nothing:

```
run 1:  frames=733  sources=733  rows=5822  findings=4
run 2:  frames=733  sources=733  rows=5822  findings=4
run 3:  frames=733  sources=733  rows=5822  findings=4
```

A frame shared with another file loses only *this* file's source and row mappings, so
reconstructing one file never destroys another file's provenance.

---

## 14. Failure isolation

One malformed timestamp group is recorded in `failed_groups` and skipped; the other
~780 groups in a charger-day still reconstruct. One bad file does not stop a
charger-day.

---

## 15. Lifecycle

```
QUALITY_VALIDATION → READY_FOR_NORMALIZATION → FRAME_RECONSTRUCTION
                                             → FRAMES_RECONSTRUCTED → COMPLETED
```

`READY_FOR_NORMALIZATION` no longer implies the raw rows are directly consumable:
Phase 1E consumes reconstructed frames. `COMPLETED` stays reachable directly from
`READY_FOR_NORMALIZATION` so files registered before Phase 1D existed are not
stranded mid-lifecycle.

---

## 16. Commands

```bash
python -m pipelines.frame_reconstruction reconstruct <telemetry-file-id>
python -m pipelines.frame_reconstruction reconstruct --filename HYD12_28-07-2026.csv
python -m pipelines.frame_reconstruction reconstruct-day --charger <charger-id> --date 2026-07-27
python -m pipelines.frame_reconstruction reconstruct-day --ocpp HYD12 --date 2026-07-27
```

`--charger` takes the charger id **as it appears in telemetry**; `--ocpp` is resolved
through the registry. Assuming OCPP id equals charger id would silently reconstruct
the wrong charger.

---

## 17. What Phase 1E consumes

By default, frames classified `UNIQUE` or `SAME_TIMESTAMP_DISTINCT_FRAME` — i.e.
`is_canonical`. Replays are excluded because they add no observation; their
provenance is retained for audit.

```
GET /api/v1/chargers/{id}/frames?canonical_only=true
```

---

## Related

- [Replay detection](replay-detection.md)
- [Same-timestamp collisions](same-timestamp-collisions.md)
- [ADR: event time + frame sequence](adr/0001-event-time-frame-sequence.md)
- [Fleet coverage](fleet-coverage.md) — Phase 1C, unchanged by this phase
