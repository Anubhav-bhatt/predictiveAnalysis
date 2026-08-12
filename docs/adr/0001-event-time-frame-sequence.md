# ADR 0001 — Event time + frame sequence as frame identity

**Status:** Accepted
**Date:** 2026-08-12
**Phase:** 1D — Source frame reconstruction

---

## Context

The charger source reports event timestamps at **second resolution**. Several
genuinely different source frames can share one second:

```
21:20:20   Connector Status = Idle             OCPP State = Available
21:20:20   Connector Status = Charge Finished  OCPP State = Finishing
```

The platform must store both. Any identity of the form `(charger_id, event_time)` —
or a time-series primary key on `event_time` alone — collides on exactly this data.

TimescaleDB hypertables partition on a time column, and the Silver telemetry tables
of Phase 1E will do so, which makes the choice of time identity load-bearing beyond
this phase.

---

## Decision

Frame identity is:

```
(charger_id, event_time, frame_sequence, reconstruction_version)
```

`frame_sequence` is a 0-based ordinal assigned per `(charger_id, event_time)`,
allocated in source-row order.

**No sub-second component is ever fabricated.** The platform does not synthesise
`21:20:20.001` / `21:20:20.002`.

`reconstruction_version` is included so that re-running a changed algorithm is
additive and historical output stays attributable to the code that produced it.

---

## Alternatives considered

### 1. Fabricate sub-second offsets

Assign `.001`, `.002`, … within a second so `event_time` alone is unique.

**Rejected.** It writes precision the charger never reported into the authoritative
time column. Once written, invented precision is indistinguishable from measured
precision: every later consumer — normalization, feature engineering, any model —
would treat those milliseconds as real device timing. The corruption is silent,
permanent and unrecoverable, because the original second is no longer separable from
the synthetic offset.

It would also be *wrong in a specific, misleading way*: a 1 ms spacing implies the
two states occurred 1 ms apart, which the source does not support and which is almost
certainly false.

### 2. Keep only one frame per second

Deduplicate on `(timestamp, connector, SMR)`.

**Rejected.** This is the failure mode Phase 1D exists to prevent. The rows are not
duplicates; one is a state the charger genuinely reported. Deleting it destroys a real
transition, and the loss is undetectable after the fact.

### 3. Use the source row number as the tiebreaker

Identity `(charger_id, event_time, source_row_number)`.

**Rejected.** The row number is a property of *one file*. The same frame arriving in a
second overlapping file has a different row number, so identical telemetry would
produce two distinct identities and be double-counted. `frame_sequence` is a property
of the charger's timestamp, not of a file — which is what allows cross-file replay
detection to work at all.

### 4. Use the frame fingerprint as identity

**Rejected.** Two genuinely different frames at one timestamp have different
fingerprints, so this works for collisions — but a *legitimate* repeat of the same
payload at a later timestamp would be indistinguishable, and a fingerprint carries no
ordering, so `frame_sequence` would still be needed for sequencing.

---

## Consequences

### Positive

- Distinct same-second frames are storable and queryable, with their order preserved.
- `event_time` stays exactly what the charger reported. No consumer can mistake
  invented precision for measured precision.
- Cross-file replay detection works, because identity does not depend on which file
  carried the rows.
- Reprocessing under a new algorithm version is additive, not destructive.
- Phase 1E inherits an identity that already accommodates collisions, so it does not
  need to invent one under time pressure.

### Negative

- Every query and join over frames must carry `frame_sequence`. A two-column
  `(charger, time)` join is not sufficient, and forgetting the sequence silently
  returns one frame of a collision group.
- The eventual Silver hypertable identity is four columns rather than two, which is
  slightly more index and slightly more code.
- `frame_sequence` must be allocated per `(charger, event_time)` at persistence time
  rather than taken from the algorithm's per-file numbering, so two overlapping files
  do not both claim sequence 0. That is extra machinery in the service layer.

### Stated limitation

`frame_sequence` represents **deterministic source-record ordering**. It does *not*
prove:

- that the device's physical events occurred in that order, or
- how much time elapsed between them.

When the source provides only second resolution, source order is the best available
evidence, and the platform reports it as exactly that. Any analysis requiring true
sub-second timing requires a source that provides it.

This limitation is documented in
[same-timestamp-collisions.md](../same-timestamp-collisions.md) and is asserted by
`test_no_fabricated_subsecond_timestamps`.

---

## Compliance

- `telemetry_source_frame` carries `uq_telemetry_source_frame_identity` over the four
  columns.
- `test_no_fabricated_subsecond_timestamps` asserts `microsecond == 0`.
- `test_same_timestamp_distinct_frames_persist_as_two_canonical_rows` asserts both
  frames survive with distinct sequences and the same `event_time`.
