# RMS Source Integration (Future Work)

The RMS integration does not exist yet. This document records what building it
involves, so that the decision to add it does not become a decision to rewrite the
pipeline.

**The short version: RMS becomes one more adapter. Nothing downstream changes.**

## What must change

Exactly three things:

1. A new `RmsTelemetrySource(TelemetrySource)` implementing `discover`, `fetch`,
   `metadata`, `acknowledge`.
2. Configuration for it — endpoint, credentials, polling window, retry policy.
3. A trigger: a CLI subcommand and/or scheduler entry that constructs it and calls
   `IngestionService.run`.

## What must not change

| Layer | Why it stays untouched |
|---|---|
| Profiling | operates on bytes and a schema, not on provenance |
| Schema validation & registry | a schema is a property of the file |
| Quality scoring | a quality score that varied by source would be uncomparable across the fleet |
| Duplicate/replay classification | content checksums are source-blind by construction |
| Bronze landing | already stores `source_type` as a column, not as a code path |
| Coverage & completeness (1C) | computed from unique event timestamps |
| Frame reconstruction (1D) | keyed on `(charger_id, event_time, frame_sequence, reconstruction_version)` |
| Historical query layer | reads telemetry, not acquisition records |

If implementing RMS requires editing anything in that table, the abstraction has
leaked and the fix belongs in the adapter, not downstream.

## Migration is a co-existence, not a cutover

Manual upload does not get removed when RMS arrives. Both remain enabled, because:

- RMS outages need a manual fallback.
- Historical backfills predating the integration still arrive as files.
- Comparing an RMS-collected file against the same file uploaded manually is the
  cheapest possible verification that the new adapter is correct.

Duplicate detection makes co-existence safe. It is by content checksum and
source-blind, so a file that arrives both ways is recognised once and stored once —
the second arrival is classified `DUPLICATE`, not stored again. `source_type` records
which path won the race; it does not change the result.

## Sketch

```python
class RmsTelemetrySource(TelemetrySource):
    source_type: ClassVar[SourceType] = SourceType.RMS

    async def discover(self) -> Sequence[SourceFileRef]:
        # Ask RMS what is available in the polling window. Return refs whose
        # `reference` is whatever identifier RMS uses - opaque to everything else.
        ...

    def fetch(self, ref: SourceFileRef) -> AsyncIterator[bytes]:
        # Stream the response body in chunks. Note: NOT `async def` - the base
        # contract returns the iterator directly.
        ...

    async def metadata(self, ref: SourceFileRef) -> SourceFileMetadata:
        # What RMS claims. Treated as untrusted; the platform re-derives anything
        # it actually depends on.
        ...

    async def acknowledge(self, ref: SourceFileRef, outcome: AcknowledgeOutcome) -> None:
        # Advance RMS-side state on success/duplicate. Do NOT acknowledge on
        # FAILED or QUARANTINED - an unacknowledged file can be retried, an
        # acknowledged one may be gone.
        ...
```

## Problems specific to a network source

The filesystem and staging sources are local and effectively instantaneous. An API
source is not, and these are the parts that need real design work rather than a
straight port:

**Partial transfers.** A truncated download must never be landed as a complete file.
The checksum is computed during transfer; a size mismatch against `metadata()` should
fail the file rather than accept a short read.

**Retries and idempotency.** Re-fetching after a timeout must not create a second
telemetry file. Content-checksum duplicate detection already covers this, but the
adapter should also avoid re-transferring what it already has.

**Rate limits and windows.** `discover` needs a bounded window with a durable
high-water mark, or a restart will either re-enumerate everything or skip files.

**Authentication.** Credentials belong in settings, never in a `SourceFileRef` — refs
are logged and passed around.

**Clock skew.** RMS timestamps are source metadata. Business date still comes from
event timestamps in the charger's source timezone (Phase 1C §8). An RMS-supplied
collection time is not a substitute.

**Acknowledgement semantics.** If RMS deletes on acknowledge, acknowledging a
quarantined file destroys the evidence needed to diagnose it. Hence the rule above.

## Verification when it is built

The same test that proves manual upload is source-independent must be extended, not
replaced:

```
same bytes → filesystem source ─┐
same bytes → manual upload     ─┼─► identical business date, row/timestamp counts,
same bytes → RMS source        ─┘   schema id, all five quality dimensions,
                                    duplicate/replay profile, coverage, frames
```

Only `source_type` and acquisition-specific link columns may differ.

Until that test passes for the RMS adapter, the integration is not done — regardless
of whether files are arriving.

## Related

- [source-adapters.md](source-adapters.md) — the contract to implement
- [manual-upload.md](manual-upload.md) — the reference implementation
