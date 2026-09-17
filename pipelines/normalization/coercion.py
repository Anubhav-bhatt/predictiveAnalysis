"""Type coercion and field-specific sentinel masking for Silver telemetry (Phase 6).

Governed by schema charger_status_v2.0.0 and PHASE6_NORMALIZATION_CONTRACT.md.
Never fabricates, guesses, or silently drops telemetry.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any

__all__ = [
    "coerce_boolean",
    "coerce_datetime",
    "coerce_float",
    "coerce_integer",
    "coerce_string",
    "is_gun_temp_sentinel",
    "is_rectifier_temp_sentinel",
    "is_smr_temp_sentinel",
]

# Source timestamps from CMS are in Asia/Kolkata (IST = UTC+5:30)
_SOURCE_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")
_UTC = dt.UTC


def coerce_float(val: Any) -> float | None:
    """Safely coerce raw string to float. Returns None for empty or invalid values."""
    if val is None:
        return None
    if isinstance(val, (float, int)):
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan", "na", "-"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def coerce_integer(val: Any) -> int | None:
    """Safely coerce raw string to integer. Returns None for empty or invalid values."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val) if val.is_integer() else None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan", "na", "-"):
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else None
    except (ValueError, TypeError):
        return None


def coerce_boolean(val: Any) -> bool | None:
    """Safely coerce raw string or number to boolean."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "alarm", "trip", "active", "closed"):
        return True
    if s in ("0", "false", "no", "not alarm", "normal", "inactive", "open"):
        return False
    return None


def coerce_string(val: Any) -> str | None:
    """Clean and strip raw string. Returns None for null tokens."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan", "na"):
        return None
    return s


def coerce_datetime(val: Any) -> dt.datetime | None:
    """Parse source timestamp string into UTC datetime.

    Source format is '%d-%m-%Y %H:%M:%S' in Asia/Kolkata, or ISO-8601.
    """
    if val is None:
        return None
    if isinstance(val, dt.datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=_SOURCE_TZ).astimezone(_UTC)
        return val.astimezone(_UTC)
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan", "na", "-"):
        return None

    # Try standard CMS format: DD-MM-YYYY HH:MM:SS
    for fmt in (
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            parsed = dt.datetime.strptime(s, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_SOURCE_TZ)
            return parsed.astimezone(_UTC)
        except ValueError:
            continue

    # Fallback ISO format parser
    try:
        parsed = dt.datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_SOURCE_TZ)
        return parsed.astimezone(_UTC)
    except (ValueError, TypeError):
        return None


def is_gun_temp_sentinel(val: float | None) -> bool:
    """Check if value is a gun thermocouple disconnect sentinel (999.0 or 999)."""
    if val is None:
        return False
    return abs(val - 999.0) < 0.001


def is_rectifier_temp_sentinel(val: float | None) -> bool:
    """Check if value is a rectifier uninitialized temp sentinel (-50.0 or -50)."""
    if val is None:
        return False
    return abs(val - (-50.0)) < 0.001


def is_smr_temp_sentinel(val: float | None) -> bool:
    """Check if value is an SMR probe unavailable temp sentinel (-150.0 or -150)."""
    if val is None:
        return False
    return abs(val - (-150.0)) < 0.001
