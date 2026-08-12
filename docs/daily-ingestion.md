# Daily Fleet Ingestion

The operational cycle that answers, every day: *did the fleet's telemetry arrive?*

---

## 1. Flow

```
                      DAILY SOURCE
                           │
                           ▼
                  Source discovery              FilesystemTelemetrySource
                           │
                           ▼
                  Fleet ingestion run           ingestion_run
                           │
                 ┌─────────┴──────────┐
                 │                    │
           Expected fleet        Files discovered
           (charger registry)    (telemetry_file)
                 │                    │
                 └─────────┬──────────┘
                           ▼
                       Matching                 by charger_id + business_date
                           │
                           ▼
                  Per-charger-day evaluation    CoverageService
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
       Coverage       Completeness         Gaps
          │                │                 │
          └────────────────┼─────────────────┘
                           ▼
                     Daily status              charger_day_coverage
                           │
             ┌─────────────┼──────────────┐
             │             │              │
          Complete       Partial        Missing
             │             │              │
             └─────────────┼──────────────┘
                           ▼
                  Fleet data operations         /api/v1/data-operations
                           │
                           ▼
                       Frontend                 /data-operations
```

---

## 2. Commands

Both are idempotent and scheduler-friendly. No cron, Kafka or Airflow is embedded —
the commands exit with meaningful codes so any orchestrator can drive them.

```bash
# Full daily cycle: discover, register, profile, validate, reconcile.
python -m pipelines.ingestion run-daily

# Pin the business date explicitly.
python -m pipelines.ingestion run-daily --date 2026-08-10

# Ingest without reconciling.
python -m pipelines.ingestion run-daily --no-reconcile

# Recompute a date's coverage. Ingests nothing. This is the late-file command.
python -m pipelines.ingestion reconcile --date 2026-08-10
```

Also installed as the `cpi-ingest` console script.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | completed cleanly |
| 1 | completed with warnings — some files failed or were quarantined |
| 2 | the run itself failed |
| 3 | invalid invocation |

Exit code 1 is the normal outcome for a fleet where a handful of files were bad. A
scheduler should treat it as "look at the report", not "the pipeline is broken".

---

## 3. What `run-daily` does

1. **Create the run** — an `ingestion_run` row in `STARTED`.
2. **Discover** — enumerate the source. Status becomes `DISCOVERING`.
3. **Register** — stream each file into Bronze, checksum it, create the
   `telemetry_file` row. Identical bytes under the same name resolve to the existing
   row and are counted as *skipped*, not reprocessed.
4. **Profile** (Phase 1A) — header, 449 source positions, event-time parsing,
   duplicate/replay profiling, per-field statistics.
5. **Persist per-date contributions** — one `telemetry_file_day` row per business
   date the file actually contains, including the unique-timestamp offsets.
6. **Schema + quality** (Phase 1B) — resolve the schema version, run the rule
   engine, compute the five-dimension quality score.
7. **Reconcile** — for every business date the telemetry touched, rebuild
   `charger_day_coverage`, detect gaps, and create MISSING records for expected
   chargers that delivered nothing.
8. **Finalise** — set run counters and terminal status.

Step 7 reconciles the dates the telemetry *actually contains*, not the nominal run
date. A cross-midnight file legitimately affects two days, and the filename is never
trusted for this.

---

## 4. Business date resolution

**The business date comes from event timestamps. Nothing else.**

Never from:

- the filename — the known production sample's filename date disagrees with its
  telemetry
- `received_at`, `discovered_at`, or processing time

A filename date *is* extracted, but only as metadata, so the disagreement can be
reported as `EVENT_DATE_FILENAME_MISMATCH` (a warning, never fatal). The event date
is never rewritten to match a filename.

### Multi-date files

One file is not assumed to be one business date. `FileDateSpan` records which case
applies:

| Span | Meaning |
|---|---|
| `SINGLE_DAY` | all telemetry on one local date |
| `CROSS_MIDNIGHT` | two consecutive dates |
| `MULTI_DAY` | more than two, or non-consecutive |

Each actual date gets its own `telemetry_file_day` row and its own coverage record.
`telemetry_file.business_date` holds the *dominant* date (most unique timestamps) for
convenience; coverage never relies on it.

Known limitation: the profiler reports connector/SMR identities per file, not per
date. For a multi-day file the same topology is recorded against each date, which can
over-report a date's topology but never under-report it. Row counts are apportioned by
each date's share of unique timestamps and flagged
`row_count_is_apportioned` — safe because row counts are never a coverage input.

---

## 5. Run status

```
STARTED → DISCOVERING → PROCESSING → RECONCILING → COMPLETED
                                                 ↘ COMPLETED_WITH_WARNINGS
                                                 ↘ FAILED
```

`RECONCILING` is where the expected fleet is compared against what arrived — the step
that produces MISSING charger-days.

### Failure containment

A bad file does not fail the run:

```
5,000 files, 4 corrupt  →  4 FAILED, 4,996 processed, run = COMPLETED_WITH_WARNINGS
```

A run only reports `FAILED` when nothing became usable *and* there were failures.

---

## 6. Run counters

`ingestion_run` carries a point-in-time snapshot for reporting. Live truth always
remains derivable from `telemetry_file`.

| Counter | Meaning |
|---|---|
| `files_discovered` | enumerated from the source |
| `files_registered` | new logical files created |
| `files_ready` | reached `READY_FOR_NORMALIZATION` |
| `files_partial` | structurally valid, operationally incomplete |
| `files_duplicate` | identical content under a different filename |
| `files_quarantined` | structurally unusable, preserved for inspection |
| `files_failed` | processing error |
| `files_skipped` | re-presented identical file; nothing re-derived |

`files_skipped` exists so a run that re-saw 5,000 unchanged files does not claim to
have processed them.

---

## 7. Idempotency

Running `run-daily --date X` twice does not duplicate files, quality issues, gaps or
charger-day rows. The mechanisms:

| Entity | Identity | Strategy |
|---|---|---|
| `telemetry_file` | `(sha256, original_filename)` | unique constraint; re-present resolves |
| `telemetry_file_day` | `(telemetry_file_id, business_date)` | delete-then-insert per file |
| `charger_day_coverage` | `(charger_id, business_date)` | bulk upsert |
| `telemetry_gap` | `(coverage_id, start_event_at, end_event_at)` | full recompute per charger-day |
| `data_quality_issue` | `(anchor, issue_hash)` | delete-then-insert; hash excludes counts |

Excluding counts from the issue hash is deliberate: a re-run that finds the same
problem with a different tally updates one row rather than inserting a second.

---

## 8. Performance

Reconciliation issues a **fixed number of statements regardless of fleet size**:

1. read the expected fleet (one query)
2. read every file-day for the date (one query)
3. bulk upsert coverage (one select + one insert + one update)
4. bulk replace gaps (one delete + one insert)
5. bulk replace daily findings (one delete + one insert)

Per-charger work happens in memory. There is no query-per-charger anywhere in the
path, and no distributed infrastructure is introduced.

Coverage recomputation reads persisted second-offsets rather than re-parsing CSVs, so
a late file arriving days later costs one query — not a 16.5 MB re-read per
charger-day.

---

## 9. Observability

Structured logs carry `ingestion_run_id`, `telemetry_file_id`, `business_date`,
`charger_id`, `processing_stage`, `duration_ms`, `coverage_percentage`, `gap_count`
and `final_status`. Telemetry row contents are never logged; `safe_preview` is the
only sanctioned way to put a source-derived value in a log line, and it truncates.

Internal counters are exposed at
`GET /api/v1/data-operations/metrics?date=…`. No Prometheus client is introduced —
the internal abstraction is what this phase calls for.

---

## Related

- [Fleet coverage](fleet-coverage.md) — raw rows vs unique timestamps, file quality vs day completeness
- [Telemetry gap detection](telemetry-gap-detection.md)
- [Late data reconciliation](late-data-reconciliation.md)
