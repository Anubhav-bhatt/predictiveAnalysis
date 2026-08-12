"""Source-frame persistence (Phase 1D section 44).

Repositories build SQL and nothing else - no frame-building logic lives here.

Idempotency is delete-then-bulk-insert scoped to
``(telemetry_file, reconstruction_version)``. Re-running the same immutable file
under the same algorithm version replaces exactly that file's frames and leaves
every other file's alone; running a *new* version is additive, because the version
is part of frame identity.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from backend.app.models.enums import DuplicateClassification, FrameStatus
from backend.app.models.telemetry_frame import (
    TelemetryFrameRow,
    TelemetryFrameSource,
    TelemetrySourceFrame,
)
from backend.app.repositories.base import Page, PageRequest, Repository, paginate

__all__ = ["FrameRepository"]

#: Classifications that Phase 1E consumes by default.
CANONICAL_CLASSIFICATIONS = (
    DuplicateClassification.UNIQUE,
    DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
)


class FrameRepository(Repository):
    # -- write path --------------------------------------------------------

    async def delete_for_file(
        self, telemetry_file_id: UUID, *, reconstruction_version: str
    ) -> int:
        """Remove this file's frames for one algorithm version.

        A frame can be sourced from several files, so "frames belonging to this
        file" is resolved through ``telemetry_frame_source`` rather than assumed.
        Only frames whose *sole* source is this file are deleted; a frame shared
        with another file loses just this file's source and row mappings, so
        reconstructing one file never destroys another file's provenance.
        """
        frame_ids = (
            sa.select(TelemetryFrameSource.frame_id)
            .join(
                TelemetrySourceFrame,
                TelemetrySourceFrame.id == TelemetryFrameSource.frame_id,
            )
            .where(
                TelemetryFrameSource.telemetry_file_id == telemetry_file_id,
                TelemetrySourceFrame.reconstruction_version == reconstruction_version,
            )
        )
        candidate_ids = [row[0] for row in (await self.session.execute(frame_ids)).all()]
        if not candidate_ids:
            return 0

        # Frames still referenced by a *different* file must survive.
        shared = await self.session.execute(
            sa.select(TelemetryFrameSource.frame_id)
            .where(
                TelemetryFrameSource.frame_id.in_(candidate_ids),
                TelemetryFrameSource.telemetry_file_id != telemetry_file_id,
            )
            .distinct()
        )
        shared_ids = {row[0] for row in shared.all()}
        exclusive_ids = [fid for fid in candidate_ids if fid not in shared_ids]

        # Drop this file's contribution to shared frames.
        await self.session.execute(
            sa.delete(TelemetryFrameRow).where(
                TelemetryFrameRow.frame_id.in_(candidate_ids),
                TelemetryFrameRow.telemetry_file_id == telemetry_file_id,
            )
        )
        await self.session.execute(
            sa.delete(TelemetryFrameSource).where(
                TelemetryFrameSource.frame_id.in_(candidate_ids),
                TelemetryFrameSource.telemetry_file_id == telemetry_file_id,
            )
        )

        if exclusive_ids:
            # Clear replay pointers first: a SET NULL foreign key would otherwise
            # leave rows referencing a frame that is about to disappear.
            await self.session.execute(
                sa.update(TelemetrySourceFrame)
                .where(TelemetrySourceFrame.replay_of_frame_id.in_(exclusive_ids))
                .values(replay_of_frame_id=None)
            )
            await self.session.execute(
                sa.delete(TelemetrySourceFrame).where(
                    TelemetrySourceFrame.id.in_(exclusive_ids)
                )
            )
        return len(exclusive_ids)

    async def insert_frames(self, rows: Sequence[dict[str, Any]]) -> None:
        """Bulk-insert frames. Every dict must carry an identical key set."""
        if rows:
            await self.session.execute(sa.insert(TelemetrySourceFrame), list(rows))

    async def insert_sources(self, rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            await self.session.execute(
                sa.insert(TelemetryFrameSource),
                [{**row, "id": uuid4()} for row in rows],
            )

    async def insert_frame_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            await self.session.execute(
                sa.insert(TelemetryFrameRow),
                [{**row, "id": uuid4()} for row in rows],
            )

    async def set_replay_targets(self, mapping: Sequence[tuple[UUID, UUID]]) -> None:
        """Point replay frames at their canonical frame.

        Applied after insertion because a replay's target is another row in the
        same batch, so the id is only known once the batch exists.
        """
        for frame_id, target_id in mapping:
            await self.session.execute(
                sa.update(TelemetrySourceFrame)
                .where(TelemetrySourceFrame.id == frame_id)
                .values(replay_of_frame_id=target_id)
            )

    # -- read path ---------------------------------------------------------

    async def get(self, frame_id: UUID, *, with_relations: bool = True) -> (
        TelemetrySourceFrame | None
    ):
        stmt = sa.select(TelemetrySourceFrame).where(TelemetrySourceFrame.id == frame_id)
        if with_relations:
            stmt = stmt.options(
                selectinload(TelemetrySourceFrame.sources).selectinload(
                    TelemetryFrameSource.telemetry_file
                ),
                selectinload(TelemetrySourceFrame.frame_rows),
            )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_charger(
        self,
        request: PageRequest,
        *,
        charger_id: str,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        frame_status: FrameStatus | None = None,
        duplicate_classification: DuplicateClassification | None = None,
        canonical_only: bool = False,
        reconstruction_version: str | None = None,
    ) -> Page[TelemetrySourceFrame]:
        stmt = (
            sa.select(TelemetrySourceFrame)
            .where(TelemetrySourceFrame.charger_id == charger_id)
            .order_by(
                TelemetrySourceFrame.event_time,
                TelemetrySourceFrame.frame_sequence,
            )
        )
        if date_from is not None:
            stmt = stmt.where(TelemetrySourceFrame.business_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(TelemetrySourceFrame.business_date <= date_to)
        if frame_status is not None:
            stmt = stmt.where(TelemetrySourceFrame.frame_status == frame_status)
        if duplicate_classification is not None:
            stmt = stmt.where(
                TelemetrySourceFrame.duplicate_classification == duplicate_classification
            )
        if canonical_only:
            stmt = stmt.where(
                TelemetrySourceFrame.duplicate_classification.in_(
                    CANONICAL_CLASSIFICATIONS
                )
            )
        if reconstruction_version is not None:
            stmt = stmt.where(
                TelemetrySourceFrame.reconstruction_version == reconstruction_version
            )
        return await paginate(self.session, stmt, request)

    async def frames_at(
        self, charger_id: str, event_time: dt.datetime
    ) -> Sequence[TelemetrySourceFrame]:
        """Every frame at one event timestamp - the collision explorer's query."""
        stmt = (
            sa.select(TelemetrySourceFrame)
            .where(
                TelemetrySourceFrame.charger_id == charger_id,
                TelemetrySourceFrame.event_time == event_time,
            )
            .order_by(TelemetrySourceFrame.frame_sequence)
            .options(selectinload(TelemetrySourceFrame.frame_rows))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def file_summary(
        self, telemetry_file_id: UUID, *, reconstruction_version: str | None = None
    ) -> dict[str, Any]:
        """Reconstruction metrics for one file, aggregated in SQL (section 45)."""
        joined = sa.select(
            TelemetrySourceFrame.frame_status,
            TelemetrySourceFrame.duplicate_classification,
            TelemetrySourceFrame.event_time,
            TelemetrySourceFrame.expected_position_count,
        ).join(
            TelemetryFrameSource,
            TelemetryFrameSource.frame_id == TelemetrySourceFrame.id,
        ).where(TelemetryFrameSource.telemetry_file_id == telemetry_file_id)
        if reconstruction_version is not None:
            joined = joined.where(
                TelemetrySourceFrame.reconstruction_version == reconstruction_version
            )

        rows = (await self.session.execute(joined)).all()

        status_counts = dict.fromkeys((s.value for s in FrameStatus), 0)
        classification_counts = dict.fromkeys(
            (c.value for c in DuplicateClassification), 0
        )
        collision_times: dict[dt.datetime, int] = {}
        expected_positions = 0

        for status, classification, event_time, expected in rows:
            status_counts[status.value] += 1
            classification_counts[classification.value] += 1
            expected_positions = max(expected_positions, int(expected or 0))
            if classification in CANONICAL_CLASSIFICATIONS:
                collision_times[event_time] = collision_times.get(event_time, 0) + 1

        canonical = sum(
            classification_counts[c.value] for c in CANONICAL_CLASSIFICATIONS
        )
        unassigned = await self.session.execute(
            sa.select(sa.func.count())
            .select_from(TelemetryFrameRow)
            .where(
                TelemetryFrameRow.telemetry_file_id == telemetry_file_id,
                TelemetryFrameRow.unassigned.is_(True),
            )
        )

        return {
            "frames_reconstructed": len(rows),
            "expected_positions_per_frame": expected_positions,
            "complete_frames": status_counts[FrameStatus.COMPLETE.value],
            "partial_frames": status_counts[FrameStatus.PARTIAL.value],
            "severely_incomplete_frames": status_counts[
                FrameStatus.SEVERELY_INCOMPLETE.value
            ],
            "malformed_frames": status_counts[FrameStatus.MALFORMED.value],
            "ambiguous_frames": status_counts[FrameStatus.AMBIGUOUS.value],
            "canonical_frames": canonical,
            "full_replays": classification_counts[
                DuplicateClassification.FULL_FRAME_REPLAY.value
            ],
            "partial_replays": classification_counts[
                DuplicateClassification.PARTIAL_FRAME_REPLAY.value
            ],
            "same_timestamp_distinct_frames": classification_counts[
                DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME.value
            ],
            "collision_timestamps": sum(
                1 for count in collision_times.values() if count > 1
            ),
            "unique_timestamps": len({row[2] for row in rows}),
            "unassigned_rows": int(unassigned.scalar_one() or 0),
        }

    async def charger_day_summary(
        self, charger_id: str, business_date: dt.date
    ) -> dict[str, Any]:
        """Frame metrics for one charger-day (section 39).

        Complements Phase 1C coverage; it does not replace or alter it.
        """
        rows = await self.session.execute(
            sa.select(
                TelemetrySourceFrame.frame_status,
                TelemetrySourceFrame.duplicate_classification,
                TelemetrySourceFrame.event_time,
            ).where(
                TelemetrySourceFrame.charger_id == charger_id,
                TelemetrySourceFrame.business_date == business_date,
            )
        )
        canonical = replays = partial = ambiguous = total = 0
        collision_times: dict[dt.datetime, int] = {}

        for status, classification, event_time in rows.all():
            total += 1
            if classification in CANONICAL_CLASSIFICATIONS:
                canonical += 1
                collision_times[event_time] = collision_times.get(event_time, 0) + 1
            elif classification in {
                DuplicateClassification.FULL_FRAME_REPLAY,
                DuplicateClassification.PARTIAL_FRAME_REPLAY,
            }:
                replays += 1
            if status is FrameStatus.PARTIAL:
                partial += 1
            elif status is FrameStatus.AMBIGUOUS:
                ambiguous += 1

        return {
            "canonical_frame_count": canonical,
            "replay_frame_count": replays,
            "partial_frame_count": partial,
            "ambiguous_frame_count": ambiguous,
            "collision_timestamp_count": sum(
                1 for count in collision_times.values() if count > 1
            ),
            "frames_total": total,
        }

    async def collision_timestamps(
        self, charger_id: str, business_date: dt.date
    ) -> Sequence[tuple[dt.datetime, int]]:
        """Timestamps carrying more than one canonical frame (section 50)."""
        stmt = (
            sa.select(
                TelemetrySourceFrame.event_time,
                sa.func.count().label("frames"),
            )
            .where(
                TelemetrySourceFrame.charger_id == charger_id,
                TelemetrySourceFrame.business_date == business_date,
                TelemetrySourceFrame.duplicate_classification.in_(
                    CANONICAL_CLASSIFICATIONS
                ),
            )
            .group_by(TelemetrySourceFrame.event_time)
            .having(sa.func.count() > 1)
            .order_by(TelemetrySourceFrame.event_time)
        )
        return [(row[0], int(row[1])) for row in (await self.session.execute(stmt)).all()]

    async def replay_sources(self, frame_id: UUID) -> Sequence[TelemetrySourceFrame]:
        """Frames that replay the given canonical frame (section 52)."""
        stmt = (
            sa.select(TelemetrySourceFrame)
            .where(TelemetrySourceFrame.replay_of_frame_id == frame_id)
            .order_by(TelemetrySourceFrame.frame_sequence)
            .options(selectinload(TelemetrySourceFrame.sources))
        )
        return list((await self.session.execute(stmt)).scalars().all())
