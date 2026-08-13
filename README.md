# Charger Predictive Intelligence Platform

Operational data platform for EV charger telemetry. **Phase 1** builds the trusted
data foundation; there are no predictive endpoints yet, by design.

| Phase | Scope | State |
|---|---|---|
| 1A | Daily telemetry foundation & data contract | implemented |
| 1B | Charger data dictionary, schema classification & quality engine | implemented |
| 1C | Daily fleet ingestion, coverage, completeness & telemetry gap detection | implemented |
| 1C.5 | Bulk manual telemetry upload & source-independent ingestion | implemented |
| 1D | Source frame reconstruction, duplicate/replay & same-timestamp collisions | implemented |
| 1E | Canonical charger/connector/SMR telemetry normalization | not started |
| 1F | Session reconstruction, alarm normalization & historical query layer | not started |

---

## The distinctions that govern this codebase

Get these wrong and every number the platform reports becomes untrustworthy.

**1. Coverage is computed from unique event timestamps, never raw rows.**

The source grain is `2 connectors x 4 SMRs = 8 raw rows per event timestamp`, and
replayed frames add rows without adding observations. Dividing raw rows by expected
raw rows lets a duplicated file report >100% coverage while being half empty.

**2. File quality and charger-day completeness are different questions.**

A file can be schema-valid and score 98% while containing only 20% of the day.
Neither number is ever written over the other.

Both are documented in [docs/fleet-coverage.md](docs/fleet-coverage.md).

**3. How a file arrived never changes what it means.**

Manual upload, filesystem drop and (later) RMS are acquisition mechanisms behind one
adapter contract. Below acquisition there is a single pipeline, and no stage can
observe the source. An equivalence test asserts that the same bytes produce identical
business date, coverage, quality, duplicate classification and frames through either
source — see [docs/source-adapters.md](docs/source-adapters.md).

**4. Repetition is classified, never deleted.**

`drop_duplicates` on `(timestamp, connector, smr)` would destroy the evidence that
distinguishes a replayed frame from a genuine same-timestamp collision. See
[docs/frame-reconstruction.md](docs/frame-reconstruction.md).

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

With PostgreSQL/TimescaleDB running:

```bash
alembic upgrade head
uvicorn backend.app.main:app --reload      # API on :8000, docs at /docs
```

Frontend:

```bash
cd frontend && npm install && npm run dev  # UI on :5173
```

Or the whole stack:

```bash
docker compose -f infrastructure/docker/docker-compose.yml up --build
# API :8000 · UI :8080 · TimescaleDB :5432
```

---

## Daily operation

```bash
# Full cycle: discover, register, profile, validate, reconcile.
python -m pipelines.ingestion run-daily

# Recompute one date's coverage. This is the late-file command; it is idempotent.
python -m pipelines.ingestion reconcile --date 2026-08-10

# Process telemetry uploaded through the UI or the upload API.
python -m pipelines.ingestion process-uploads

# Reconstruct source frames for one date (Phase 1D).
python -m pipelines.frame_reconstruction reconstruct --date 2026-08-10
```

Exit codes: `0` clean, `1` completed with warnings, `2` run failed, `3` bad
invocation. Exit `1` is normal for a fleet where a few files were bad.

Telemetry can arrive two ways, and they are equivalent downstream:

- **Filesystem** — drop CSVs into `CPI_SOURCE_FILESYSTEM_INBOX` (default
  `./data/inbox`), then `run-daily`.
- **Manual upload** — the UI at `/data-operations/upload`, or
  `POST /api/v1/ingestion/uploads`, then `process-uploads`. A `202` means the bytes
  are staged and queued, not that processing finished.

---

## Layout

```
backend/app/
  api/v1/         FastAPI routes - no business logic
  core/           typed configuration, structured logging
  db/             declarative base, portable column types, sessions
  models/         SQLAlchemy models
  repositories/   the only place that builds SQL
  services/       orchestration
  schemas/        Pydantic read models
pipelines/
  sources/        telemetry source adapters (filesystem, manual upload; RMS later)
  profiling/      header parsing, event-time analysis, file profiling
  validation/     dictionary resolution, schema compatibility, classification
  quality/        file-scope and charger-day-scope rule engines
  ingestion/      coverage engine, per-date splitting, state machine, CLI
  persistence/    Bronze raw-object storage
  frame_reconstruction/  frame identity, duplicate/replay classification, fingerprints
data/
  dictionaries/   curated field dictionary (YAML)
  contracts/      units and missing-value semantics
docs/             architecture and operational documentation
```

Boundaries: routes never touch a session, repositories never contain business
logic, and the pipeline modules are pure enough to test without a database.

---

## Validation

```bash
ruff check .          # lint
mypy .                # strict type check
pytest                # unit + integration (hermetic SQLite)
alembic upgrade head  # migrations
alembic check         # model/migration drift

cd frontend
npm run lint && npm run typecheck && npm run test && npm run build
```

The real production sample is not committed. `tests/fixtures/builders.py`
synthesises a file reproducing its structural characteristics — 449 source
positions, a duplicated header, the 8-rows-per-timestamp grain, replays, exact
duplicates, a ~121 s cadence, a gap, and a filename date that disagrees with the
telemetry. To profile the genuine file:

```bash
CPI_REAL_SAMPLE_PATH=/path/to/charger_daily.csv pytest -m real_sample -s
```

---

## Documentation

- [Daily ingestion](docs/daily-ingestion.md) — the cycle, commands, idempotency
- [Fleet coverage](docs/fleet-coverage.md) — **raw rows vs unique timestamps; file quality vs day completeness**
- [Telemetry gap detection](docs/telemetry-gap-detection.md) — thresholds, severity, recomputation
- [Late data reconciliation](docs/late-data-reconciliation.md) — MISSING → LATE in place
- [Manual upload](docs/manual-upload.md) — bulk upload, staging vs Bronze, security
- [Source adapters](docs/source-adapters.md) — **the contract that keeps acquisition out of analysis**
- [RMS source integration](docs/rms-source-integration.md) — what the next adapter involves
- [Frame reconstruction](docs/frame-reconstruction.md) — frame identity and fingerprints
- [Replay detection](docs/replay-detection.md) — classifying repetition instead of dropping it
- [Same-timestamp collisions](docs/same-timestamp-collisions.md) — genuine collisions vs replays
- [ADR 0001](docs/adr/0001-event-time-frame-sequence.md) — event time + frame sequence as identity

---

## Configuration

Every threshold is configuration; none is a literal in the evaluators. See
`.env.example`. The values most worth knowing:

| Variable | Default | Effect |
|---|---|---|
| `CPI_FLEET_DEFAULT_SOURCE_TIMEZONE` | `Asia/Kolkata` | applied to naive source timestamps; per-charger override supported |
| `CPI_FLEET_DEFAULT_SAMPLING_INTERVAL_SECONDS` | `120` | drives expected observation count |
| `CPI_FLEET_GAP_THRESHOLD_MULTIPLIER` | `3.0` | gap threshold = interval x multiplier |
| `CPI_FLEET_COMPLETENESS_COMPLETE_MIN_PCT` | `95.0` | COMPLETE floor |
| `CPI_FLEET_COMPLETENESS_PARTIAL_MIN_PCT` | `50.0` | PARTIAL floor |
| `CPI_FLEET_LATE_ARRIVAL_GRACE_HOURS` | `24` | cutoff after the business date ends |
| `CPI_UPLOAD_MAX_FILE_SIZE_BYTES` | `268435456` | per-file upload ceiling (256 MiB) |
| `CPI_UPLOAD_MAX_BATCH_SIZE_BYTES` | `5368709120` | whole-request ceiling (5 GiB) |
| `CPI_UPLOAD_MAX_FILES_PER_BATCH` | `200` | files accepted in one upload |
| `CPI_UPLOAD_ALLOWED_EXTENSIONS` | `[".csv"]` | upload extension allowlist |
| `CPI_UPLOAD_STAGING_ROOT` | `./data/uploads` | where uploaded bytes wait before registration; **not** Bronze |

Gap severity bands and per-rule severities are configurable too
(`CPI_FLEET_GAP_*`, `CPI_DAILY_SEVERITY_*`). The defaults are development
defaults, not engineering-justified constants.

The upload limits are deliberately **not** derived from the ~16.5 MB reference sample:
a fleet backfill may present far larger or far more numerous files, and a ceiling
inferred from one sample would become an arbitrary production constraint. The UI reads
them from `GET /api/v1/ingestion/uploads/limits` rather than carrying its own copy.
