"""Ingestion orchestration.

Drives one file from discovery to READY_FOR_NORMALIZATION through the explicit
state machine, coordinating the pure pipeline modules with persistence.

Two behaviours are load-bearing:

**Idempotency** (Phase 1A section 15). Identical bytes under the same filename
resolve to the existing logical file; nothing is inserted twice. Identical bytes
under a *different* filename are recorded as a DUPLICATE arrival pointing at the
canonical file, so the event is auditable without creating a second logical
source file.

**Failure containment** (Phase 1C section 43). One corrupt file marks itself
FAILED and the run continues. Only a genuine system-level fault aborts the run.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger, log_context
from backend.app.models.enums import (
    FileStatus,
    IngestionRunStatus,
    IngestionTrigger,
    QualitySeverity,
)
from backend.app.models.ingestion_run import IngestionRun
from backend.app.models.telemetry_file import IdentifierType, TelemetryFile
from backend.app.repositories.ingestion import IngestionRunRepository, TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.schema import SchemaRepository
from backend.app.services.quality_service import QualityService
from backend.app.services.schema_service import SchemaService
from pipelines.ingestion.file_day import build_file_days, dominant_identifier
from pipelines.ingestion.state_machine import assert_transition_allowed
from pipelines.persistence.storage import RawObjectStorage
from pipelines.profiling.event_time import extract_filename_date
from pipelines.profiling.header_parser import HeaderParseError, parse_header
from pipelines.profiling.profiler import FileProfile, ProfilerError, profile_file
from pipelines.quality.base import QualityContext, RuleRegistry
from pipelines.sources.base import AcknowledgeOutcome, SourceFileRef, TelemetrySource
from pipelines.validation.dictionary import DictionaryRegistry

__all__ = ["FileOutcome", "IngestionService", "RunSummary"]

logger = get_logger(__name__)


class QuarantineError(RuntimeError):
    """The file is structurally unusable; it is preserved and set aside."""


@dataclass(frozen=True, slots=True)
class FileOutcome:
    telemetry_file_id: UUID | None
    filename: str
    status: FileStatus
    quality_score: float | None = None
    message: str | None = None
    #: True when this file was already registered with identical bytes and name,
    #: so this run re-derived nothing. Counted separately from work actually done
    #: (section 21) - a run that re-saw 5,000 unchanged files must not report
    #: having processed them.
    already_registered: bool = False


@dataclass(slots=True)
class RunSummary:
    ingestion_run_id: UUID
    status: IngestionRunStatus
    files_discovered: int = 0
    files_registered: int = 0
    files_ready: int = 0
    files_partial: int = 0
    files_duplicate: int = 0
    files_quarantined: int = 0
    files_failed: int = 0
    #: Re-presented files that were already registered; no work was redone.
    files_skipped: int = 0
    outcomes: list[FileOutcome] = field(default_factory=list)


class IngestionService:
    def __init__(
        self,
        *,
        run_repo: IngestionRunRepository,
        file_repo: TelemetryFileRepository,
        schema_repo: SchemaRepository,
        quality_repo: QualityRepository,
        storage: RawObjectStorage,
        dictionary: DictionaryRegistry,
        rules: RuleRegistry,
        settings: Settings,
    ) -> None:
        self._runs = run_repo
        self._files = file_repo
        self._storage = storage
        self._settings = settings
        self._schema = SchemaService(schema_repo, dictionary)
        self._quality = QualityService(quality_repo, rules, settings.quality_weights)
        self._dictionary = dictionary

    @property
    def files(self) -> TelemetryFileRepository:
        """Read-only access for orchestrators that need to ask which dates moved."""
        return self._files

    # -- run level ---------------------------------------------------------

    async def run(
        self,
        source: TelemetrySource,
        *,
        trigger: IngestionTrigger = IngestionTrigger.CLI,
        business_date: dt.date | None = None,
        request_id: str | None = None,
        only: Sequence[SourceFileRef] | None = None,
    ) -> RunSummary:
        """Discover and process every available file from a source."""
        run = await self._runs.create(
            source_type=source.source_type,
            trigger=trigger,
            business_date=business_date,
            request_id=request_id,
        )
        summary = RunSummary(ingestion_run_id=run.id, status=IngestionRunStatus.PROCESSING)

        with log_context(ingestion_run_id=run.id, request_id=request_id):
            run.status = IngestionRunStatus.DISCOVERING
            refs = list(only) if only is not None else list(await source.discover())
            summary.files_discovered = len(refs)
            run.files_discovered = len(refs)
            logger.info("ingestion.discovered", files=len(refs), source=source.describe())

            run.status = IngestionRunStatus.PROCESSING
            for ref in refs:
                outcome = await self.ingest_file(source, ref, run)
                summary.outcomes.append(outcome)
                self._tally(summary, outcome)

            self._apply_counters(run, summary)
            run.status = self._final_status(summary)
            run.finished_at = dt.datetime.now(dt.UTC)
            summary.status = run.status
            logger.info(
                "ingestion.run.finished",
                status=run.status.value,
                ready=summary.files_ready,
                failed=summary.files_failed,
                quarantined=summary.files_quarantined,
                duplicate=summary.files_duplicate,
            )
        return summary

    @staticmethod
    def _tally(summary: RunSummary, outcome: FileOutcome) -> None:
        if outcome.already_registered:
            summary.files_skipped += 1
            return
        match outcome.status:
            case FileStatus.READY_FOR_NORMALIZATION | FileStatus.COMPLETED:
                summary.files_ready += 1
                summary.files_registered += 1
            case FileStatus.PARTIAL:
                summary.files_partial += 1
                summary.files_registered += 1
            case FileStatus.DUPLICATE:
                summary.files_duplicate += 1
            case FileStatus.QUARANTINED:
                summary.files_quarantined += 1
            case FileStatus.FAILED:
                summary.files_failed += 1
            case _:
                summary.files_registered += 1

    @staticmethod
    def _apply_counters(run: IngestionRun, summary: RunSummary) -> None:
        run.files_registered = summary.files_registered
        run.files_ready = summary.files_ready
        run.files_partial = summary.files_partial
        run.files_duplicate = summary.files_duplicate
        run.files_quarantined = summary.files_quarantined
        run.files_failed = summary.files_failed

    @staticmethod
    def _final_status(summary: RunSummary) -> IngestionRunStatus:
        """A few bad files degrade a run; they do not fail it (section 43)."""
        if summary.files_discovered == 0:
            return IngestionRunStatus.COMPLETED
        if summary.files_ready == 0 and (summary.files_failed or summary.files_quarantined):
            return IngestionRunStatus.FAILED
        if summary.files_failed or summary.files_quarantined or summary.files_partial:
            return IngestionRunStatus.COMPLETED_WITH_WARNINGS
        return IngestionRunStatus.COMPLETED

    # -- file level --------------------------------------------------------

    async def ingest_file(
        self, source: TelemetrySource, ref: SourceFileRef, run: IngestionRun
    ) -> FileOutcome:
        """Take one file as far as READY_FOR_NORMALIZATION."""
        telemetry_file: TelemetryFile | None = None
        try:
            self._check_admission(ref)

            telemetry_file, created = await self._register(source, ref, run)

            if not created:
                # Idempotent re-presentation: identical bytes under the same
                # filename. The canonical record stands; nothing is re-derived
                # and no second logical source file appears.
                logger.info(
                    "ingestion.file.already_registered",
                    telemetry_file_id=str(telemetry_file.id),
                    status=telemetry_file.status.value,
                )
                await source.acknowledge(ref, AcknowledgeOutcome.PROCESSED)
                return FileOutcome(
                    telemetry_file_id=telemetry_file.id,
                    filename=ref.display_name,
                    status=telemetry_file.status,
                    quality_score=(
                        float(telemetry_file.quality_score)
                        if telemetry_file.quality_score is not None
                        else None
                    ),
                    message="Already registered; identical content and filename.",
                    already_registered=True,
                )

            with log_context(telemetry_file_id=telemetry_file.id):
                if telemetry_file.status is FileStatus.DUPLICATE:
                    await source.acknowledge(ref, AcknowledgeOutcome.DUPLICATE)
                    return FileOutcome(
                        telemetry_file.id,
                        ref.display_name,
                        FileStatus.DUPLICATE,
                        message="Identical content already registered under another filename.",
                    )

                await self._analyse(telemetry_file, run)
                await source.acknowledge(ref, AcknowledgeOutcome.PROCESSED)
                return FileOutcome(
                    telemetry_file.id,
                    ref.display_name,
                    telemetry_file.status,
                    quality_score=(
                        float(telemetry_file.quality_score)
                        if telemetry_file.quality_score is not None
                        else None
                    ),
                )

        except QuarantineError as exc:
            await self._mark_quarantined(telemetry_file, str(exc))
            await source.acknowledge(ref, AcknowledgeOutcome.QUARANTINED)
            logger.warning("ingestion.file.quarantined", filename=ref.display_name, reason=str(exc))
            return FileOutcome(
                telemetry_file.id if telemetry_file else None,
                ref.display_name,
                FileStatus.QUARANTINED,
                message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not fail the run
            await self._mark_failed(telemetry_file, str(exc))
            await source.acknowledge(ref, AcknowledgeOutcome.FAILED)
            logger.exception("ingestion.file.failed", filename=ref.display_name)
            return FileOutcome(
                telemetry_file.id if telemetry_file else None,
                ref.display_name,
                FileStatus.FAILED,
                message=str(exc),
            )

    # -- steps -------------------------------------------------------------

    def _check_admission(self, ref: SourceFileRef) -> None:
        """Cheap pre-transfer safety gates (section 20)."""
        limits = self._settings.ingest
        name = ref.display_name
        suffix = f".{name.rsplit('.', 1)[-1].lower()}" if "." in name else ""
        if limits.allowed_extensions and suffix not in limits.allowed_extensions:
            raise QuarantineError(
                f"Extension {suffix or '<none>'} is not permitted "
                f"(allowed: {', '.join(limits.allowed_extensions)})"
            )
        if ref.size_bytes > limits.max_file_size_bytes:
            raise QuarantineError(
                f"File size {ref.size_bytes} exceeds the limit of {limits.max_file_size_bytes}"
            )

    async def _register(
        self, source: TelemetrySource, ref: SourceFileRef, run: IngestionRun
    ) -> tuple[TelemetryFile, bool]:
        """Land the bytes, compute the checksum and create the record.

        Returns ``(file, created)``. ``created`` is False when the checksum and
        filename already identify a registered logical file - the idempotency
        boundary. The checksum only exists after transfer, so the duplicate
        check necessarily happens post-landing; the redundant copy is discarded
        rather than left behind.
        """
        file_id = uuid4()
        received_at = dt.datetime.now(dt.UTC)

        chunks = source.fetch(ref)
        stored = await self._storage.store(
            chunks,
            file_id=file_id,
            original_filename=ref.display_name,
            received_at=received_at,
        )

        same_name = await self._files.find_by_checksum_and_name(stored.sha256, ref.display_name)
        if same_name is not None:
            # Idempotent re-presentation: discard the redundant copy we just
            # wrote and return the canonical record untouched.
            self._storage.discard(stored.storage_reference)
            return (same_name, False)

        duplicates = await self._files.find_by_checksum(stored.sha256)
        telemetry_file = TelemetryFile(
            id=file_id,
            ingestion_run_id=run.id,
            source_type=ref.source_type,
            original_filename=ref.display_name,
            source_reference=ref.reference,
            storage_reference=stored.storage_reference,
            sha256=stored.sha256,
            file_size_bytes=stored.size_bytes,
            status=FileStatus.DISCOVERED,
            discovered_at=ref.discovered_at,
            received_at=received_at,
            filename_date=extract_filename_date(ref.display_name),
        )
        await self._files.add(telemetry_file)

        self._transition(telemetry_file, FileStatus.REGISTERED)
        if duplicates:
            canonical = duplicates[0]
            telemetry_file.duplicate_of_file_id = canonical.id
            self._transition(telemetry_file, FileStatus.DUPLICATE)
            logger.info(
                "ingestion.file.duplicate_content",
                telemetry_file_id=str(telemetry_file.id),
                duplicate_of=str(canonical.id),
            )
        return (telemetry_file, True)

    async def _analyse(self, telemetry_file: TelemetryFile, run: IngestionRun) -> None:
        """Profile, register the schema, run quality rules and score."""
        self._transition(telemetry_file, FileStatus.LANDING)
        self._transition(telemetry_file, FileStatus.PROFILING)

        reference = telemetry_file.storage_reference
        if reference is None:  # pragma: no cover - guarded by _register
            raise QuarantineError("File has no stored object to profile")

        with self._storage.materialize_local(reference) as path:
            try:
                header = parse_header(path)
            except HeaderParseError as exc:
                raise QuarantineError(f"Header could not be parsed: {exc}") from exc

            if header.field_count > self._settings.ingest.max_column_count:
                raise QuarantineError(
                    f"Column count {header.field_count} exceeds the configured maximum "
                    f"of {self._settings.ingest.max_column_count}"
                )

            try:
                profile = profile_file(
                    path,
                    timestamp_formats=self._settings.ingest.timestamp_formats,
                    source_timezone=self._settings.fleet.default_source_timezone,
                    sentinel_values=self._settings.ingest.global_sentinel_values,
                    header=header,
                )
            except ProfilerError as exc:
                raise QuarantineError(str(exc)) from exc

        if profile.row_count > self._settings.ingest.max_row_count:
            raise QuarantineError(
                f"Row count {profile.row_count} exceeds the configured maximum "
                f"of {self._settings.ingest.max_row_count}"
            )

        timestamps = profile.timestamps
        if not timestamps.is_within_tolerance(self._settings.ingest.timestamp_failure_tolerance):
            raise QuarantineError(
                f"Event-time parsing failed for {timestamps.failure_ratio:.2%} of values, "
                f"beyond the configured tolerance of "
                f"{self._settings.ingest.timestamp_failure_tolerance:.2%}"
            )

        self._apply_profile(telemetry_file, profile)

        # Business identifiers must be persisted here: Phase 1C reconciliation
        # groups charger-days by them, so a file whose identifiers were never
        # written would silently look like a charger that sent nothing.
        await self.persist_identifiers(telemetry_file, profile)

        # --- per-date contributions (Phase 1C sections 8, 19) -------------
        await self.persist_file_days(telemetry_file, profile)

        # --- schema -------------------------------------------------------
        self._transition(telemetry_file, FileStatus.SCHEMA_VALIDATION)
        resolution = await self._schema.resolve(profile.header)
        telemetry_file.schema_version_id = resolution.schema_version.id
        telemetry_file.header_fingerprint = profile.header.header_fingerprint
        telemetry_file.schema_compatibility = resolution.comparison.compatibility

        # --- quality ------------------------------------------------------
        self._transition(telemetry_file, FileStatus.QUALITY_VALIDATION)
        context = QualityContext(
            profile=profile,
            resolved_fields=resolution.resolved_fields,
            registry=self._dictionary,
            original_filename=telemetry_file.original_filename,
            filename_date=telemetry_file.filename_date,
            expected_connector_count=self._settings.ingest.expected_connector_count,
            expected_smr_count=self._settings.ingest.expected_smr_count,
            telemetry_gap_factor=self._settings.ingest.telemetry_gap_factor,
            timestamp_failure_tolerance=self._settings.ingest.timestamp_failure_tolerance,
            missing_schema_fields=resolution.comparison.missing_all,
            additional_schema_fields=resolution.comparison.additional,
            schema_is_known=not resolution.created,
        )
        outcome = await self._quality.analyse(
            telemetry_file_id=telemetry_file.id,
            ingestion_run_id=run.id,
            context=context,
        )

        scores = outcome.score.as_decimals()
        telemetry_file.quality_score = scores["quality_score"]
        telemetry_file.schema_quality = scores["schema_quality"]
        telemetry_file.completeness_quality = scores["completeness_quality"]
        telemetry_file.validity_quality = scores["validity_quality"]
        telemetry_file.duplicate_quality = scores["duplicate_quality"]
        telemetry_file.timestamp_quality = scores["timestamp_quality"]
        telemetry_file.processed_at = dt.datetime.now(dt.UTC)

        # A CRITICAL finding means the file cannot be trusted downstream.
        if any(f.severity is QualitySeverity.CRITICAL for f in outcome.findings):
            raise QuarantineError("Critical data-quality findings prevent normalization")

        self._transition(telemetry_file, FileStatus.READY_FOR_NORMALIZATION)

    def _apply_profile(self, telemetry_file: TelemetryFile, profile: FileProfile) -> None:
        timestamps = profile.timestamps

        telemetry_file.row_count = profile.row_count
        telemetry_file.column_count = profile.column_count
        telemetry_file.connector_count_detected = profile.connector_count
        telemetry_file.smr_count_detected = profile.smr_count
        telemetry_file.session_id_count = len(profile.session_ids)

        telemetry_file.event_time_min = timestamps.event_time_min
        telemetry_file.event_time_max = timestamps.event_time_max
        telemetry_file.event_time_format = timestamps.chosen_format
        telemetry_file.unique_event_timestamp_count = timestamps.unique_count
        telemetry_file.invalid_timestamp_count = timestamps.failed_count
        telemetry_file.median_sampling_interval_seconds = (
            Decimal(f"{timestamps.median_interval_seconds:.3f}")
            if timestamps.median_interval_seconds is not None
            else None
        )
        # Business date comes from telemetry content only - never the filename.
        telemetry_file.business_date = timestamps.dominant_business_date
        telemetry_file.distinct_business_date_count = len(timestamps.business_dates)
        telemetry_file.file_date_span = timestamps.date_span

        duplicates = profile.duplicates
        telemetry_file.exact_duplicate_row_count = duplicates.exact_duplicate_rows
        telemetry_file.duplicate_participating_row_count = (
            duplicates.rows_participating_in_duplicates
        )
        telemetry_file.logical_key_collision_group_count = duplicates.logical_collision_groups
        telemetry_file.logical_key_conflicting_group_count = duplicates.conflicting_logical_groups
        telemetry_file.max_occurrences_per_logical_key = duplicates.max_rows_per_logical_key

        telemetry_file.empty_field_count = len(profile.empty_fields)
        telemetry_file.constant_field_count = len(profile.constant_fields)
        telemetry_file.varying_field_count = len(profile.varying_fields)
        telemetry_file.duplicate_header_count = profile.header.duplicate_header_count
        telemetry_file.profiling_duration_ms = profile.profiling_duration_ms

        logger.info(
            "ingestion.profiled",
            rows=profile.row_count,
            columns=profile.column_count,
            unique_timestamps=timestamps.unique_count,
            business_date=(
                timestamps.dominant_business_date.isoformat()
                if timestamps.dominant_business_date
                else None
            ),
            duration_ms=profile.profiling_duration_ms,
        )

    async def persist_identifiers(
        self, telemetry_file: TelemetryFile, profile: FileProfile
    ) -> None:
        rows = [
            {
                "id": uuid4(),
                "telemetry_file_id": telemetry_file.id,
                "identifier_type": kind,
                "value": value,
                "occurrence_count": count,
            }
            for kind, mapping in (
                (IdentifierType.CHARGER, profile.charger_ids),
                (IdentifierType.OCPP, profile.ocpp_ids),
                (IdentifierType.SESSION, profile.session_ids),
                (IdentifierType.CONNECTOR, profile.connectors),
                (IdentifierType.SMR, profile.smrs),
            )
            for value, count in mapping.items()
        ]
        await self._files.replace_identifiers(telemetry_file.id, rows)

    async def persist_file_days(self, telemetry_file: TelemetryFile, profile: FileProfile) -> None:
        """Record one row per business date this file actually contains.

        This is what lets reconciliation rebuild a charger-day later - after a
        late or overlapping file arrives - without re-reading the raw CSV
        (Phase 1C sections 8, 19, 24).
        """
        charger_id = dominant_identifier(profile.charger_ids)
        if charger_id is None:
            # Nothing to attribute the telemetry to. The file stays registered and
            # profiled; it simply cannot contribute to any charger-day, and the
            # quality engine has already recorded the missing identifier.
            logger.warning(
                "ingestion.file_days.no_charger_identifier",
                telemetry_file_id=str(telemetry_file.id),
            )
            await self._files.replace_file_days(telemetry_file.id, [])
            return

        contributions = build_file_days(
            profile,
            charger_id=charger_id,
            source_timezone=self._settings.fleet.default_source_timezone,
        )
        await self._files.replace_file_days(
            telemetry_file.id,
            [c.as_row(telemetry_file_id=telemetry_file.id) for c in contributions],
        )
        logger.info(
            "ingestion.file_days.persisted",
            telemetry_file_id=str(telemetry_file.id),
            charger_id=charger_id,
            business_dates=[c.business_date.isoformat() for c in contributions],
            unique_timestamps=[c.unique_timestamp_count for c in contributions],
        )

    # -- state transitions -------------------------------------------------

    def _transition(self, telemetry_file: TelemetryFile, target: FileStatus) -> None:
        current = telemetry_file.status
        assert_transition_allowed(current, target)
        telemetry_file.status = target
        logger.debug("ingestion.state", **{"from": current.value, "to": target.value})

    async def _mark_quarantined(self, telemetry_file: TelemetryFile | None, reason: str) -> None:
        if telemetry_file is None:
            return
        telemetry_file.quarantine_reason = reason[:2000]
        if telemetry_file.storage_reference:
            try:
                self._storage.quarantine(telemetry_file.storage_reference, reason=reason)
            except (OSError, ValueError):  # pragma: no cover - best effort
                logger.warning("ingestion.quarantine.copy_failed")
        telemetry_file.status = FileStatus.QUARANTINED

    async def _mark_failed(self, telemetry_file: TelemetryFile | None, reason: str) -> None:
        if telemetry_file is None:
            return
        telemetry_file.failure_reason = reason[:2000]
        telemetry_file.status = FileStatus.FAILED


@dataclass(frozen=True, slots=True)
class _ExistingMatch:
    file: TelemetryFile
    sha_matches_name: bool
