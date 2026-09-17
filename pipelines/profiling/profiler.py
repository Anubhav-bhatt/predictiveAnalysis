"""File profiler (Phase 1A section 10, Phase 1B section 24).

Design decisions worth stating plainly:

**Everything is read as text.**  Section 20 says field types are untrusted, and
section 13 says sentinels such as ``-150`` must be preserved, not interpreted.
Letting a CSV reader infer types would quietly turn ``-150`` into a temperature
and ``Not alarm`` into a null.  So the file loads as all-Utf8 and every numeric
interpretation is an explicit, separately-counted cast.

**One load, one context.**  The file is read once and every statistic is derived
from that single frame with vectorised expressions (section 38).  No rule
re-opens the file.

**Duplicates are measured, never resolved.**  Phase 1A/1B only classify; frame
reconstruction is Phase 1D.  Critically, the profiler distinguishes a *replay*
(same logical key, identical values) from a *conflict* (same logical key,
different values) - the latter must never be silently dropped.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from backend.app.models.enums import VariabilityClass
from pipelines.profiling.column_roles import ColumnRole, RoleResolution, resolve_roles
from pipelines.profiling.event_time import TimestampAnalysis, analyse_event_time
from pipelines.profiling.header_parser import RawHeaderParseResult, parse_header

__all__ = [
    "DuplicateAnalysis",
    "FieldProfile",
    "FileProfile",
    "ProfilerError",
    "profile_file",
]

#: Distinct values retained for a low-cardinality (state-like) field.
MAX_OBSERVED_VALUES = 50
#: Example values retained for every field.
MAX_EXAMPLE_VALUES = 5
#: A column is treated as numeric when at least this share of its non-null
#: values cast cleanly to a float.
NUMERIC_DOMINANCE_THRESHOLD = 0.95


class ProfilerError(RuntimeError):
    """The file could not be profiled; the orchestrator quarantines it."""


@dataclass(frozen=True, slots=True)
class FieldProfile:
    """Per-field observations *for this file only* (section 29)."""

    position: int
    source_name: str
    source_occurrence: int
    canonical_name: str

    null_count: int
    null_percentage: float
    unique_count: int
    variability: VariabilityClass

    min_value: str | None = None
    max_value: str | None = None
    numeric_valid_count: int | None = None
    mean_value: float | None = None
    median_value: float | None = None
    stddev_value: float | None = None

    example_values: tuple[str, ...] = ()
    #: Populated only for low-cardinality fields, where an exhaustive value list
    #: is meaningful.  None means "too many distinct values to enumerate".
    observed_values: tuple[str, ...] | None = None
    sentinel_hits: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_numeric(self) -> bool:
        return self.numeric_valid_count is not None and self.numeric_valid_count > 0

    @property
    def sentinel_hit_count(self) -> int:
        return sum(self.sentinel_hits.values())


@dataclass(frozen=True, slots=True)
class DuplicateAnalysis:
    """Duplicate/replay classification (Phase 1A section 12)."""

    #: Redundant copies: total rows minus distinct rows.
    exact_duplicate_rows: int
    #: Rows belonging to any group of byte-identical rows.
    rows_participating_in_duplicates: int

    #: Distinct (event time, connector, SMR) keys present.
    logical_key_groups: int
    #: Keys occupied by more than one raw row.
    logical_collision_groups: int
    #: Keys whose rows are *not* all identical - genuinely differing
    #: observations that Phase 1D must reconcile rather than discard.
    conflicting_logical_groups: int
    max_rows_per_logical_key: int

    #: rows-per-timestamp -> how many timestamps had that many rows.
    rows_per_timestamp: Mapping[int, int] = field(default_factory=dict)
    #: Timestamps carrying more than the expected frame size.
    duplicate_timestamp_count: int = 0

    @property
    def has_collisions(self) -> bool:
        return self.logical_collision_groups > 0


@dataclass(frozen=True, slots=True)
class FileProfile:
    """Structured profiling result.  Never just console text (section 10)."""

    row_count: int
    column_count: int
    header: RawHeaderParseResult
    roles: RoleResolution
    timestamps: TimestampAnalysis
    duplicates: DuplicateAnalysis
    fields: tuple[FieldProfile, ...]

    charger_ids: Mapping[str, int] = field(default_factory=dict)
    ocpp_ids: Mapping[str, int] = field(default_factory=dict)
    connectors: Mapping[str, int] = field(default_factory=dict)
    smrs: Mapping[str, int] = field(default_factory=dict)
    session_ids: Mapping[str, int] = field(default_factory=dict)

    profiling_duration_ms: int = 0

    # -- convenience views used by reporting and the quality engine ---------

    @property
    def empty_fields(self) -> tuple[FieldProfile, ...]:
        return tuple(f for f in self.fields if f.variability is VariabilityClass.ALL_NULL_IN_SAMPLE)

    @property
    def constant_fields(self) -> tuple[FieldProfile, ...]:
        return tuple(f for f in self.fields if f.variability is VariabilityClass.CONSTANT_IN_SAMPLE)

    @property
    def varying_fields(self) -> tuple[FieldProfile, ...]:
        return tuple(f for f in self.fields if f.variability is VariabilityClass.VARIABLE_IN_SAMPLE)

    @property
    def connector_count(self) -> int:
        return len(self.connectors)

    @property
    def smr_count(self) -> int:
        return len(self.smrs)

    def field_by_canonical(self, name: str) -> FieldProfile | None:
        for item in self.fields:
            if item.canonical_name == name:
                return item
        return None


def _load_frame(path: Path, canonical_names: Sequence[str]) -> pl.DataFrame:
    """Read the CSV as pure text using our own column names.

    ``has_header=False`` plus ``skip_rows=1`` means the reader never sees the
    duplicated header at all - our parser already assigned unique canonical
    names, so neither Polars' duplicate-column error nor Pandas' ``.1`` mangling
    can occur.
    """
    try:
        return pl.read_csv(
            path,
            has_header=False,
            skip_rows=1,
            new_columns=list(canonical_names),
            infer_schema_length=0,  # every column stays Utf8
            empty_string_is_null=True,  # an empty field is absent, not ""
            low_memory=False,
            encoding="utf8-lossy",  # untrusted bytes must not abort the read
        )
    except Exception as exc:  # noqa: BLE001 - any reader failure quarantines
        raise ProfilerError(f"Unable to read CSV content: {exc}") from exc


def _value_counts(frame: pl.DataFrame, column: str | None, *, limit: int = 200) -> dict[str, int]:
    """Distinct values and their frequencies for an identifier-like column."""
    if column is None or column not in frame.columns:
        return {}
    counts = (
        frame.select(pl.col(column))
        .drop_nulls()
        .group_by(column)
        .len()
        .sort("len", descending=True)
        .head(limit)
    )
    return {str(row[0]): int(row[1]) for row in counts.iter_rows()}


def _profile_fields(
    frame: pl.DataFrame,
    header: RawHeaderParseResult,
    sentinel_values: Sequence[str],
) -> tuple[FieldProfile, ...]:
    """Per-field statistics, computed with whole-frame expressions."""
    row_count = frame.height
    columns = frame.columns

    nulls = frame.null_count().row(0)

    # One reshape to long form gives distinct counts, value frequencies and
    # sentinel hits for all 449 columns together.  Doing this per column instead
    # costs one Polars call per field, which dominated total runtime on a
    # real-sized file (section 38).
    value_counts = (
        frame.with_row_index("__row")
        .unpivot(index="__row", variable_name="__col", value_name="__val")
        .drop_nulls("__val")
        .group_by("__col", "__val")
        .agg(pl.len().alias("__n"))
    )

    per_column_values: dict[str, list[tuple[str, int]]] = {}
    unique_counts: dict[str, int] = {}
    sentinel_lookup: dict[str, dict[str, int]] = {}
    sentinel_set = set(sentinel_values)

    for col, val, count in value_counts.sort("__n", descending=True).iter_rows():
        unique_counts[col] = unique_counts.get(col, 0) + 1
        bucket = per_column_values.setdefault(col, [])
        if len(bucket) < MAX_OBSERVED_VALUES:
            bucket.append((str(val), int(count)))
        if val in sentinel_set:
            sentinel_lookup.setdefault(col, {})[str(val)] = int(count)

    # Numeric interpretation is explicit and separately counted, never implied.
    numeric = frame.select(pl.all().cast(pl.Float64, strict=False))
    numeric_valid = numeric.select(pl.all().count()).row(0)
    numeric_min = numeric.select(pl.all().min()).row(0)
    numeric_max = numeric.select(pl.all().max()).row(0)
    numeric_mean = numeric.select(pl.all().mean()).row(0)
    numeric_median = numeric.select(pl.all().median()).row(0)
    numeric_std = numeric.select(pl.all().std()).row(0)

    text_min = frame.select(pl.all().min()).row(0)
    text_max = frame.select(pl.all().max()).row(0)

    profiles: list[FieldProfile] = []
    for index, header_field in enumerate(header.fields):
        column = columns[index]
        null_count = int(nulls[index])
        unique_count = unique_counts.get(column, 0)
        non_null = row_count - null_count

        if null_count >= row_count:
            variability = VariabilityClass.ALL_NULL_IN_SAMPLE
        elif unique_count <= 1:
            variability = VariabilityClass.CONSTANT_IN_SAMPLE
        else:
            variability = VariabilityClass.VARIABLE_IN_SAMPLE

        valid_numeric = int(numeric_valid[index] or 0)
        treat_numeric = non_null > 0 and (valid_numeric / non_null) >= NUMERIC_DOMINANCE_THRESHOLD

        # Values are ordered by frequency, so examples are representative rather
        # than merely whichever rows happened to come first.
        ranked = per_column_values.get(column, [])
        examples = tuple(value for value, _ in ranked[:MAX_EXAMPLE_VALUES])
        observed: tuple[str, ...] | None = None
        if 0 < unique_count <= MAX_OBSERVED_VALUES:
            observed = tuple(value for value, _ in ranked)

        hits = sentinel_lookup.get(column, {})

        profiles.append(
            FieldProfile(
                position=header_field.position,
                source_name=header_field.source_name,
                source_occurrence=header_field.source_occurrence,
                canonical_name=header_field.canonical_name,
                null_count=null_count,
                null_percentage=round((null_count / row_count * 100) if row_count else 0.0, 3),
                unique_count=unique_count,
                variability=variability,
                min_value=(_fmt(numeric_min[index]) if treat_numeric else _fmt(text_min[index])),
                max_value=(_fmt(numeric_max[index]) if treat_numeric else _fmt(text_max[index])),
                numeric_valid_count=valid_numeric if treat_numeric else None,
                mean_value=_as_float(numeric_mean[index]) if treat_numeric else None,
                median_value=_as_float(numeric_median[index]) if treat_numeric else None,
                stddev_value=_as_float(numeric_std[index]) if treat_numeric else None,
                example_values=examples,
                observed_values=observed,
                sentinel_hits=hits,
            )
        )
    return tuple(profiles)


def _fmt(value: object) -> str | None:
    return None if value is None else str(value)


def _as_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _analyse_duplicates(frame: pl.DataFrame, roles: RoleResolution) -> DuplicateAnalysis:
    """Classify exact duplicates, logical collisions and frame-size anomalies."""
    row_count = frame.height
    if row_count == 0:
        return DuplicateAnalysis(0, 0, 0, 0, 0, 0)

    distinct_rows = frame.unique().height
    exact_duplicates = row_count - distinct_rows
    participating = int(frame.is_duplicated().sum())

    charger_col = roles.canonical(ColumnRole.CHARGER_ID)
    event_col = roles.canonical(ColumnRole.EVENT_TIME)
    connector_col = roles.canonical(ColumnRole.CONNECTOR)
    rectifier_col = roles.canonical(ColumnRole.RECTIFIER)
    smr_col = roles.canonical(ColumnRole.SMR)

    key_columns = [
        c
        for c in (charger_col, event_col, connector_col, rectifier_col, smr_col)
        if c and c in frame.columns
    ]
    if not key_columns:
        return DuplicateAnalysis(
            exact_duplicate_rows=exact_duplicates,
            rows_participating_in_duplicates=participating,
            logical_key_groups=0,
            logical_collision_groups=0,
            conflicting_logical_groups=0,
            max_rows_per_logical_key=0,
        )

    grouped = frame.group_by(key_columns).len()
    logical_groups = grouped.height
    collisions = int(grouped.filter(pl.col("len") > 1).height)
    max_per_key = int(grouped.select(pl.col("len").max()).item() or 0)

    # After removing byte-identical rows, any key still holding >1 row holds
    # genuinely *different* observations.  That is the population Phase 1D must
    # reconcile, and the reason duplicates cannot simply be dropped.
    conflicting = int(frame.unique().group_by(key_columns).len().filter(pl.col("len") > 1).height)

    rows_per_timestamp: dict[int, int] = {}
    duplicate_timestamps = 0
    if event_col and event_col in frame.columns:
        per_ts = frame.group_by(event_col).agg(pl.len().alias("rows"))
        distribution = per_ts.group_by("rows").agg(pl.len().alias("timestamps")).sort("rows")
        rows_per_timestamp = {int(r[0]): int(r[1]) for r in distribution.iter_rows()}
        if rows_per_timestamp:
            modal_frame_size = max(rows_per_timestamp.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            duplicate_timestamps = int(per_ts.filter(pl.col("rows") > modal_frame_size).height)

    return DuplicateAnalysis(
        exact_duplicate_rows=exact_duplicates,
        rows_participating_in_duplicates=participating,
        logical_key_groups=logical_groups,
        logical_collision_groups=collisions,
        conflicting_logical_groups=conflicting,
        max_rows_per_logical_key=max_per_key,
        rows_per_timestamp=rows_per_timestamp,
        duplicate_timestamp_count=duplicate_timestamps,
    )


def profile_file(
    path: Path,
    *,
    timestamp_formats: Sequence[str],
    source_timezone: str = "UTC",
    sentinel_values: Sequence[str] = (),
    header: RawHeaderParseResult | None = None,
) -> FileProfile:
    """Profile one telemetry file end to end.

    ``header`` may be supplied when the caller has already parsed it, so the
    header is never read twice.
    """
    started = time.perf_counter()

    header = header or parse_header(path)
    frame = _load_frame(path, header.canonical_names)

    roles = resolve_roles(header.canonical_names, header.source_names)

    event_column = roles.canonical(ColumnRole.EVENT_TIME)
    if event_column and event_column in frame.columns:
        timestamps = analyse_event_time(
            frame.get_column(event_column),
            column=event_column,
            formats=list(timestamp_formats),
            source_timezone=source_timezone,
        )
    else:
        timestamps = TimestampAnalysis(
            column=event_column or "<unresolved>",
            chosen_format=None,
            total_values=frame.height,
            null_count=frame.height,
            parsed_count=0,
            failed_count=0,
            unique_count=0,
            event_time_min=None,
            event_time_max=None,
            median_interval_seconds=None,
            p95_interval_seconds=None,
            min_interval_seconds=None,
            max_interval_seconds=None,
            source_timezone=source_timezone,
        )

    fields = _profile_fields(frame, header, sentinel_values)
    duplicates = _analyse_duplicates(frame, roles)

    duration_ms = int((time.perf_counter() - started) * 1000)

    return FileProfile(
        row_count=frame.height,
        column_count=frame.width,
        header=header,
        roles=roles,
        timestamps=timestamps,
        duplicates=duplicates,
        fields=fields,
        charger_ids=_value_counts(frame, roles.canonical(ColumnRole.CHARGER_ID)),
        ocpp_ids=_value_counts(frame, roles.canonical(ColumnRole.OCPP_ID)),
        connectors=_value_counts(frame, roles.canonical(ColumnRole.CONNECTOR)),
        smrs=_value_counts(frame, roles.canonical(ColumnRole.SMR)),
        session_ids=_value_counts(frame, roles.canonical(ColumnRole.SESSION_ID)),
        profiling_duration_ms=duration_ms,
    )
