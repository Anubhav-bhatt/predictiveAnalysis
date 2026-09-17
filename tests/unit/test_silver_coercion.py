"""Unit tests for Silver telemetry coercion and sentinel evaluation (Phase 6)."""

from __future__ import annotations

import datetime as dt

from pipelines.normalization.coercion import (
    coerce_boolean,
    coerce_datetime,
    coerce_float,
    coerce_integer,
    coerce_string,
    is_gun_temp_sentinel,
    is_rectifier_temp_sentinel,
    is_smr_temp_sentinel,
)


def test_coerce_float() -> None:
    assert coerce_float("123.45") == 123.45
    assert coerce_float("0.0") == 0.0
    assert coerce_float("-42.5") == -42.5
    assert coerce_float("null") is None
    assert coerce_float("") is None
    assert coerce_float("NaN") is None
    assert coerce_float("invalid") is None
    assert coerce_float(42) == 42.0


def test_coerce_integer() -> None:
    assert coerce_integer("123") == 123
    assert coerce_integer("0") == 0
    assert coerce_integer("123.0") == 123
    assert coerce_integer("123.45") is None  # Not an integer
    assert coerce_integer("null") is None


def test_coerce_boolean() -> None:
    assert coerce_boolean("1") is True
    assert coerce_boolean("True") is True
    assert coerce_boolean("Alarm") is True
    assert coerce_boolean("Trip") is True
    assert coerce_boolean("0") is False
    assert coerce_boolean("False") is False
    assert coerce_boolean("Not alarm") is False
    assert coerce_boolean("Normal") is False
    assert coerce_boolean("unknown") is None


def test_coerce_string() -> None:
    assert coerce_string("  Active  ") == "Active"
    assert coerce_string("null") is None
    assert coerce_string("") is None
    assert coerce_string("  ") is None


def test_coerce_datetime() -> None:
    # Test CMS format: 16-09-2026 17:06:01 in Asia/Kolkata (UTC+5:30)
    parsed = coerce_datetime("16-09-2026 17:06:01")
    assert parsed is not None
    assert parsed.tzinfo == dt.UTC
    # 17:06:01 IST = 11:36:01 UTC
    assert parsed.hour == 11
    assert parsed.minute == 36
    assert parsed.second == 1

    # Test ISO format
    iso_parsed = coerce_datetime("2026-09-16T11:36:01+00:00")
    assert iso_parsed is not None
    assert iso_parsed.hour == 11


def test_sentinels() -> None:
    # Gun thermocouples: 999.0 / 999
    assert is_gun_temp_sentinel(999.0) is True
    assert is_gun_temp_sentinel(999.0001) is True
    assert is_gun_temp_sentinel(45.0) is False
    assert is_gun_temp_sentinel(None) is False

    # Rectifier internal temp: -50.0 / -50
    assert is_rectifier_temp_sentinel(-50.0) is True
    assert is_rectifier_temp_sentinel(60.0) is False
    assert is_rectifier_temp_sentinel(None) is False

    # SMR modular temp: -150.0 / -150
    assert is_smr_temp_sentinel(-150.0) is True
    assert is_smr_temp_sentinel(40.0) is False
    assert is_smr_temp_sentinel(None) is False
