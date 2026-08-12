# Charger Predictive Intelligence Platform

Operational data platform for EV charger telemetry. **Phase 1** builds the trusted
data foundation; there are no predictive endpoints yet, by design.

| Phase | Scope | State |
|---|---|---|
| 1A | Daily telemetry foundation & data contract | implemented |
| 1B | Charger data dictionary, schema classification & quality engine | implemented |
| 1C | Daily fleet ingestion, coverage, completeness & telemetry gap detection | implemented |
| 1D | Source frame reconstruction, duplicate/replay resolution | not started |
| 1E | Canonical charger/connector/SMR telemetry normalization | not started |

---

## The two distinctions that govern this codebase

Get these wrong and every number the platform reports becomes untrustworthy.

**1. Coverage is computed from unique event timestamps, never raw rows.**

The source grain is `2 connectors x 4 SMRs = 8 raw rows per event timestamp`, and
replayed frames add rows without adding observations. Dividing raw rows by expected
raw rows lets a duplicated file report >100% coverage while being half empty.

**2. File quality and charger-day completeness are different questions.**

A file can be schema-valid and score 98% while containing only 20% of the day.
Neither number is ever written over the other.

Both are documented in [docs/fleet-coverage.md](docs/fleet-coverage.md).

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
```

Exit codes: `0` clean, `1` completed with warnings, `2` run failed, `3` bad
invocation. Exit `1` is normal for a fleet where a few files were bad.

Drop telemetry CSVs into `CPI_SOURCE_FILESYSTEM_INBOX` (default `./data/inbox`).

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
  sources/        telemetry source adapters (filesystem implemented)
  profiling/      header parsing, event-time analysis, file profiling
  validation/     dictionary resolution, schema compatibility, classification
  quality/        file-scope and charger-day-scope rule engines
  ingestion/      coverage engine, per-date splitting, state machine, CLI
  persistence/    Bronze raw-object storage
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

Gap severity bands and per-rule severities are configurable too
(`CPI_FLEET_GAP_*`, `CPI_DAILY_SEVERITY_*`). The defaults are development
defaults, not engineering-justified constants.
