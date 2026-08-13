# Bulk Manual Telemetry Upload

Manual upload is how telemetry reaches the platform during the POC, while the RMS
integration does not yet exist. It is **an acquisition mechanism, not a mode of
operation**: an uploaded file and a file dropped on the ingest filesystem are the
same telemetry to everything downstream of acquisition.

That sentence is the whole design, and it has a testable consequence:

> The same bytes, uploaded manually or discovered on the filesystem, must produce
> identical business date, coverage, quality dimensions, duplicate/replay
> classification and reconstructed frames — differing only in which source
> delivered them.

`tests/integration/test_manual_upload.py::test_filesystem_and_manual_upload_produce_identical_analytical_results`
asserts exactly that. If a future change makes upload behave differently, that test
fails, which is the point of it existing.

## Where upload sits

```
Operator's browser
        │  multipart POST
        ▼
POST /api/v1/ingestion/uploads ──► staging directory + upload_batch rows ──► 202
                                                                             │
                                       (returns immediately; nothing processed yet)
        ┌────────────────────────────────────────────────────────────────────┘
        ▼
ingest process-uploads (worker)
        │
        ▼
ManualUploadTelemetrySource  ─┐
FilesystemTelemetrySource    ─┼──► IngestionService.run ──► profiling ──► schema
(RMS adapter, later)         ─┘         │                    quality
                                        │                    Bronze landing
                                        ▼                    coverage (1C)
                                  identical from here        frames (1D)
```

Everything below `IngestionService.run` receives a `TelemetrySource` and cannot
observe how the file arrived. There is no `if source_type == "MANUAL"` branch in the
processing path, and adding one would be a design regression rather than a feature.

## Request path vs worker path

The split is deliberate and is the reason a 100-file backfill does not time out.

| | Request (`POST /ingestion/uploads`) | Worker (`ingest process-uploads`) |
|---|---|---|
| Does | streams bytes to staging, writes one `upload_batch_file` per file, validates filename/extension/size/emptiness | profiling, schema validation, quality, Bronze landing, coverage, frame reconstruction |
| Duration | bounded by transfer | minutes for a large batch |
| Returns | `202` with a batch id and per-file staging outcome | exit code 0/1/2/3 |
| Batch status after | `REGISTERED` | `COMPLETED`, `COMPLETED_WITH_WARNINGS`, or `FAILED` |

A `202` means *"your bytes are safe and queued"*. It does **not** mean the telemetry
is usable. The UI keeps these as two separate progress bars for that reason: an
operator who reads "100%" on a transfer and assumes their data is queryable will
draw wrong conclusions from an incomplete fleet view.

The 202 is also a promise of durability: the batch is **committed** before the
response is written. Upload is the only writing endpoint in the API, and it uses a
dedicated committing session (`get_write_session`) rather than the read-only one
every other route uses. Getting this wrong is not a subtle bug — the response hands
back a batch id, the staged bytes sit on disk, and the batch itself never existed, so
the worker can never find it and the operator gets a 404 on the id they were just
given.

## Staging is not Bronze

| | Staging (`CPI_UPLOAD_STAGING_ROOT`) | Bronze (`CPI_STORAGE_BRONZE_ROOT`) |
|---|---|---|
| Holds | bytes that arrived but were not yet accepted | files the platform accepted |
| Identity | none — no checksum identity in the platform | content checksum, `telemetry_file` row |
| Lifetime | deleted once processed or proven duplicate; **kept** on failure/quarantine so an operator can inspect what they actually sent | immutable |
| Names | generated (`safe_staged_name`), never the user's filename | generated |

A duplicate never becomes a Bronze file, which is why staging has to be a distinct
place: the platform must be able to hold bytes it has not yet decided to keep.

## Duplicates across sources

Duplicate detection is by content checksum and is **source-blind**. Uploading a file
that was already collected from the filesystem yields `DUPLICATE`, not a second copy
— and vice versa. Two operators uploading the same file in overlapping batches also
converge: the second is recognised.

This is presented in the UI as *"Already uploaded"* rather than as an error, because
nothing went wrong. The telemetry is present; it simply arrived twice. Phase 1D's
distinction still holds underneath: repetition is classified, never deleted.

The CLI reports two flavours of "already present", because they are caught at
different points:

| Counter | Caught | Means |
|---|---|---|
| `Files already present` | before registration | the platform already had a registration for this content |
| `Files duplicate` | during processing | the content checksum matched an accepted file |

Both mean the telemetry was recognised. They are reported separately rather than
summed so it stays visible *which* check caught it — and a batch of nothing but
already-held telemetry no longer prints zeros across the board and looks like it lost
the files.

Whichever way it is caught, the file lands in **exactly one** outcome bucket. The
counts are derived at read time and must partition the batch: a re-uploaded file is
marked `DUPLICATE` at acquisition *and* linked to the telemetry file it matched, so
counting both sides once reported a one-file batch as "1 ready and 1 already
uploaded".

## Overlapping content is not a duplicate

A file whose event timestamps overlap another file's is **not** a duplicate unless
its bytes are identical. Overlapping uploads are both accepted, both landed, and
Phase 1D reconciles the overlap by frame identity — including allocating
non-colliding `frame_sequence` values across files.

## Filenames

The original filename is metadata. It is never used to build a path, and it is never
trusted to indicate a telemetry date: the business date comes from event timestamps
in the charger's source timezone (Phase 1C §8), exactly as for any other source. A
file named `HYD12_28-07-2026.csv` whose readings are from 27 July is filed under
**2026-07-27**.

## Security

| Threat | Handling |
|---|---|
| Path traversal (`../../etc/passwd`) | filename is never a path; `safe_staged_name` generates the storage name |
| Absolute paths in the filename | same — the supplied name only ever becomes a database column |
| Symlinked staged reference | refused; checked *before* `resolve()`, since resolving dereferences the link |
| Reference escaping staging | every path is re-validated against the resolved staging root on each access |
| Oversized file / batch | per-file, per-batch and file-count ceilings, enforced server-side and published at `GET /ingestion/uploads/limits` |
| Unsupported type | extension allowlist (`CPI_UPLOAD_ALLOWED_EXTENSIONS`) |
| Empty file | rejected at staging with a stated reason |
| Malformed multipart | rejected by FastAPI before any bytes are staged |
| Internal path disclosure | `staged_reference` and `storage_reference` are never serialised into any response |

Logs record filenames, sizes and outcomes. They never record file contents or
telemetry rows.

The browser also pre-checks extension, emptiness and size — purely so an operator
gets feedback before a long transfer. Those checks read the server's own limits from
`/ingestion/uploads/limits`, so they cannot drift from what is enforced, and the
server revalidates everything regardless.

## One bad file does not fail a batch

Batch status is derived from its files, never stored as a counter:

| Condition | Status |
|---|---|
| any file pending or still processing | `PROCESSING` |
| nothing usable and something went wrong | `FAILED` |
| some usable, plus failures/quarantines/rejections/duplicates | `COMPLETED_WITH_WARNINGS` |
| everything usable | `COMPLETED` |

Counts are computed in SQL at read time (`UploadRepository.batch_counts`). A stored
"completed" tally can disagree with the files it claims to describe; a query cannot.

## Operating it

```bash
# Upload through the UI: /data-operations/upload
# Or directly:
curl -F files=@HYD12_28-07-2026.csv http://localhost:8000/api/v1/ingestion/uploads

# Then process queued batches (the worker path):
ingest process-uploads

# One specific batch:
ingest process-uploads --batch <uuid>
```

Exit codes match the rest of the CLI: `0` clean, `1` completed with warnings, `2`
nothing processed, `3` unexpected failure.

Reprocessing a batch is safe. `process-uploads` picks up `REGISTERED` and
`PROCESSING` batches, so a worker killed mid-run resumes rather than stranding the
batch, and files already registered are recognised rather than duplicated.

Reprocessing is safe for coverage too, but only because of a fix this phase forced
out. Reconciliation is idempotent and runs again on every later batch and every late
file. The set of file states that count toward a charger-day originally omitted the
Phase 1D states, so the *second* reconciliation of an already-reconstructed day
reported the charger MISSING with 0% coverage — the file intact, the file-days
intact, and the fleet view claiming nothing had arrived. Usability is a statement
about whether a file's profile can be trusted, not about how far down the pipeline it
has travelled.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/ingestion/uploads` | stage a batch, `202` + batch id |
| `GET /api/v1/ingestion/uploads/limits` | limits this deployment enforces |
| `GET /api/v1/ingestion/uploads` | history, newest first, with derived counts |
| `GET /api/v1/ingestion/uploads/{id}` | one batch with outcome counts |
| `GET /api/v1/ingestion/uploads/{id}/files` | files in a batch, filterable by status/charger/date |

## Related

- [source-adapters.md](source-adapters.md) — the contract every source implements
- [rms-source-integration.md](rms-source-integration.md) — what replacing upload with RMS involves
- [daily-ingestion.md](daily-ingestion.md) — what happens after acquisition
- [frame-reconstruction.md](frame-reconstruction.md) — how repetition is classified
