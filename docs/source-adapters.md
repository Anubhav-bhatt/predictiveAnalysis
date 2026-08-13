# Telemetry Source Adapters

Every way telemetry can reach the platform is an adapter behind one contract. The
processing pipeline receives a `TelemetrySource` and cannot tell which one it got.

That is not a stylistic preference. The POC ingests manual uploads; production will
ingest from RMS; a customer may later insist on SFTP or S3. If any analytical stage
could observe the source, each of those would mean re-testing coverage, quality,
duplicate classification and frame reconstruction from scratch.

## The contract

```python
class TelemetrySource(ABC):
    source_type: ClassVar[SourceType]

    async def discover(self) -> Sequence[SourceFileRef]: ...
    def fetch(self, ref: SourceFileRef) -> AsyncIterator[bytes]: ...
    async def metadata(self, ref: SourceFileRef) -> SourceFileMetadata: ...
    async def acknowledge(self, ref: SourceFileRef, outcome: AcknowledgeOutcome) -> None: ...
```

| Method | Responsibility | Must not |
|---|---|---|
| `discover` | enumerate what is available *now* | read file contents |
| `fetch` | stream bytes in chunks | materialise the whole file, or return a path |
| `metadata` | report what the source knows without transferring | be trusted (see below) |
| `acknowledge` | advance source-side state from the outcome | delete anything on failure or quarantine |

Two details in that signature are load-bearing:

**`fetch` returns the iterator, it is not a coroutine.** `IngestionService` does
`async for chunk in source.fetch(ref)`. An adapter that declares `async def fetch`
returning an `AsyncIterator` is one `await` away from being incompatible — this bug
existed in `FilesystemTelemetrySource` and was fixed in Phase 1C.

**`fetch` yields bytes rather than handing over a path.** A path is a filesystem
concept. Committing to it would leak the local filesystem into every later stage and
make SFTP, S3 or an HTTP API impossible to add without rewriting them. Streaming also
keeps memory bounded and lets the checksum be computed in the same pass that writes
to Bronze.

## `SourceFileRef.reference` is opaque

`reference` means something only to the adapter that produced it. Nothing downstream
parses it, and it never appears in an API response. For the filesystem source it is a
path; for manual upload it is a staged path; for RMS it will be whatever identifier
the RMS API uses.

Because a reference round-trips through the pipeline, an adapter **re-validates** it
rather than trusting it. `ManualUploadTelemetrySource._validated_path` re-resolves
every reference against the staging root on each access and refuses symlinks —
checked before `resolve()`, since resolving dereferences the link and would make the
check silently useless.

## Source metadata is untrusted

`metadata()` reports what the *source* claims. The platform re-derives everything it
depends on:

| The source may claim | The platform uses |
|---|---|
| a filename containing a date | event timestamps in the charger's source timezone |
| a size | the bytes actually transferred |
| a modification time | received-at, recorded by the platform |
| a charger identity | the identifier columns inside the file |

This is why a mislabelled upload cannot corrupt coverage: the label was never used.

## `acknowledge` and failure

| Outcome | Filesystem source | Manual upload |
|---|---|---|
| `PROCESSED` | may move/mark the file | deletes staged bytes (Bronze holds the accepted copy) |
| `DUPLICATE` | same | deletes staged bytes (content is provably already stored) |
| `QUARANTINED` | leaves it | **keeps** staged bytes |
| `FAILED` | leaves it | **keeps** staged bytes |

Keeping bytes on failure is deliberate: an operator debugging a rejected upload needs
the file that was actually sent, not a description of it.

## Implemented adapters

| Adapter | `source_type` | Discovery | Notes |
|---|---|---|---|
| `FilesystemTelemetrySource` | `FILESYSTEM` | scans a directory | the original Phase 1A path |
| `ManualUploadTelemetrySource` | `MANUAL_UPLOAD` | lists the batch's staged files | membership is fixed when the upload request completes, so two concurrent batches cannot steal each other's files |
| *(RMS)* | `RMS` | to be built | see [rms-source-integration.md](rms-source-integration.md) |

Note the discovery difference. The filesystem source scans a directory, so whatever
is present gets picked up. Manual upload does **not** scan: it enumerates the exact
files recorded for that batch. Directory scanning under concurrent uploads would let
one worker ingest another batch's files and attribute them to the wrong batch.

## Adding an adapter

1. Subclass `TelemetrySource`, set `source_type` to a new `SourceType` member.
2. Implement the four methods. Put **no** profiling, schema, quality, coverage or
   reconstruction logic in the adapter — those are shared, and duplicating them is
   how two sources start disagreeing.
3. Add a way to construct it (config, CLI subcommand, or scheduler entry).
4. Write the equivalence test: same bytes through the new adapter and through the
   filesystem source must produce identical analytical results, with only
   `source_type` (and any acquisition-specific link column) permitted to differ.
   `tests/integration/test_manual_upload.py` is the template.

Step 4 is the one that matters. It is the only thing that proves source independence
is real rather than intended.

## What must never appear

```python
# Never. Any of these means the platform now has two pipelines to trust.
if source_type == SourceType.MANUAL_UPLOAD:
    manual_processing_pipeline()

if file.source_type == "RMS":
    quality_score *= 1.1

coverage = manual_coverage(...) if is_upload else standard_coverage(...)
```

Branching on source type is legitimate in exactly two places: **acquisition** (how
bytes are obtained) and **presentation** (telling an operator where a file came
from). Anywhere between those two, it is a defect.

## Related

- [manual-upload.md](manual-upload.md) — the upload adapter in operational detail
- [rms-source-integration.md](rms-source-integration.md) — the next adapter
- [daily-ingestion.md](daily-ingestion.md) — the shared pipeline itself
