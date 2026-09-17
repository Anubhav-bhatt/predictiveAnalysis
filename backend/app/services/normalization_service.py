"""Silver telemetry normalization service (Phase 6).

Governed by schema revision charger_status_v2.0.0 and PHASE6_NORMALIZATION_CONTRACT.md.
Transforms reconstructed source frames into typed, normalized Silver records
without losing, guessing, averaging, fabricating, or silently modifying telemetry.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger, log_context
from backend.app.db.base import utcnow
from backend.app.models.data_quality_issue import DataQualityIssue
from backend.app.models.enums import (
    FileStatus,
    QualityDimension,
    QualityIssueType,
    QualityRuleScope,
    QualitySeverity,
)
from backend.app.models.silver_telemetry import SilverNormalizationRun
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.repositories.frames import FrameRepository
from backend.app.repositories.ingestion import TelemetryFileRepository
from backend.app.repositories.quality import QualityRepository
from backend.app.repositories.silver import SilverRepository
from pipelines.ingestion.state_machine import assert_transition_allowed
from pipelines.normalization.normalizers import create_silver_records
from pipelines.normalization.payload_resolver import (
    CanonicalFramePayloadResolver,
)
from pipelines.persistence.storage import RawObjectStorage
from pipelines.profiling.header_parser import parse_header
from pipelines.validation.dictionary import DictionaryRegistry

__all__ = ["NormalizationResult", "NormalizationService"]

logger = get_logger(__name__)


@dataclass(slots=True)
class NormalizationResult:
    """Outcome of normalizing one telemetry file."""

    telemetry_file_id: UUID
    run: SilverNormalizationRun | None
    frames_normalized: int = 0
    records_created: int = 0
    sentinels_masked: int = 0
    conflicts_detected: int = 0
    skipped_reason: str | None = None


class NormalizationService:
    """Orchestrates Silver normalization, provenance tracking, and idempotency."""

    def __init__(
        self,
        *,
        silver_repo: SilverRepository,
        frame_repo: FrameRepository,
        file_repo: TelemetryFileRepository,
        quality_repo: QualityRepository,
        storage: RawObjectStorage,
        dictionary: DictionaryRegistry,
        settings: Settings,
    ) -> None:
        self._silver = silver_repo
        self._frames = frame_repo
        self._files = file_repo
        self._quality = quality_repo
        self._storage = storage
        self._dictionary = dictionary
        self._settings = settings
        self._resolver = CanonicalFramePayloadResolver(dictionary)

    async def normalize_file(
        self,
        telemetry_file: TelemetryFile,
        *,
        advance_lifecycle: bool = True,
    ) -> NormalizationResult:
        """Normalize canonical reconstructed frames of a file into typed Silver records."""
        result = NormalizationResult(
            telemetry_file_id=telemetry_file.id,
            run=None,
        )

        with log_context(telemetry_file_id=telemetry_file.id):
            if telemetry_file.storage_reference is None:
                result.skipped_reason = "file has no stored object to normalize from"
                return result

            # Transition to NORMALIZING
            if advance_lifecycle:
                self._transition(telemetry_file, FileStatus.NORMALIZING)

            run = await self._silver.create_normalization_run(
                file_id=telemetry_file.id,
                status="NORMALIZING",
            )
            result.run = run

            # Load canonical frames for this file
            frames = await self._frames.get_canonical_frames_for_file(telemetry_file.id)
            run.frames_input = len(frames)

            if not frames:
                run.status = "COMPLETED"
                run.completed_at = utcnow()
                if advance_lifecycle:
                    self._transition(telemetry_file, FileStatus.NORMALIZED)
                return result

            frame_ids = [f.id for f in frames]

            # Idempotently remove any prior Silver records and provenance for these frames
            await self._silver.delete_for_frames(frame_ids)

            # Read raw Bronze rows indexed by 1-based source row number
            raw_rows_by_line: dict[int, dict[str, str]] = {}
            with self._storage.materialize_local(telemetry_file.storage_reference) as path:
                header_res = parse_header(path)
                headers = list(header_res.source_names)
                with path.open(encoding="utf-8", errors="replace") as f:  # noqa: ASYNC230
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header line
                    for line_idx, row in enumerate(reader, 1):
                        row_dict: dict[str, str] = {}
                        for col_idx, val in enumerate(row):
                            if col_idx < len(headers):
                                row_dict[headers[col_idx]] = val
                        raw_rows_by_line[line_idx] = row_dict

            total_records: list[Any] = []
            total_provenance: list[Any] = []
            counts_by_table: dict[str, int] = {}
            conflicts_count = 0
            sentinels_count = 0
            frames_with_warnings = 0

            for frame in frames:
                # Find contributing row numbers from frame_rows
                contributing_row_numbers = [
                    fr.source_row_number
                    for fr in frame.frame_rows
                    if fr.telemetry_file_id == telemetry_file.id
                ]
                if (
                    not contributing_row_numbers
                    and frame.source_order_min
                    and frame.source_order_max
                ):
                    contributing_row_numbers = list(
                        range(frame.source_order_min, frame.source_order_max + 1)
                    )

                contributing_rows = [
                    raw_rows_by_line[num]
                    for num in contributing_row_numbers
                    if num in raw_rows_by_line
                ]

                # Resolve frame payload across contributing rows
                payload = self._resolver.resolve_frame(
                    frame_id=frame.id,
                    charger_id=frame.charger_id,
                    event_time=frame.event_time,
                    frame_sequence=frame.frame_sequence,
                    raw_rows=contributing_rows,
                    headers=headers,
                    source_file_id=telemetry_file.id,
                )

                if payload.conflicts:
                    conflicts_count += len(payload.conflicts)
                    frames_with_warnings += 1
                    for conflict in payload.conflicts:
                        issue_type = QualityIssueType.REPEATED_FIELD_CONFLICT
                        if "CONNECTOR" in conflict.get("type", ""):
                            issue_type = QualityIssueType.CONNECTOR_FIELD_CONFLICT
                        issue = DataQualityIssue(
                            telemetry_file_id=telemetry_file.id,
                            scope=QualityRuleScope.FRAME,
                            rule_code=issue_type.value,
                            dimension=QualityDimension.VALIDITY,
                            severity=QualitySeverity.WARNING,
                            message=(
                                f"Field {conflict.get('field')} at pos {conflict.get('position')} "
                                f"conflicted with values {conflict.get('values')}"
                            ),
                            details=conflict,
                        )
                        self._silver.session.add(issue)

                if payload.sentinels_masked:
                    sentinels_count += len(payload.sentinels_masked)

                # Build typed Silver models and provenance
                silver_models, provenance = create_silver_records(
                    payload,
                    source_file_id=telemetry_file.id,
                )

                for model in silver_models:
                    tbl = getattr(model, "__tablename__", "unknown")
                    counts_by_table[tbl] = counts_by_table.get(tbl, 0) + 1

                total_records.extend(silver_models)
                total_provenance.extend(provenance)

            # Bulk persist
            await self._silver.insert_records(total_records)
            await self._silver.insert_provenance(total_provenance)

            # Update run metrics
            run.frames_normalized = len(frames)
            run.frames_with_warnings = frames_with_warnings
            run.conflicts_detected_count = conflicts_count
            run.sentinels_masked_count = sentinels_count
            run.records_created_by_table = counts_by_table
            run.status = "COMPLETED"
            run.completed_at = utcnow()

            result.frames_normalized = len(frames)
            result.records_created = len(total_records)
            result.sentinels_masked = sentinels_count
            result.conflicts_detected = conflicts_count

            # Lifecycle progression
            if advance_lifecycle:
                target_status = (
                    FileStatus.NORMALIZED_WITH_WARNINGS
                    if frames_with_warnings > 0
                    else FileStatus.NORMALIZED
                )
                self._transition(telemetry_file, target_status)

            return result

    def _transition(self, telemetry_file: TelemetryFile, target: FileStatus) -> None:
        assert_transition_allowed(telemetry_file.status, target)
        telemetry_file.status = target
