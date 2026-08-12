# Telemetry Gap Detection

Finding the stretches of a charger-day where telemetry simply is not there.

---

## 1. What a gap is

A gap is an interval **between two consecutive observed event timestamps** that is
longer than the configured tolerance.

Two things it is deliberately *not*:

- **Not** `interval > expected_interval`. Real cadence varies. The known sample's
  median is ~121 s against a nominal 120 s; treating every 121-second interval as a
  gap would produce hundreds of meaningless gaps per charger-day.
- **Not** the absence of telemetry before the first or after the last observation.
  That is missing *time*, not a gap *between samples*, and it is reported separately
  as `leading_missing_seconds` / `trailing_missing_seconds`.

---

## 2. Threshold

```
gap_threshold_seconds = expected_sampling_interval_seconds x gap_threshold_multiplier
```

With the defaults (`120 x 3.0`) the threshold is **360 seconds**. An interval must
*exceed* the threshold; exactly 360 s is not a gap.

The multiplier is configuration (`CPI_FLEET_GAP_THRESHOLD_MULTIPLIER`), never a
literal. It must be greater than 1.0 — a validator enforces that, because a
multiplier of 1.0 or below would classify normal cadence as continuous gaps.

### Worked example

```
06:00:00  ─ 2 min ─  06:02:00  ─ 2 min ─  06:04:00  ─ 2 min ─  06:06:00
06:06:00  ─────────── 10 min ───────────  06:16:00
```

Intervals of 120 s, 120 s, 120 s, 600 s against a 360 s threshold:

```
gap_count = 1
largest_gap_seconds = 600
```

The three normal intervals are not gaps. The 10-minute hole is.

---

## 3. Severity

Duration-banded, all thresholds configurable:

| Severity | Default floor | Env var |
|---|---|---|
| `MINOR` | below the moderate floor | — |
| `MODERATE` | 1,800 s (30 min) | `CPI_FLEET_GAP_MODERATE_SECONDS` |
| `MAJOR` | 7,200 s (2 h) | `CPI_FLEET_GAP_MAJOR_SECONDS` |
| `CRITICAL` | 21,600 s (6 h) | `CPI_FLEET_GAP_CRITICAL_SECONDS` |

`CPI_FLEET_GAP_MINOR_SECONDS` (default 300 s) is retained for reporting context.

These are **development defaults, not engineering-justified constants.** They are
stated here rather than buried in code so that a fleet with different operational
expectations can retune them. Classification is `>=` the floor: a gap of exactly
7,200 s is `MAJOR`, not `MODERATE`.

---

## 4. Estimated missing samples

```
estimated_missing_samples = (duration_seconds // expected_interval_seconds) - 1
```

A 1,200-second gap at a 120-second cadence spans 10 cadence slots, 9 of which should
have carried an observation:

```
1200 // 120 - 1 = 9
```

This is an *estimate* derived from expected cadence, not a count of anything
observed — the whole point is that nothing was observed there.

---

## 5. Persistence and determinism

Gaps live in `telemetry_gap`, one row per detected gap, with identity:

```
(coverage_id, start_event_at, end_event_at)
```

A gap is uniquely located by the charger-day it belongs to and the two observations
that bracket it. Nothing about that identity depends on run order or row insertion
sequence, so repeated reconciliation converges.

### Recomputation, not accumulation

Gaps are **fully recomputed** whenever a charger-day is evaluated, and the recompute
deletes the previous set first. This is what makes the late-file case correct:

```
Monday    file covers 00:00-06:00 and 18:00-24:00  →  1 gap (12 hours, CRITICAL)
Wednesday late file arrives covering 06:00-18:00   →  0 gaps
```

The 12-hour gap is **gone**, not left behind as a stale record contradicting the
data. `test_gaps_are_recomputed_not_accumulated` pins this behaviour, including that
the `telemetry_gap` table ends up empty.

At fleet scale the recompute is two statements for the whole pass — one delete across
every affected coverage row, one insert of the recomputed set.

---

## 6. Gap-related fields on the charger-day

| Field | Meaning |
|---|---|
| `gap_count` | number of detected inter-sample gaps |
| `largest_gap_seconds` | longest single gap |
| `total_gap_seconds` | sum of all gap durations |
| `leading_missing_seconds` | day start → first observation |
| `trailing_missing_seconds` | last observation → day end |
| `gap_adjusted_coverage_percentage` | span coverage with gap time removed |

Leading and trailing time are kept distinct from gaps so the two conditions stay
distinguishable. A charger that only reported for the last two hours of the day has
**no gaps** and a large `leading_missing_seconds` — reporting that as a gap would
conflate "stopped reporting mid-day" with "started reporting late".

---

## 7. Reporting floor

A charger-day raises at most **one** `TELEMETRY_GAP` quality finding, carrying the
gap count in `occurrence_count` and the worst gap in its details. One finding per gap
would drown the daily report on a charger with cadence noise.

Only gaps at or above `CPI_DAILY_SEVERITY_GAP_MIN_SEVERITY` (default `MODERATE`)
raise a finding. Every detected gap is still persisted in `telemetry_gap` regardless
of the reporting floor — the floor controls *notification*, not *retention*.

---

## 8. What gap detection does not do

- It does not interpolate or fill anything.
- It does not attribute cause. A gap may be a charger outage, a network failure, a
  collection failure or a source defect; Phase 1C reports the absence and does not
  guess.
- It does not treat a gap as a hardware fault. That inference belongs to a later
  phase.

---

## 9. API

```
GET /api/v1/chargers/{chargerId}/gaps?from=…&to=…&severity=…
GET /api/v1/chargers/{chargerId}/coverage/{date}     # gaps for the timeline view
```

---

## Related

- [Fleet coverage](fleet-coverage.md)
- [Daily ingestion](daily-ingestion.md)
- [Late data reconciliation](late-data-reconciliation.md)
