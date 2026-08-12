# Fleet Coverage

How the platform decides how much of a charger's day it actually has.

This document defines the two distinctions that everything in Phase 1C depends on.
Both are mandatory reading before changing any coverage code.

---

## 1. Raw rows vs unique event timestamps

**A charger-day's coverage is computed from unique event timestamps. Never from raw
row count.**

The source grain is one row per *entity combination* per observation cycle. For the
known charger:

```
2 connectors x 4 SMRs = 8 raw rows per event timestamp
```

So a normal day with a 120-second cadence looks like:

```
720 unique event timestamps
5,760 raw rows
```

Both numbers describe the same 720 observations.

### Why row count cannot be used

Files contain replays. A timestamp whose frame was retransmitted carries 16 rows;
the known sample contains one timestamp with 64. If coverage were
`raw_rows / expected_raw_rows`, then a file that duplicated everything twice would
report **200% coverage while containing exactly one day of real observations** — and
a file that was half empty but heavily replayed could report 100%.

That failure mode is the reason this phase exists, so the platform refuses to
compute coverage that way:

```
coverage  =  unique_event_timestamps / expected_event_timestamps     ✅
coverage  =  raw_rows / expected_raw_rows                            ❌ never
```

Raw row counts are still recorded (`telemetry_file_day.row_count`) and shown in the
UI, but only as *context* alongside the unique count — never as a coverage input.

---

## 2. File quality vs charger-day completeness

These are two different questions with two different answers, stored in two
different places, and neither ever overwrites the other.

| | File quality | Charger-day completeness |
|---|---|---|
| Question | Is this file trustworthy? | Do we have the day? |
| Scope | One telemetry file | One charger + one business date |
| Stored on | `telemetry_file.quality_score` and its five dimensions | `charger_day_coverage.completeness_status`, `coverage_percentage` |
| Owner | Phase 1B quality engine | Phase 1C reconciliation |

The case that forces the separation:

> A file can be **schema-valid, parseable, duplicate-free and score 98%** while
> containing **only 20% of the day's telemetry.**

A high file-quality score says nothing about coverage, and a low coverage figure is
not a file defect. `charger_day_coverage.quality_score` holds the *mean file quality*
of the day's contributing files as convenience context; it is a separate column and
never written back to any file.

---

## 3. Expected observation count

```
expected_timestamp_count = day_seconds / expected_sampling_interval_seconds
```

With the defaults (`86,400 / 120`) that is **720** observations per charger-day.

`expected_sampling_interval_seconds` resolves with documented precedence:

```
charger override  >  global configured default
```

Two further tiers — charger *model* and *schema version* — are specified in the
contract but have no storage yet. They are deliberately **not faked**: the
precedence chain currently has two live levels, and
`CoverageService._policy_for` says so in a comment rather than pretending
otherwise.

Configuration: `CPI_FLEET_DEFAULT_SAMPLING_INTERVAL_SECONDS`, `CPI_FLEET_DAY_SECONDS`.

---

## 4. The three coverage dimensions

A single percentage cannot answer "do we have the day?", so three are computed.

### sample_coverage_percentage — the headline

```
100 * unique_timestamp_count / expected_timestamp_count     (capped at 100)
```

This is the number surfaced as `coverage_percentage` and the one that drives
`completeness_status`. It is the only dimension that **cannot be inflated by
duplication**.

### span_coverage_percentage

```
100 * (last_event_at - first_event_at) / day_seconds
```

How much of the day lies *between* the first and last observation.

**Span alone is actively misleading**, which is exactly why it is never the
headline. A file containing four rows — two at 00:01 and two at 23:59 — scores
~99.9% span coverage and ~0.5% sample coverage. It has two minutes of telemetry.
Both numbers are reported so the contradiction is visible.

### gap_adjusted_coverage_percentage

```
100 * (span_seconds - total_gap_seconds) / day_seconds
```

Span with detected gap time removed — the reconciliation between the other two.

### Worked example

A charger reporting 00:00–06:00 and 18:00–24:00 at a 120-second cadence:

| Dimension | Value | Reading |
|---|---|---|
| sample | 50.0% | half the expected observations exist |
| span | ~100% | first and last events bracket the whole day |
| gap-adjusted | ~50% | one 12-hour gap removed from the span |
| **completeness** | **PARTIAL** | derived from sample coverage |

---

## 5. Completeness bands

Derived from **sample** coverage, with configurable thresholds:

| Status | Condition |
|---|---|
| `COMPLETE` | `coverage >= completeness_complete_min_pct` (default 95%) |
| `PARTIAL` | `coverage >= completeness_partial_min_pct` (default 50%) |
| `SEVERELY_INCOMPLETE` | below the partial threshold, with data present |
| `NO_DATA` | no usable telemetry at all |
| `UNKNOWN` | not yet evaluated |

Configuration: `CPI_FLEET_COMPLETENESS_COMPLETE_MIN_PCT`,
`CPI_FLEET_COMPLETENESS_PARTIAL_MIN_PCT`.

No percentage literal appears in the evaluator. `CoveragePolicy` resolves every
threshold once, and `classify_completeness` is the only place a band is decided.

> **Note on the "00:00–05:30 = PARTIAL" example** from the contract: 5.5 hours is
> ~23% of a day, which under the *default* thresholds is `SEVERELY_INCOMPLETE`, not
> `PARTIAL`. The distinction that matters is preserved either way — a structurally
> valid short file is an operational-completeness verdict, never `FAILED`. Which
> band it lands in is configuration, and
> `test_short_partial_day_is_incomplete_but_never_failed` pins both readings.

---

## 6. Multiple files, one charger-day

**File completeness is not charger-day completeness.** Coverage is the union of
every usable file's timestamp set for that date:

```
File A  00:00-12:00  ->  360 unique timestamps
File B  12:00-24:00  ->  360 unique timestamps
                         ---
charger-day          ->  720 unique timestamps  =  COMPLETE
```

Neither file is complete on its own; together they are. Timestamps appearing in more
than one file are counted as `overlapping_timestamp_count` — quantified, never
deduplicated away. Only files in a usable state
(`READY_FOR_NORMALIZATION`, `COMPLETED`, `PARTIAL`) contribute; quarantined and
failed files contribute nothing.

---

## 7. Fleet-level aggregation

The denominator is the decision that makes these numbers honest.

```
fleet_coverage_percentage  =  mean(coverage_percentage) over EXPECTED charger-days
```

**Missing chargers are included at 0%.** Excluding them would let a fleet that lost
half its estate report 99% coverage. `UNEXPECTED` charger-days — telemetry from a
charger absent from the registry — are excluded from the denominator instead, since
they are not part of what the fleet was measured against, and reported as their own
count.

| Metric | Definition |
|---|---|
| `fleet_delivery_rate` | received / expected |
| `fleet_complete_day_rate` | COMPLETE / expected |
| `fleet_missing_rate` | MISSING / expected |
| `fleet_partial_rate` | PARTIAL / expected |
| `late_arrival_rate` | LATE / **received** (lateness only applies to telemetry that arrived) |
| `p50_coverage_percentage` | nearest-rank median over expected charger-days |
| `p95_coverage_percentage` | nearest-rank 95th percentile |
| `p95_largest_gap_seconds` | nearest-rank p95 of per-charger largest gap |

Percentiles use **nearest-rank**, not interpolation, so every reported percentile is
a value that was actually observed. They are computed in Python from an ordered list
rather than with a dialect-specific SQL function, so PostgreSQL and SQLite agree.

---

## 8. Timezone policy

A charger's day is **its own local day**, not a UTC day.

- Naive source timestamps get a configured source timezone applied
  (`CPI_FLEET_DEFAULT_SOURCE_TIMEZONE`, default `Asia/Kolkata`), overridable per
  charger via `charger.source_timezone`.
- All stored timestamps are timezone-aware UTC. The `UtcDateTime` column type
  guarantees this on the way out too — SQLite has no timezone storage and would
  otherwise hand back naive values, which raises `TypeError` the moment one is
  compared against an aware value.
- Business-date boundaries are computed in the *source* timezone. A UTC-based split
  would place 00:00–05:29 IST on the previous day for the entire Indian fleet.

No timezone is hard-coded in any parsing rule.

---

## 9. Where each number lives

| Question | Column |
|---|---|
| How many observations? | `charger_day_coverage.unique_timestamp_count` |
| How many expected? | `charger_day_coverage.expected_timestamp_count` |
| How many raw rows? | `telemetry_file_day.row_count` (context only) |
| Headline coverage | `charger_day_coverage.coverage_percentage` |
| Which dimension? | `sample_/span_/gap_adjusted_coverage_percentage` |
| Did it arrive? | `arrival_status` |
| Do we have the day? | `completeness_status` |
| Is the file trustworthy? | `telemetry_file.quality_score` |

---

## Related

- [Daily ingestion](daily-ingestion.md)
- [Telemetry gap detection](telemetry-gap-detection.md)
- [Late data reconciliation](late-data-reconciliation.md)
