"""Business-date derivation from event time (Phase 1C sections 8, 29, 45).

The two rules under test are the ones the known production sample violates most
usefully: the filename is never the business date, and one file is not
necessarily one business date.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.models.enums import FileDateSpan
from pipelines.ingestion.file_day import build_file_days, dominant_identifier
from pipelines.profiling.event_time import extract_filename_date
from pipelines.profiling.header_parser import parse_header
from pipelines.profiling.profiler import FileProfile, profile_file
from tests.fixtures.builders import FixtureSpec, build_telemetry_csv

TIMESTAMP_FORMATS = ["%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"]
SOURCE_TZ = "Asia/Kolkata"


def profile(path: Path) -> FileProfile:
    header = parse_header(path)
    return profile_file(
        path,
        timestamp_formats=TIMESTAMP_FORMATS,
        source_timezone=SOURCE_TZ,
        sentinel_values=["-150"],
        header=header,
    )


@pytest.fixture
def single_day_file(tmp_path: Path) -> Path:
    # Filename says 28 July; the telemetry inside is 27 July.
    path = tmp_path / "HYD12_28-07-2026.csv"
    build_telemetry_csv(path, FixtureSpec())
    return path


def test_business_date_comes_from_event_time_not_filename(single_day_file: Path) -> None:
    """Section 8/29: the filename is metadata only, and here it disagrees."""
    result = profile(single_day_file)
    days = build_file_days(result, charger_id="D82510560390014", source_timezone=SOURCE_TZ)

    assert len(days) == 1
    assert days[0].business_date == dt.date(2026, 7, 27)

    filename_date = extract_filename_date(single_day_file.name)
    assert filename_date == dt.date(2026, 7, 28)
    assert filename_date != days[0].business_date, "the mismatch must be detectable"


def test_filename_date_is_extracted_but_never_authoritative() -> None:
    assert extract_filename_date("HYD12_28-07-2026.csv") == dt.date(2026, 7, 28)
    assert extract_filename_date("charger_2026-07-28_daily.csv") == dt.date(2026, 7, 28)
    assert extract_filename_date("charger_20260728.csv") == dt.date(2026, 7, 28)
    assert extract_filename_date("no_date_here.csv") is None
    # An impossible date is rejected rather than coerced.
    assert extract_filename_date("file_99-99-2026.csv") is None


def test_unique_timestamps_drive_the_day_not_raw_rows(single_day_file: Path) -> None:
    """Section 11: the raw grain is many rows per timestamp."""
    result = profile(single_day_file)
    days = build_file_days(result, charger_id="D82510560390014", source_timezone=SOURCE_TZ)
    day = days[0]

    assert day.unique_timestamp_count == result.timestamps.unique_count
    assert day.row_count > day.unique_timestamp_count, "duplication is expected in the raw grain"
    assert len(day.event_second_offsets) == day.unique_timestamp_count


def test_offsets_round_trip_to_the_original_timestamps(single_day_file: Path) -> None:
    """Persisted offsets must reproduce the exact instants (section 24)."""
    result = profile(single_day_file)
    day = build_file_days(result, charger_id="D82510560390014", source_timezone=SOURCE_TZ)[0]

    restored = day.timestamps_utc()
    assert restored == sorted(result.timestamps.unique_timestamps)


def test_offsets_are_sorted_and_unique(single_day_file: Path) -> None:
    result = profile(single_day_file)
    day = build_file_days(result, charger_id="D82510560390014", source_timezone=SOURCE_TZ)[0]
    offsets = list(day.event_second_offsets)
    assert offsets == sorted(offsets)
    assert len(offsets) == len(set(offsets))
    assert all(0 <= value < 86_400 for value in offsets)


def test_cross_midnight_file_produces_two_business_dates(tmp_path: Path) -> None:
    """Section 8: one file is not necessarily one business date."""
    path = tmp_path / "HYD12_cross_midnight.csv"
    # Start at 23:00 local with a 2-minute cadence, running past midnight.
    build_telemetry_csv(
        path,
        FixtureSpec(
            start=dt.datetime(2026, 7, 27, 23, 0, 0),
            timestamp_count=60,
            interval_seconds=120,
            replay_timestamp_indexes=(),
            conflicting_timestamp_indexes=(),
        ),
    )
    result = profile(path)
    days = build_file_days(result, charger_id="D82510560390014", source_timezone=SOURCE_TZ)

    assert len(days) == 2
    assert [d.business_date for d in days] == [dt.date(2026, 7, 27), dt.date(2026, 7, 28)]
    assert result.timestamps.date_span is FileDateSpan.CROSS_MIDNIGHT

    # Every unique timestamp is attributed to exactly one date - none lost, none
    # double-counted.
    assert sum(d.unique_timestamp_count for d in days) == result.timestamps.unique_count

    for day in days:
        assert day.detail["multi_day_file"] is True
        assert day.detail["row_count_is_apportioned"] is True


def test_dominant_identifier_is_deterministic() -> None:
    assert dominant_identifier({"A": 5, "B": 2}) == "A"
    assert dominant_identifier({}) is None
    # Ties break on the sorted value, so the result never depends on dict order.
    assert dominant_identifier({"B": 3, "A": 3}) == "B"
    assert dominant_identifier({"A": 3, "B": 3}) == "B"


def test_no_timestamps_yields_no_days(single_day_file: Path) -> None:
    result = profile(single_day_file)
    empty = type(result.timestamps)(
        column="Event Time",
        chosen_format=None,
        total_values=0,
        null_count=0,
        parsed_count=0,
        failed_count=0,
        unique_count=0,
        event_time_min=None,
        event_time_max=None,
        median_interval_seconds=None,
        p95_interval_seconds=None,
        min_interval_seconds=None,
        max_interval_seconds=None,
    )
    stripped = replace(result, timestamps=empty)
    assert build_file_days(stripped, charger_id="X", source_timezone=SOURCE_TZ) == ()
