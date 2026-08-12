# Late Data Reconciliation

What happens when telemetry turns up days after the day it describes.

---

## 1. The requirement

A file may contain telemetry for `2026-08-08` but arrive on `2026-08-10`. When it
does, the charger-day it belongs to must be **updated in place**:

```
before   HYD44  2026-08-08   MISSING   NO_DATA    0%
after    HYD44  2026-08-08   LATE      COMPLETE   100%
```

Same coverage row. Same identity. No duplicate state anywhere.

---

## 2. Lateness is measured from receipt

```
cutoff  = end of business_date (in the charger's source timezone)
          + late_arrival_grace_hours

late    = first_received_at > cutoff
```

Configuration: `CPI_FLEET_LATE_ARRIVAL_GRACE_HOURS` (default 24).

**Lateness uses actual receive/discovery time, never processing time.** A file that
sat in the inbox for a week and was processed today is late; a file received on time
but reprocessed today is *not*. Confusing the two would let a backfill run
retroactively mark a healthy fleet as late.

When `first_received_at` is unknown, the charger-day is **not** called late — absence
of evidence is not evidence of lateness.

`late_by_seconds` records how far past the cutoff the first file arrived.

---

## 3. The command

```bash
python -m pipelines.ingestion reconcile --date 2026-08-08
```

Ingests nothing. Recomputes one date's charger-day coverage from what is already
registered. Safe to run repeatedly, and cheap enough to run for a range of dates
after a backfill.

The normal sequence when a late file appears:

```bash
python -m pipelines.ingestion run-daily              # registers the late file
python -m pipelines.ingestion reconcile --date 2026-08-08   # fixes that day
```

`run-daily` already reconciles every date its telemetry touched, so the explicit
`reconcile` is only needed when files were registered by some other path.

---

## 4. Why it is cheap

Reconciliation never re-reads a CSV.

When a file is first profiled, its **unique event timestamps** are persisted as
seconds-from-local-midnight in `telemetry_file_day.event_second_offsets`. For a
120-second cadence that is ~720 small integers per charger-day.

Recomputing a charger-day therefore means:

1. one query for the expected fleet
2. one query for every file-day on that date
3. rehydrate offsets into timestamps in memory
4. recompute coverage, cadence and gaps
5. bulk upsert

A late file arriving a week later costs a query, not a 16.5 MB re-parse per
charger-day. This is the reason `telemetry_file_day` exists.

---

## 5. Idempotency mechanics

| Entity | How repeated reconciliation converges |
|---|---|
| `charger_day_coverage` | identity `(charger_id, business_date)`; bulk upsert, never insert |
| `telemetry_gap` | deleted for every affected charger-day, then rewritten from scratch |
| `data_quality_issue` (CHARGER_DAY) | deleted per coverage row, then rewritten; `issue_hash` excludes counts |

The findings behaviour is what makes the MISSING→LATE transition clean. Because daily
findings are *replaced* rather than appended:

```
first reconcile    MISSING_CHARGER_DATA (ERROR)
late file arrives
second reconcile   LATE_FILE (WARNING)     ← MISSING_CHARGER_DATA is gone
```

Both findings never coexist. `test_late_arrival_flips_missing_to_late_in_place`
asserts the coverage row keeps its original `id`, that only one row exists, and that
the MISSING finding has disappeared.

---

## 6. Gap correction

A late file that fills a hole must make the gap **disappear**, not leave a stale
record. Because gaps are fully recomputed per charger-day:

```
before   1 gap,  12h,  CRITICAL
after    0 gaps
```

See [telemetry gap detection](telemetry-gap-detection.md#5-persistence-and-determinism).

---

## 7. Arrival status transitions

| From | Trigger | To |
|---|---|---|
| `EXPECTED` | reconciliation with no data | `MISSING` |
| `EXPECTED` | usable file within cutoff | `RECEIVED` |
| `EXPECTED` | usable file past cutoff | `LATE` |
| `MISSING` | late file registered, then reconcile | `LATE` |
| any | file from an unregistered charger | `UNEXPECTED` |

`completeness_status` is recomputed independently on every pass, so a charger-day can
move from `NO_DATA` to `COMPLETE` in the same reconciliation that moves it from
`MISSING` to `LATE`.

---

## 8. Multiple and overlapping late files

A late file may overlap telemetry already held. Its timestamps are **unioned** with
what is known, and timestamps present in more than one file are counted in
`overlapping_timestamp_count`.

Overlap is *quantified, never resolved* in this phase. No observation is deleted and
no conflicting row is dropped — frame-level duplicate/replay resolution is Phase 1D's
job. The relevant counters:

| Field | Meaning |
|---|---|
| `overlapping_timestamp_count` | timestamps seen in more than one file |
| `duplicate_file_count` | contributing files containing exact duplicate rows |
| `duplicate_timestamp_count` | timestamps carrying more than the expected frame size |
| `logical_collision_count` | `(timestamp, connector, SMR)` keys with more than one row |

---

## 9. Concurrency

Two workers reconciling the same date must not produce duplicate logical state.
Protection comes from the database, not in-memory flags:

- `uq_charger_day_coverage_identity` on `(charger_id, business_date)`
- `uq_telemetry_file_day_identity` on `(telemetry_file_id, business_date)`
- `uq_telemetry_file_sha256_name` on `(sha256, original_filename)`
- `uq_telemetry_gap_identity` on `(coverage_id, start_event_at, end_event_at)`
- transactional state transitions — a reconciliation pass commits as one unit

Known limitation: two simultaneous reconciliations of the same date will both do the
work, and one may lose the race on the unique constraint and abort. The state remains
correct — the losing transaction rolls back and the winner's result stands — but
there is no advisory lock preventing the wasted effort. Scheduling reconciliation of a
given date on a single worker avoids it.

---

## 10. Boundary cases

**Cross-midnight late file.** Reconciles both dates it touches. `run-daily` derives
the affected dates from `telemetry_file_day`, so nothing depends on the run's nominal
date.

**Late file for a decommissioned charger.** The charger is no longer *expected*, so it
does not affect missing-data metrics, but the telemetry is still recorded — as
`UNEXPECTED` if the registry no longer lists it as expected on that date.

**Late file that is quarantined.** Contributes nothing. The charger-day stays
`MISSING`, which is honest: unusable telemetry is not telemetry.

---

## Related

- [Daily ingestion](daily-ingestion.md)
- [Fleet coverage](fleet-coverage.md)
- [Telemetry gap detection](telemetry-gap-detection.md)
