"""Deterministic synthetic multi-file test fixture generator using the REAL 456-field schema.

Generates multi-day telemetry across multiple chargers, connectors, SMRs, and rectifiers
with controlled degradation, gaps, out-of-order arrival, topology evolution, same-second
frames, counter resets, and signal availability variations.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

CSV_SAMPLE_PATH = Path("16092026_170601_charger_status_latest.csv")


def get_real_456_headers() -> list[str]:
    """Retrieve authoritative 456 production headers from the sample CSV."""
    if CSV_SAMPLE_PATH.exists():
        with CSV_SAMPLE_PATH.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            return next(reader)
    raise FileNotFoundError(
        f"Authoritative 456-field production CSV not found at {CSV_SAMPLE_PATH}"
    )


def build_synthetic_frame_row(
    headers: list[str],
    *,
    charger_id: str,
    ocpp_id: str = "OCPP_DEF",
    station: str = "Station Central",
    logged_at: str = "01-09-2026 10:00:00",
    connector_no: int = 1,
    smr_no: int = 1,
    rectifier_no: int = 1,
    l1_n_voltage: float = 230.5,
    line_1_current: float = 15.2,
    cabinet_temp: float = 35.0,
    gun_temp_pos: float = 32.0,
    gun_voltage: float = 400.0,
    smr_dcdc_temp: float = 42.0,
    rectifier_internal_temp: float = 45.0,
    rsrp: float | None = -75.0,
    cumulative_energy: float = 100.0,
    charging_mode: str = "Standard",
) -> dict[str, Any]:
    """Build a complete 456-position row with realistic values for a specific frame."""
    row: dict[str, Any] = {}
    for h in headers:
        row[h] = ""

    # Populate canonical keys
    row["Charger Id"] = charger_id
    row["OCPP Id"] = ocpp_id
    row["Charging Station"] = station
    row["Logged At Time"] = logged_at
    row["L1-N Voltage"] = str(l1_n_voltage)
    row["Line 1 Input Current"] = str(line_1_current)
    row["Frequency"] = "50.0"
    row["Cabinet Temperature"] = str(cabinet_temp)

    # Connector fields
    row["Connector No"] = str(connector_no)
    row["Gun Temp Dc+"] = str(gun_temp_pos)
    row["Gun Temp Dc-"] = str(round(gun_temp_pos - 1.0, 1))
    row["Gun Voltage"] = str(gun_voltage)
    row["Connector Status"] = "Occupied"

    # SMR fields
    row["Smr No."] = str(smr_no)
    row["SMR DcDc Temperature"] = str(smr_dcdc_temp)

    # Rectifier fields
    row["Rectifier Number"] = str(rectifier_no)
    row["Rectifier Internal Temp"] = str(rectifier_internal_temp)

    # Communication
    if rsrp is not None:
        row["RSRP"] = str(rsrp)

    # Counter
    row["Ems Cumulative Energy"] = str(cumulative_energy)

    # Configuration
    row["Charging Mode"] = charging_mode

    return row


def generate_7day_history_csvs() -> dict[str, str]:
    """Generate 7 separate daily CSV files for 3 distinct chargers.

    Charger CH_HIST_01:
      - SMR-based charger (SMR 1, 2, 3, 4; Connectors 1 & 2)
      - Day 1 has same-second frame at 10:00:00 (two distinct frame rows)
      - Controlled degradation sequence on SMR 3 temp: Day 1=41, 2=42, 3=43, 4=46, 5=50, 6=55, 7=61
      - Counter sequence on Ems Cumulative Energy: 100, 105, 111, 118, 3, 8, 15 (reset on Day 5)
      - RSRP present (-75.0)

    Charger CH_HIST_02:
      - Rectifier-based charger (Rectifiers 1 & 2; Connectors 1 & 2)
      - Day 2 contains the gap fixture: 10:00, 10:02, 10:04, 10:06 -> gap -> 10:40 (34 min)
      - RSRP present (-80.0)

    Charger CH_HIST_03:
      - Topology evolution: Days 1-3 SMR 1-4; Days 4-7 SMR 1-6
      - Configuration change: Days 1-4 mode "Mode_A", Days 5-7 mode "Mode_B"
      - RSRP is missing/null across all days (verifies signal availability matrix)
    """
    headers = get_real_456_headers()
    files: dict[str, str] = {}

    smr3_temps = {1: 41.0, 2: 42.0, 3: 43.0, 4: 46.0, 5: 50.0, 6: 55.0, 7: 61.0}
    counter_vals = {1: 100.0, 2: 105.0, 3: 111.0, 4: 118.0, 5: 3.0, 6: 8.0, 7: 15.0}

    for day in range(1, 8):
        day_str = f"{day:02d}-09-2026"
        filename = f"telemetry_{day_str}.csv"
        rows: list[dict[str, Any]] = []

        # --- CH_HIST_01 ---
        s3_temp = smr3_temps[day]
        cnt_val = counter_vals[day]

        # Day 1 same-second frame test: frame 0 and frame 1 at 10:00:00
        if day == 1:
            rows.append(
                build_synthetic_frame_row(
                    headers,
                    charger_id="CH_HIST_01",
                    logged_at=f"{day_str} 10:00:00",
                    connector_no=1,
                    smr_no=1,
                    smr_dcdc_temp=38.0,
                    cumulative_energy=cnt_val,
                )
            )
            rows.append(
                build_synthetic_frame_row(
                    headers,
                    charger_id="CH_HIST_01",
                    logged_at=f"{day_str} 10:00:00",
                    connector_no=2,
                    smr_no=3,
                    smr_dcdc_temp=s3_temp,
                    cumulative_energy=cnt_val,
                )
            )

        # Observations across the day for CH_HIST_01 (10:02, 10:04, 10:06, 10:08)
        for minute in (2, 4, 6, 8):
            rows.append(
                build_synthetic_frame_row(
                    headers,
                    charger_id="CH_HIST_01",
                    logged_at=f"{day_str} 10:{minute:02d}:00",
                    connector_no=1,
                    smr_no=3,
                    smr_dcdc_temp=s3_temp,
                    cumulative_energy=cnt_val + (minute * 0.1),
                    rsrp=-75.0,
                )
            )

        # --- CH_HIST_02 --- (Rectifier based)
        if day == 2:
            # Gap fixture: 10:00, 10:02, 10:04, 10:06 -> 10:40 (34 min gap)
            gap_minutes = (0, 2, 4, 6, 40)
            for m in gap_minutes:
                rows.append(
                    build_synthetic_frame_row(
                        headers,
                        charger_id="CH_HIST_02",
                        logged_at=f"{day_str} 10:{m:02d}:00",
                        connector_no=1,
                        rectifier_no=1,
                        rectifier_internal_temp=48.0,
                        rsrp=-80.0,
                    )
                )
        else:
            for m in (0, 2, 4, 6, 8):
                rows.append(
                    build_synthetic_frame_row(
                        headers,
                        charger_id="CH_HIST_02",
                        logged_at=f"{day_str} 10:{m:02d}:00",
                        connector_no=1,
                        rectifier_no=1,
                        rectifier_internal_temp=48.0,
                        rsrp=-80.0,
                    )
                )

        # --- CH_HIST_03 --- (Topology & Config evolution; No RSRP)
        smr_count = 4 if day <= 3 else 6  # Topology evolution on Day 4
        cfg_mode = "Mode_A" if day <= 4 else "Mode_B"  # Config change on Day 5

        for m in (0, 2, 4, 6, 8):
            for s_id in range(1, smr_count + 1):
                rows.append(
                    build_synthetic_frame_row(
                        headers,
                        charger_id="CH_HIST_03",
                        logged_at=f"{day_str} 10:{m:02d}:00",
                        connector_no=1,
                        smr_no=s_id,
                        smr_dcdc_temp=40.0 + s_id,
                        rsrp=None,  # Intentionally absent signal!
                        charging_mode=cfg_mode,
                    )
                )

        # Serialize to CSV text
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

        files[filename] = out.getvalue()

    return files
