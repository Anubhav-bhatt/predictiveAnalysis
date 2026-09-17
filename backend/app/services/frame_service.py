"""Frame reconstruction orchestration (Phase 1D sections 34, 43).

Bridges the pure algorithm in :mod:`pipelines.frame_reconstruction` to persistence.
The service loads a registered file from Bronze, re-derives the profile it needs,
runs reconstruction, and writes frames, provenance and diagnostics.

Two properties are load-bearing:

**Transactional per file** (section 34). One file's frames, sources, rows and
findings are written inside the caller's transaction. A failure part-way leaves no
half-persisted frame structure.

**Idempotent** (section 33). Reconstruction is scoped to
``(telemetry_file, reconstruction_version)`` and replaces that scope wholesale, so
re-running the same immutable file changes nothing. Running a new algorithm version
is additive, because the version is part of frame identity.

Cross-file replay (section 23) is handled by looking up existing frames with the
same ``(charger_id, frame_fingerprint)`` before inserting: a payload already known
from another file is recorded as an additional *source* of the existing canonical
frame rather than as a second frame.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
import sqlalchemy as sa

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger, log_context
from backend.app.models.enums import (
    CanonicalDataType,
    DuplicateClassification,
    FileStatus,
    FrameStatus,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.models.telemetry_frame import TelemetrySourceFrame
from backend.app.repositories.fleet import FleetRepository
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from pipelines.frame_reconstruction.canonical_serializer import CanonicalSerializer
from pipelines.frame_reconstruction.models import (
    RECONSTRUCTION_VERSION,
    ReconstructedFrame,
)
from pipelines.frame_reconstruction.reconstruction_service import (
    ReconstructionInput,
    ReconstructionOutcome,
    reconstruct,
)
from pipelines.ingestion.file_day import dominant_identifier
from pipelines.ingestion.state_machine import assert_transition_allowed
from pipelines.persistence.storage import RawObjectStorage
from pipelines.profiling.column_roles import ColumnRole, resolve_roles
from pipelines.profiling.event_time import resolve_timezone
from pipelines.profiling.header_parser import RawHeaderParseResult, parse_header
from pipelines.profiling.profiler import FileProfile, profile_file
from pipelines.validation.dictionary import DictionaryRegistry

__all__ = ["FrameReconstructionResult", "FrameReconstructionService"]

logger = get_logger(__name__)

#: Frame-scope rule severities. Configurable defaults rather than business
#: assertions (section 31): a replay is informational, an ambiguous boundary is
#: not, and an unassigned row means telemetry we cannot place.
DEFAULT_FRAME_SEVERITIES: dict[str, QualitySeverity] = {
    "FULL_FRAME_REPLAY": QualitySeverity.INFO,
    "PARTIAL_FRAME_REPLAY": QualitySeverity.WARNING,
    "SAME_TIMESTAMP_DISTINCT_FRAME": QualitySeverity.INFO,
    "FRAME_MISSING_POSITION": QualitySeverity.WARNING,
    "FRAME_UNEXPECTED_POSITION": QualitySeverity.WARNING,
    "AMBIGUOUS_FRAME_BOUNDARY": QualitySeverity.ERROR,
    "INCONSISTENT_TOPOLOGY": QualitySeverity.WARNING,
    "UNASSIGNED_RAW_ROW": QualitySeverity.WARNING,
    "ENTITY_ID_MISSING": QualitySeverity.WARNING,
}


@dataclass(slots=True)
class FrameReconstructionResult:
    """Outcome of reconstructing one file."""

    telemetry_file_id: UUID
    charger_id: str | None
    outcome: ReconstructionOutcome | None
    frames_persisted: int = 0
    frames_reused_from_other_files: int = 0
    findings_persisted: int = 0
    skipped_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is not None and self.skipped_reason is None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "telemetry_file_id": str(self.telemetry_file_id),
            "charger_id": self.charger_id,
            "frames_persisted": self.frames_persisted,
            "frames_reused_from_other_files": self.frames_reused_from_other_files,
            "findings_persisted": self.findings_persisted,
            "skipped_reason": self.skipped_reason,
        }
        if self.outcome is not None:
            payload["metrics"] = self.outcome.metrics.as_dict()
            payload["topology"] = self.outcome.topology.describe()
        return payload


class FrameReconstructionService:
    def __init__(
        self,
        *,
        frame_repo: FrameRepository,
        file_repo: TelemetryFileRepository,
        fleet_repo: FleetRepository,
        quality_repo: QualityRepository,
        storage: RawObjectStorage,
        dictionary: DictionaryRegistry,
        settings: Settings,
    ) -> None:
        self._frames = frame_repo
        self._files = file_repo
        self._fleet = fleet_repo
        self._quality = quality_repo
        self._storage = storage
        self._dictionary = dictionary
        self._settings = settings

    # -- public API --------------------------------------------------------

    async def reconstruct_file(
        self,
        telemetry_file: TelemetryFile,
        *,
        reconstruction_version: str = RECONSTRUCTION_VERSION,
        advance_lifecycle: bool = True,
    ) -> FrameReconstructionResult:
        """Reconstruct one registered file's frames."""
        result = FrameReconstructionResult(
            telemetry_file_id=telemetry_file.id, charger_id=None, outcome=None
        )

        with log_context(telemetry_file_id=telemetry_file.id):
            if telemetry_file.storage_reference is None:
                result.skipped_reason = "file has no stored object to reconstruct from"
                return result

            if advance_lifecycle:
                self._transition(telemetry_file, FileStatus.FRAME_RECONSTRUCTION)

            # Re-read from Bronze: Phase 1C persisted timestamps, not row values,
            # and Bronze is the authoritative copy of the telemetry.
            with self._storage.materialize_local(telemetry_file.storage_reference) as path:
                header = parse_header(path)
                profile = profile_file(
                    path,
                    timestamp_formats=self._settings.ingest.timestamp_formats,
                    source_timezone=self._settings.fleet.default_source_timezone,
                    sentinel_values=self._settings.ingest.global_sentinel_values,
                    header=header,
                )
                frame_data = self._load_frame(path, header)

            charger_id = self._dominant_charger(profile)
            result.charger_id = charger_id

            charger = await self._fleet.get_charger(charger_id) if charger_id else None
            serializer = self._build_serializer(header)

            outcome = reconstruct(
                ReconstructionInput(
                    frame=frame_data,
                    event_times=list(profile.timestamps.row_event_times),
                    roles=profile.roles,
                    serializer=serializer,
                    telemetry_file_id=telemetry_file.id,
                    charger_id_fallback=charger_id,
                    charger_connector_count=(charger.expected_connector_count if charger else None),
                    charger_smr_count=charger.expected_smr_count if charger else None,
                    default_connector_count=self._settings.ingest.expected_connector_count,
                    default_smr_count=self._settings.ingest.expected_smr_count,
                )
            )
            result.outcome = outcome

            await self._persist(
                telemetry_file,
                outcome,
                charger_pk=charger.id if charger else None,
                # Charger override first, then the configured default - the same
                # precedence Phase 1C applies.
                source_timezone=(
                    (charger.source_timezone if charger else None)
                    or self._settings.fleet.default_source_timezone
                ),
                reconstruction_version=reconstruction_version,
                result=result,
            )

            if advance_lifecycle:
                self._transition(telemetry_file, FileStatus.FRAMES_RECONSTRUCTED)

            logger.info(
                "frames.reconstructed",
                charger_id=charger_id,
                reconstruction_version=reconstruction_version,
                frame_count=outcome.metrics.frames_reconstructed,
                canonical_frame_count=outcome.metrics.canonical_frames,
                replay_count=(
                    outcome.metrics.full_frame_replays + outcome.metrics.partial_frame_replays
                ),
                collision_count=outcome.metrics.collision_timestamps,
                partial_count=outcome.metrics.partial_frames,
                unassigned_row_count=outcome.metrics.rows_unassigned,
                frames_persisted=result.frames_persisted,
                duration_ms=outcome.metrics.duration_ms,
            )
            return result

    async def reconstruct_charger_day(
        self,
        charger_id: str,
        business_date: dt.date,
        *,
        reconstruction_version: str = RECONSTRUCTION_VERSION,
    ) -> list[FrameReconstructionResult]:
        """Reconstruct every usable file contributing to one charger-day.

        Files are processed in receipt order so that cross-file replay attribution
        is deterministic: the earliest-received file owns the canonical frame
        (section 33).
        """
        files = await self._files.files_for_charger_day(charger_id, business_date)
        results: list[FrameReconstructionResult] = []
        for telemetry_file in files:
            try:
                results.append(await self.reconstruct_file(telemetry_file))
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the day
                logger.exception(
                    "frames.file_failed",
                    telemetry_file_id=str(telemetry_file.id),
                    error=str(exc),
                )
                results.append(
                    FrameReconstructionResult(
                        telemetry_file_id=telemetry_file.id,
                        charger_id=charger_id,
                        outcome=None,
                        skipped_reason=str(exc),
                    )
                )
        return results

    # -- internals ---------------------------------------------------------

    def _transition(self, telemetry_file: TelemetryFile, target: FileStatus) -> None:
        assert_transition_allowed(telemetry_file.status, target)
        telemetry_file.status = target

    @staticmethod
    def _load_frame(path: Path, header: RawHeaderParseResult) -> pl.DataFrame:
        """Read the CSV as text using the profiler's canonical column names.

        Mirrors the profiler's reader settings exactly, so reconstruction sees the
        same bytes-to-text interpretation the profile was built from.
        """
        return pl.read_csv(
            path,
            has_header=False,
            skip_rows=1,
            new_columns=list(header.canonical_names),
            infer_schema_length=0,
            empty_string_is_null=True,
            low_memory=False,
            encoding="utf8-lossy",
        )

    @staticmethod
    def _dominant_charger(profile: FileProfile) -> str | None:
        return dominant_identifier(profile.charger_ids)

    def _build_serializer(self, header: RawHeaderParseResult) -> CanonicalSerializer:
        """Type map and null literals from the Phase 1B dictionary."""
        field_types: dict[str, CanonicalDataType] = {}
        for position, canonical_name in enumerate(header.canonical_names):
            source_name = (
                header.source_names[position]
                if position < len(header.source_names)
                else canonical_name
            )
            spec = self._dictionary.by_name.get(canonical_name) or (
                self._dictionary.by_name.get(source_name)
            )
            field_types[canonical_name] = spec.data_type if spec else CanonicalDataType.UNKNOWN

        # Both token maps from the Phase 1B missing-value contract. `explicit_states`
        # is deliberately NOT included: "Not alarm" is a real reported state, not
        # absence, and folding it into null would erase the fact that the charger
        # said "no alarm".
        registry = self._dictionary.missing_values
        nulls = {token.casefold() for token in registry.missing_tokens} | {
            token.casefold() for token in registry.case_insensitive_tokens
        }

        roles = self._role_columns(header)
        return CanonicalSerializer(
            field_types=field_types,
            null_literals=frozenset(nulls),
            # Identity columns are excluded from payload fingerprints: frames at
            # one timestamp share them by definition, so they add no
            # discriminating power, and excluding them keeps a frame's identity
            # independent of which file carried it (section 13).
            excluded_fields=frozenset(roles),
        )

    @staticmethod
    def _role_columns(header: RawHeaderParseResult) -> set[str]:
        resolution = resolve_roles(list(header.canonical_names), list(header.source_names))
        excluded: set[str] = set()
        for role in (ColumnRole.CHARGER_ID, ColumnRole.EVENT_TIME, ColumnRole.OCPP_ID):
            resolved = resolution.get(role)
            if resolved is not None:
                excluded.add(resolved.canonical_name)
        return excluded

    async def _persist(
        self,
        telemetry_file: TelemetryFile,
        outcome: ReconstructionOutcome,
        *,
        charger_pk: UUID | None,
        source_timezone: str,
        reconstruction_version: str,
        result: FrameReconstructionResult,
    ) -> None:
        """Write frames, provenance and findings for one file."""
        # Idempotency: replace this file's frames for this algorithm version.
        await self._frames.delete_for_file(
            telemetry_file.id, reconstruction_version=reconstruction_version
        )

        business_date = telemetry_file.business_date
        existing_by_fingerprint = await self._existing_fingerprints(outcome, reconstruction_version)
        # frame_sequence is assigned by the algorithm *per file*, so two
        # overlapping files would both start at 0 and collide on frame identity.
        # Persistence therefore allocates the next free sequence per
        # (charger, event_time), preserving the file's relative ordering within a
        # timestamp. For the common single-file case this is a no-op.
        next_sequence = await self._next_free_sequences(outcome, reconstruction_version)

        frame_rows: list[dict[str, object]] = []
        source_rows: list[dict[str, object]] = []
        row_rows: list[dict[str, object]] = []
        replay_links: list[tuple[UUID, UUID]] = []
        sequence_to_id: dict[tuple[dt.datetime, int], UUID] = {}

        for frame in outcome.frames:
            date_for_frame = self._business_date_for(frame, source_timezone, business_date)
            reused_id = existing_by_fingerprint.get(frame.frame_fingerprint)

            if reused_id is not None:
                # Cross-file replay: this payload is already a known canonical
                # frame from another file. Record this file as an additional
                # source rather than duplicating the frame (section 24).
                result.frames_reused_from_other_files += 1
                source_rows.append(
                    self._source_row(
                        frame_id=reused_id,
                        telemetry_file_id=telemetry_file.id,
                        frame=frame,
                        occurrence=1,
                        is_primary=False,
                    )
                )
                row_rows.extend(self._row_rows(reused_id, telemetry_file.id, frame))
                continue

            frame_id = uuid4()
            key = (frame.charger_id, frame.event_time)
            assigned_sequence = next_sequence.get(key, frame.frame_sequence)
            next_sequence[key] = assigned_sequence + 1
            sequence_to_id[(frame.event_time, frame.frame_sequence)] = frame_id
            frame_rows.append(
                {
                    "id": frame_id,
                    "charger_pk": charger_pk,
                    "charger_id": frame.charger_id,
                    "event_time": frame.event_time,
                    "business_date": date_for_frame,
                    "frame_sequence": assigned_sequence,
                    "frame_fingerprint": frame.frame_fingerprint,
                    "frame_status": FrameStatus(frame.status.value),
                    "duplicate_classification": DuplicateClassification(
                        frame.duplicate_classification.value
                    ),
                    "replay_of_frame_id": None,
                    "expected_position_count": frame.expected_position_count,
                    "observed_position_count": frame.observed_position_count,
                    "missing_position_count": frame.missing_position_count,
                    "unexpected_position_count": frame.unexpected_position_count,
                    "completeness_percentage": Decimal(str(frame.completeness_percentage)),
                    "source_order_min": frame.source_order_min,
                    "source_order_max": frame.source_order_max,
                    "reconstruction_version": reconstruction_version,
                    "detail": self._frame_detail(frame),
                    "created_at": dt.datetime.now(dt.UTC),
                    "updated_at": dt.datetime.now(dt.UTC),
                }
            )
            source_rows.append(
                self._source_row(
                    frame_id=frame_id,
                    telemetry_file_id=telemetry_file.id,
                    frame=frame,
                    occurrence=0,
                    is_primary=True,
                )
            )
            row_rows.extend(self._row_rows(frame_id, telemetry_file.id, frame))

        await self._frames.insert_frames(frame_rows)
        await self._frames.insert_sources(source_rows)

        # Unassigned rows are persisted too, so nothing silently disappears.
        row_rows.extend(self._unassigned_row_rows(outcome, telemetry_file.id, sequence_to_id))
        await self._frames.insert_frame_rows(row_rows)

        # Replay pointers, now that every frame id exists.
        for frame in outcome.frames:
            if frame.replay_of_sequence is None:
                continue
            source_id = sequence_to_id.get((frame.event_time, frame.frame_sequence))
            target_id = sequence_to_id.get((frame.event_time, frame.replay_of_sequence))
            if source_id and target_id:
                replay_links.append((source_id, target_id))
        await self._frames.set_replay_targets(replay_links)

        result.frames_persisted = len(frame_rows)
        result.findings_persisted = await self._persist_findings(
            telemetry_file, outcome, reconstruction_version
        )

    async def _existing_fingerprints(
        self, outcome: ReconstructionOutcome, reconstruction_version: str
    ) -> dict[str, UUID]:
        """Look up canonical frames from *other* files with the same payload."""
        # Every frame, not only canonical ones. A replay or partial frame arriving
        # in a second overlapping file is still the same payload we already hold,
        # and skipping it here would try to insert a colliding frame.
        fingerprints = [frame.frame_fingerprint for frame in outcome.frames]
        if not fingerprints:
            return {}
        charger_ids = {frame.charger_id for frame in outcome.frames}
        rows = await self._frames.session.execute(
            sa.select(TelemetrySourceFrame.frame_fingerprint, TelemetrySourceFrame.id).where(
                TelemetrySourceFrame.charger_id.in_(charger_ids),
                TelemetrySourceFrame.frame_fingerprint.in_(fingerprints),
                TelemetrySourceFrame.reconstruction_version == reconstruction_version,
            )
        )
        return dict(rows.all())  # type: ignore[arg-type]

    async def _next_free_sequences(
        self, outcome: ReconstructionOutcome, reconstruction_version: str
    ) -> dict[tuple[str, dt.datetime], int]:
        """Next unused frame_sequence per (charger, event_time).

        Starts from one past the highest sequence already stored for that
        timestamp, so a second overlapping file appends rather than colliding.
        """
        if not outcome.frames:
            return {}
        chargers = {frame.charger_id for frame in outcome.frames}
        times = {frame.event_time for frame in outcome.frames}
        rows = await self._frames.session.execute(
            sa.select(
                TelemetrySourceFrame.charger_id,
                TelemetrySourceFrame.event_time,
                sa.func.max(TelemetrySourceFrame.frame_sequence),
            )
            .where(
                TelemetrySourceFrame.charger_id.in_(chargers),
                TelemetrySourceFrame.event_time.in_(times),
                TelemetrySourceFrame.reconstruction_version == reconstruction_version,
            )
            .group_by(TelemetrySourceFrame.charger_id, TelemetrySourceFrame.event_time)
        )
        return {
            (charger_id, event_time): int(highest) + 1
            for charger_id, event_time, highest in rows.all()
        }

    @staticmethod
    def _business_date_for(
        frame: ReconstructedFrame, source_timezone: str, fallback: dt.date | None
    ) -> dt.date:
        """Business date for a frame, in the charger's *local* timezone.

        Uses the frame's own event time rather than the file's dominant date, so a
        cross-midnight file attributes each frame to the day it belongs to.

        The timezone conversion is essential and not incidental: event times are
        stored UTC-aware, and taking ``.date()`` off the UTC instant would place
        every IST timestamp before 05:30 on the previous day - disagreeing with the
        Phase 1C business date for the very same telemetry.
        """
        event_time = frame.event_time
        if event_time.tzinfo is None:
            return fallback if fallback is not None else event_time.date()
        tzinfo = resolve_timezone(source_timezone)
        return event_time.astimezone(tzinfo).date()

    @staticmethod
    def _source_row(
        *,
        frame_id: UUID,
        telemetry_file_id: UUID,
        frame: ReconstructedFrame,
        occurrence: int,
        is_primary: bool,
    ) -> dict[str, object]:
        return {
            "frame_id": frame_id,
            "telemetry_file_id": telemetry_file_id,
            "first_source_row": frame.source_order_min,
            "last_source_row": frame.source_order_max,
            "row_count": len(frame.rows),
            "source_occurrence": occurrence,
            "is_primary_source": is_primary,
            "created_at": dt.datetime.now(dt.UTC),
        }

    @staticmethod
    def _row_rows(
        frame_id: UUID, telemetry_file_id: UUID, frame: ReconstructedFrame
    ) -> list[dict[str, object]]:
        return [
            {
                "frame_id": frame_id,
                "telemetry_file_id": telemetry_file_id,
                "source_row_number": row.source_row_number,
                "connector_id": row.position.connector_id or None,
                "smr_id": row.position.smr_id or None,
                "logical_position": str(row.position) if row.position.is_assigned else None,
                "occurrence_index": row.occurrence_index,
                "row_fingerprint": row.row_fingerprint,
                "unassigned": row.unassigned,
                "created_at": dt.datetime.now(dt.UTC),
            }
            for row in frame.rows
        ]

    @staticmethod
    def _unassigned_row_rows(
        outcome: ReconstructionOutcome,
        telemetry_file_id: UUID,
        sequence_to_id: dict[tuple[dt.datetime, int], UUID],
    ) -> list[dict[str, object]]:
        """Attach unassigned rows to the first frame so they stay traceable.

        They carry ``unassigned=True``, so they are excluded from frame payloads
        while remaining queryable and countable (section 22).
        """
        if not outcome.unassigned_rows or not sequence_to_id:
            return []
        anchor = sequence_to_id[min(sequence_to_id)]
        return [
            {
                "frame_id": anchor,
                "telemetry_file_id": telemetry_file_id,
                "source_row_number": row.source_row_number,
                "connector_id": row.position.connector_id or None,
                "smr_id": row.position.smr_id or None,
                "logical_position": None,
                "occurrence_index": row.occurrence_index,
                "row_fingerprint": row.row_fingerprint,
                "unassigned": True,
                "created_at": dt.datetime.now(dt.UTC),
            }
            for row in outcome.unassigned_rows
        ]

    @staticmethod
    def _frame_detail(frame: ReconstructedFrame) -> dict[str, object]:
        detail = dict(frame.detail)
        if frame.missing_positions:
            detail["missing_positions"] = [str(p) for p in frame.missing_positions]
        if frame.unexpected_positions:
            detail["unexpected_positions"] = [str(p) for p in frame.unexpected_positions]
        if frame.issues:
            detail["issues"] = [issue.value for issue in frame.issues]
        return detail

    async def _persist_findings(
        self,
        telemetry_file: TelemetryFile,
        outcome: ReconstructionOutcome,
        reconstruction_version: str,
    ) -> int:
        """Persist frame diagnostics through the existing quality framework.

        Aggregated per rule code rather than one row per frame: a file with 700
        replays produces one INFO finding carrying the count, not 700 rows
        (section 30 - one issue system, not two).
        """
        counts: dict[str, int] = {}
        for frame in outcome.frames:
            for issue in frame.issues:
                counts[issue.value] = counts.get(issue.value, 0) + 1
        if outcome.metrics.rows_unassigned:
            counts["UNASSIGNED_RAW_ROW"] = outcome.metrics.rows_unassigned

        rows: list[dict[str, object]] = []
        for code, count in sorted(counts.items()):
            try:
                rule_code = QualityIssueType(code)
            except ValueError:  # pragma: no cover - enum kept in step with issues
                continue
            severity = DEFAULT_FRAME_SEVERITIES.get(code, QualitySeverity.WARNING)
            rows.append(
                {
                    "ingestion_run_id": telemetry_file.ingestion_run_id,
                    "field_definition_id": None,
                    "rule_code": rule_code,
                    "scope": QualityRuleScope.FRAME,
                    "severity": severity,
                    "entity": None,
                    "field_name": None,
                    "field_occurrence": None,
                    "source_row_number": None,
                    "event_time": None,
                    "entity_reference": reconstruction_version,
                    "charger_id": None,
                    "business_date": telemetry_file.business_date,
                    "raw_value": None,
                    "message": _finding_message(code, count),
                    "details": {
                        "occurrences": count,
                        "reconstruction_version": reconstruction_version,
                    },
                    "occurrence_count": count,
                    "issue_hash": _finding_hash(telemetry_file.id, code, reconstruction_version),
                    "detected_at": dt.datetime.now(dt.UTC),
                }
            )

        # Frame findings are FRAME-scope; replacing only those leaves the file's
        # Phase 1A/1B findings untouched.
        await self._quality.replace_scoped_issues(telemetry_file.id, QualityRuleScope.FRAME, rows)
        return len(rows)


def _finding_message(code: str, count: int) -> str:
    readable = code.replace("_", " ").lower()
    return f"{count} frame(s) with {readable} during source frame reconstruction."


def _finding_hash(telemetry_file_id: UUID, code: str, version: str) -> str:
    return hashlib.sha256(
        "\x1f".join(("FRAME", str(telemetry_file_id), code, version)).encode("utf-8")
    ).hexdigest()
