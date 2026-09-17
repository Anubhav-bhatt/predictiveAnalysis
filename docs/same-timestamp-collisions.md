# Same-Timestamp Collisions

Two real observations in one second, and why both must survive.

---

## 1. The case

The source reports at second resolution. A charger can change state *within* one
second and report both states:

```
21:20:20   Connector Status = Idle             OCPP State = Available
21:20:20   Connector Status = Charge Finished  OCPP State = Finishing
```

These rows share `(event_time, connector, SMR)`. They are **not duplicates** — they
are a genuine state transition.

This is why the platform never does:

```python
drop_duplicates(subset=["timestamp", "connector", "smr"])  # ❌
```

That single line would silently delete one of the two states, and nothing downstream
would ever know a transition had been lost.

---

## 2. How both are kept

```
event_time = 2026-07-27 21:20:20   frame_sequence = 0   Idle / Available
event_time = 2026-07-27 21:20:20   frame_sequence = 1   Charge Finished / Finishing
```

Both are `SAME_TIMESTAMP_DISTINCT_FRAME`-class (the first is `UNIQUE`), both are
canonical, and both are consumed by Phase 1E. Neither has a `replay_of_frame_id`.

Frame identity is `(charger_id, event_time, frame_sequence,
reconstruction_version)` precisely so these two rows can coexist.

---

## 3. No fabricated sub-second time

The charger did **not** send milliseconds, so the platform does not invent them:

```
21:20:20.001   ❌ fabricated
21:20:20.002   ❌ fabricated

event_time = 21:20:20, frame_sequence = 0   ✅
event_time = 21:20:20, frame_sequence = 1   ✅
```

Fabricating sub-second timestamps would make invented precision indistinguishable
from measured precision at every later stage. See
[the ADR](adr/0001-event-time-frame-sequence.md).

A test asserts `event_time.microsecond == 0` on every persisted frame.

---

## 4. What frame_sequence means

`frame_sequence` is **deterministic source ordering**. It says frame 0's rows appeared
before frame 1's rows in the file.

It does **not** prove the device's physical events happened in that order, nor how far
apart they were. When the source provides only second resolution, source order is the
best available evidence, and it is reported as exactly that — not as timing.

Any later analysis that needs true sub-second timing needs a source that provides it.

---

## 5. Distinguishing a collision from a replay

Both look like "more than 8 rows at one timestamp". The difference is the payload:

| | Payload | Classification | Canonical |
|---|---|---|---|
| Replay | identical | `FULL_FRAME_REPLAY` | ❌ |
| Collision | differs | `SAME_TIMESTAMP_DISTINCT_FRAME` | ✅ |

Comparison is by canonical fingerprint per logical position, with no tolerance — a
single changed signal value (`RSRP -83 → -87`) makes it a distinct frame.

---

## 6. Inspecting collisions

```
GET /api/v1/chargers/{chargerId}/frames/collisions?date=2026-07-27
```

Returns each colliding timestamp with all its frames. Then:

```
GET /api/v1/frames/{frameId}/diff/{otherFrameId}
```

reports which **logical positions** differ:

| Logical position | Seq 0 | Seq 1 | Result |
|---|---|---|---|
| `C1/S1` | `a3f9…` | `b721…` | CHANGED |
| `C2/S1` | `cc41…` | `cc41…` | same |

The diff returns positions and fingerprints, never telemetry values — field names are
computed from whatever the frames contain and are never hard-coded.

On the representative fixture, one timestamp carried **3** distinct canonical frames,
which the collision explorer reports as such.

---

## 7. What Phase 1E must preserve

Phase 1E consumes both frames and must keep them apart. For the known topology each
canonical frame becomes 1 charger + 2 connector + 4 SMR observations, so a collision
timestamp legitimately yields two sets — distinguished by `frame_sequence`, not by an
invented timestamp.

Collapsing them would reintroduce exactly the data loss this phase prevents.

---

## Related

- [Frame reconstruction](frame-reconstruction.md)
- [Replay detection](replay-detection.md)
- [ADR: event time + frame sequence](adr/0001-event-time-frame-sequence.md)
