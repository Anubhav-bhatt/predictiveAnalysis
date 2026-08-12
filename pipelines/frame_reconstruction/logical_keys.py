"""Logical key construction (Phase 1D sections 4, 5, 8).

Row identity comes from the Phase 1B schema registry, not from raw CSV names
scattered through the algorithm: :mod:`pipelines.profiling.column_roles` already
resolves which of the 449 columns carries the event time, charger id, connector and
SMR, and this module consumes that resolution.

Two properties matter downstream:

**Source order is preserved.** ``source_row_number`` is captured from the file's
original row order before any sort, and ``occurrence_index`` is assigned within a
logical key in that order. Nothing keys off a DataFrame index, which would change
meaning the moment the frame is sorted.

**Unidentifiable rows survive.** A row whose connector or SMR cannot be resolved is
marked unassigned and carried through, never silently dropped (section 22).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from pipelines.frame_reconstruction.canonical_serializer import CanonicalSerializer
from pipelines.frame_reconstruction.models import (
    UNASSIGNED_POSITION,
    LogicalPosition,
    RawRowRef,
)
from pipelines.profiling.column_roles import ColumnRole, RoleResolution

__all__ = ["KeyedRows", "LogicalKeyBuilder", "SOURCE_ROW_COLUMN"]

#: Name of the synthetic column holding each row's original file position.
SOURCE_ROW_COLUMN = "__source_row_number"


@dataclass(frozen=True, slots=True)
class KeyedRows:
    """Raw rows with logical identity attached, in source order."""

    #: (charger_id, event_time) -> rows at that timestamp, source-ordered.
    by_timestamp: Mapping[tuple[str, dt.datetime], tuple[RawRowRef, ...]]
    #: Rows whose identity could not be resolved, by timestamp where known.
    unassigned_by_timestamp: Mapping[tuple[str, dt.datetime], tuple[RawRowRef, ...]]
    #: Rows with no usable event time at all - they cannot join any frame.
    undatable_rows: tuple[RawRowRef, ...]

    #: position -> number of distinct timestamp groups it appeared in. Feeds the
    #: observed-topology tier, which counts groups rather than rows so one
    #: anomalous timestamp cannot redefine topology.
    position_group_counts: Mapping[LogicalPosition, int]
    group_total: int

    observed_connectors: tuple[str, ...]
    observed_smrs: tuple[str, ...]

    #: Rows whose canonical text was byte-identical to an earlier row anywhere in
    #: the file. Counted for reporting; the rows are retained.
    exact_duplicate_row_count: int = 0

    @property
    def assigned_row_count(self) -> int:
        return sum(len(rows) for rows in self.by_timestamp.values())

    @property
    def unassigned_row_count(self) -> int:
        return sum(len(rows) for rows in self.unassigned_by_timestamp.values()) + len(
            self.undatable_rows
        )


class LogicalKeyBuilder:
    """Attaches logical identity and occurrence indexes to raw rows."""

    def __init__(
        self,
        *,
        roles: RoleResolution,
        serializer: CanonicalSerializer,
        charger_id_fallback: str | None = None,
    ) -> None:
        self._roles = roles
        self._serializer = serializer
        self._charger_fallback = charger_id_fallback

    def _column(self, role: ColumnRole) -> str | None:
        resolved = self._roles.get(role)
        return resolved.canonical_name if resolved else None

    def build(
        self,
        frame: pl.DataFrame,
        *,
        telemetry_file_id: object,
        event_times: Sequence[dt.datetime | None],
    ) -> KeyedRows:
        """Key every row of a profiled file.

        ``event_times`` is positionally aligned with ``frame`` and already parsed
        and timezone-normalised by the Phase 1A event-time analyser, so this module
        never re-parses timestamps or reinterprets the source timezone.
        """
        connector_col = self._column(ColumnRole.CONNECTOR)
        smr_col = self._column(ColumnRole.SMR)
        charger_col = self._column(ColumnRole.CHARGER_ID)

        field_names = list(frame.columns)
        # Vectorised extraction, then a single ordered pass. Polars does the bulk
        # column work; the per-row loop only assembles small value objects.
        columns = {name: frame.get_column(name).to_list() for name in field_names}

        connectors = columns.get(connector_col) if connector_col else None
        smrs = columns.get(smr_col) if smr_col else None
        chargers = columns.get(charger_col) if charger_col else None

        by_timestamp: dict[tuple[str, dt.datetime], list[RawRowRef]] = {}
        unassigned: dict[tuple[str, dt.datetime], list[RawRowRef]] = {}
        undatable: list[RawRowRef] = []

        # occurrence_index counts rows already seen for a logical key.
        occurrence_counter: dict[tuple[str, dt.datetime, LogicalPosition], int] = {}
        positions_per_group: dict[tuple[str, dt.datetime], set[LogicalPosition]] = {}
        seen_row_fingerprints: set[str] = set()
        exact_duplicates = 0

        observed_connectors: set[str] = set()
        observed_smrs: set[str] = set()

        row_values = [columns[name] for name in field_names]

        for index in range(frame.height):
            values = [column[index] for column in row_values]
            fingerprint = self._serializer.row_fingerprint(field_names, values)
            if fingerprint in seen_row_fingerprints:
                exact_duplicates += 1
            else:
                seen_row_fingerprints.add(fingerprint)

            charger_id = _clean(chargers[index]) if chargers else ""
            if not charger_id:
                charger_id = self._charger_fallback or ""

            connector_id = _clean(connectors[index]) if connectors else ""
            smr_id = _clean(smrs[index]) if smrs else ""
            if connector_id:
                observed_connectors.add(connector_id)
            if smr_id:
                observed_smrs.add(smr_id)

            position = (
                LogicalPosition(connector_id=connector_id, smr_id=smr_id)
                if connector_id and smr_id
                else UNASSIGNED_POSITION
            )
            is_assigned = position.is_assigned and bool(charger_id)

            event_time = event_times[index] if index < len(event_times) else None
            if event_time is None:
                undatable.append(
                    RawRowRef(
                        telemetry_file_id=telemetry_file_id,
                        source_row_number=index,
                        position=position,
                        occurrence_index=0,
                        row_fingerprint=fingerprint,
                        unassigned=True,
                    )
                )
                continue

            group_key = (charger_id, event_time)

            if not is_assigned:
                ref = RawRowRef(
                    telemetry_file_id=telemetry_file_id,
                    source_row_number=index,
                    position=position,
                    occurrence_index=0,
                    row_fingerprint=fingerprint,
                    unassigned=True,
                )
                unassigned.setdefault(group_key, []).append(ref)
                continue

            counter_key = (charger_id, event_time, position)
            occurrence = occurrence_counter.get(counter_key, 0)
            occurrence_counter[counter_key] = occurrence + 1

            by_timestamp.setdefault(group_key, []).append(
                RawRowRef(
                    telemetry_file_id=telemetry_file_id,
                    source_row_number=index,
                    position=position,
                    occurrence_index=occurrence,
                    row_fingerprint=fingerprint,
                )
            )
            positions_per_group.setdefault(group_key, set()).add(position)

        position_group_counts: dict[LogicalPosition, int] = {}
        for positions in positions_per_group.values():
            for position in positions:
                position_group_counts[position] = position_group_counts.get(position, 0) + 1

        return KeyedRows(
            by_timestamp={key: tuple(rows) for key, rows in by_timestamp.items()},
            unassigned_by_timestamp={key: tuple(rows) for key, rows in unassigned.items()},
            undatable_rows=tuple(undatable),
            position_group_counts=position_group_counts,
            group_total=len(positions_per_group),
            observed_connectors=tuple(sorted(observed_connectors)),
            observed_smrs=tuple(sorted(observed_smrs)),
            exact_duplicate_row_count=exact_duplicates,
        )


def _clean(value: object) -> str:
    """Normalise an identity field to comparable text.

    A numeric-looking identity is rendered without its decimal tail, so a source
    that writes ``1`` in one row and ``1.0`` in another still resolves to the same
    connector rather than two phantom ones.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return text[:-2]
    return text
