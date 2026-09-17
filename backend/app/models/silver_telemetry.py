"""Typed, normalized Silver telemetry models (Phase 6).

Governed by schema revision charger_status_v2.0.0.
Every one of the 456 production source positions maps to an explicit typed column
in one of the 11 domain Silver tables without data loss, truncation, or fabrication.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import (
    Base,
    JSONVariant,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class SilverSiteMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Operational site metadata extracted from telemetry frames."""

    __tablename__ = "silver_site_metadata"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    charging_station: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    site_address: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    site_city: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    site_state: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    site_pin: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_site_metadata"
        ),
    )


class SilverChargerTelemetry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cabinet and grid-level continuous electrical and environmental telemetry (120 fields)."""

    __tablename__ = "silver_charger_telemetry"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ocpp_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    l1_n_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 5: L1-N Voltage
    l2_n_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 6: L2-N Voltage
    l3_n_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 7: L3-N Voltage
    neutral_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 8: Neutral Voltage
    line_1_input_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 9: Line 1 Input Current
    line_2_input_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 10: Line 2 Input Current
    line_3_input_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 11: Line 3 Input Current
    frequency: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 12: Frequency
    power_factor: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 13: Power Factor
    active_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 14: Active Power
    l1_l2_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 16: L1-L2 Voltage
    l2_l3_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 17: L2-L3 Voltage
    l3_l1_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 18: L3-L1 Voltage
    reactive_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 19: Reactive Power
    active_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 20: Active Energy
    reactive_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 21: Reactive Energy
    apparent_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 22: Apparent Energy
    l1_n_voltage_meter: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 24: L1-N Voltage(Meter)
    l2_n_voltage_meter: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 25: L2-N Voltage(Meter)
    l3_n_voltage_meter: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 26: L3-N Voltage(Meter)
    grid_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 27: Grid Status
    apparent_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 28: Apparent Power
    pilot_upper_tcp_interface: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 48: Pilot-Upper TCP Interface
    rms_enable_modified_by: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 49: RMS Enable ModifiedBy
    fan_run_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 50: Fan Run Status
    fan_set_speed: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 51: FAN Set Speed
    system_fan_speed: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 52: System Fan Speed
    cabinet_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 53: Cabinet Temperature
    cooling_temp_sensor_1: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 54: Cooling Temp Sensor 1
    cooling_temp_sensor_2: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 55: Cooling Temp Sensor 2
    fan_card_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 56: Fan Card Status
    fan_1_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 58: Fan 1 Status
    fan_2_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 59: Fan 2 Status
    fan_3_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 60: Fan 3 Status
    fan_4_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 61: Fan 4 Status
    fan_5_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 62: Fan 5 Status
    fan_6_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 63: Fan 6 Status
    fan_7_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 64: Fan 7 Status
    fan_8_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 65: Fan 8 Status
    fan_9_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 66: Fan 9 Status
    fan_10_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 67: Fan 10 Status
    fan_11_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 68: Fan 11 Status
    fan_12_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 69: Fan 12 Status
    fan_13_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 70: Fan 13 Status
    fan_14_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 71: Fan 14 Status
    fan_15_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 72: Fan 15 Status
    fan_16_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 73: Fan 16 Status
    fan_17_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 74: Fan 17 Status
    fan_18_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 75: Fan 18 Status
    fan_19_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 76: Fan 19 Status
    fan_20_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 77: Fan 20 Status
    fan_21_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 78: Fan 21 Status
    fan_22_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 79: Fan 22 Status
    fan_23_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 80: Fan 23 Status
    dc_section_fan_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 81: DC Section FAN Status
    line_1_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 88: Line 1 Over Voltage
    line_2_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 89: Line 2 Over Voltage
    line_3_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 90: Line 3 Over Voltage
    line_1_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 91: Line 1 Under Voltage
    line_2_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 92: Line 2 Under Voltage
    line_3_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 93: Line 3 Under Voltage
    system_over_temperature: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 97: System Over Temperature
    system_tilted: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 99: System Tilted
    temperature_sensor_disconnected: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 100: Temperature Sensor Disconnected
    mains_high: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 103: Mains High
    mains_low: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 104: Mains Low
    sd_card_not_present: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 106: SD Card Not Present
    temperature_sensor_1_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 110: Temperature Sensor-1 Fail
    temperature_sensor_2_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 111: Temperature Sensor-2 Fail
    dcem_sn_duplicate: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 119: DCEM SN Duplicate
    grid_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 126: Grid Over Voltage
    grid_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 127: Grid Under Voltage
    ocpp_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 132: OCPP State
    pilot_controller_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 133: Pilot Controller State
    ccu_main_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 137: CCU Main State
    cp_voltage: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 138: CP Voltage
    set_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 146: Set Voltage
    set_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 147: Set Current
    output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 148: Output Voltage
    output_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 149: Output Current
    available_max_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 150: Available Max Current
    available_max_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 151: Available Max Power
    dc_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 154: DC Over Voltage
    e_lock_failed: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 164: E Lock Failed
    auxillary_power_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 168: Auxillary Power Fail
    voltage_calibration_error: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 181: Voltage Calibration Error
    power_section_failed: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 182: Power Section Failed
    ems_output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 183: Ems Output Voltage
    ems_output_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 184: Ems Output Current
    ems_output_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 185: Ems Output Power
    ac_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 189: AC Over Voltage
    ac_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 191: AC Under Voltage
    charging_time: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 207: Charging Time
    ocpp_tx_send_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 216: OCPP Tx Send Status
    ev_mac_id_info: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 217: EV Mac ID Info
    slac_attenuation: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 231: SLAC Attenuation
    discharge_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 247: Discharge Abnormal
    dc_side_is_off: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 248: DC Side Is Off
    mdl_protect: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 250: MDL Protect
    over_temperature: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 252: Over Temperature
    output_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 253: Output Over Voltage
    walk_in_enabled: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 254: Walk In Enabled
    mdl_id_repetition: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 257: MDL Id Repetition
    load_sharing: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 258: Load Sharing
    input_phase_loss: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 259: Input Phase Loss
    input_unbalance: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 260: Input Unbalance
    input_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 261: Input Under Voltage
    input_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 262: Input Over Voltage
    fuse_burn_out: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 264: Fuse Burn Out
    bus_unbalanced_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 266: Bus Unbalanced Voltage
    bus_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 267: Bus Over Voltage
    bus_voltage_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 268: Bus Voltage Abnormal
    bus_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 269: Bus Under Voltage
    fan_at_full_speed: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 270: Fan At Full Speed
    output_derating_temp: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 271: Output Derating Temp
    output_derating_ac: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 272: Output Derating AC
    back_up_battery_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 443: BackUp Battery Voltage
    run_since_power_on: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 444: Run Since Power On
    last_charger_reboot_reason: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 456: Last Charger Reboot Reason

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_charger_telemetry"
        ),
        sa.Index(
            "ix_silver_charger_telemetry_lookup", "charger_id", "event_time", "frame_sequence"
        ),
    )


class SilverConnectorTelemetry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Connector and dispensing gun telemetry (33 fields) with sentinel tracking."""

    __tablename__ = "silver_connector_telemetry"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True, default=1)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Sentinel tracking for gun thermocouples
    gun_temp_dc_positive_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    gun_temp_dc_positive_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    gun_temp_dc_negative_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    gun_temp_dc_negative_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )

    connector_type: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 130: Connector Type
    connector_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 131: Connector Status
    plug_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 134: Plug Status
    ccs_main_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 135: CCS Main State
    ccs_sub_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 136: CCS Sub State
    gun_temp_dc_positive: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 139: Gun Temp Dc+
    gun_temp_dc_negative: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 140: Gun Temp Dc-
    gun_insertion_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 141: Gun Insertion Cycle Count
    gun_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 142: Gun Voltage
    gun_over_temp_warning: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 158: Gun Over Temp Warning
    gun_over_temp_cutoff: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 159: GunOverTempCutoff
    gun_over_temp_dc_positive_warning: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 160: GUNOverTempDC+ Warning
    gun_over_temp_dc_negative_warning: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 161: GUNOverTempDC- Warning
    gun_ov_temp_derating_set: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 162: Gun Ov Temp Derating Set
    gun_locked_by_cms: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 166: Gun locked by CMS
    gun_temperature_derating_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 169: Gun Temperature Derating Status
    gun_dc_positive_ultra_temp: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 172: Gun Dc+ Ultra Temp
    gun_dc_negative_ultra_temp: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 173: Gun Dc- Ultra Temp
    gun_dc_positive_temp_sensor_disconnect: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 175: Gun DC+ Temp Sensor Disconnect
    gun_dc_negative_temp_sensor_disconnect: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 176: Gun DC- Temp Sensor Disconnect
    gun_temperature_sensor_disconnect: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 177: GUN Temperature Sensor Disconnect
    gun_dc_positive_temp_sensor_loose: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 178: GUN DC+ Temp Sensor Loose
    gun_dc_negative_temp_sensor_loose: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 179: GUN DC- Temp Sensor Loose
    gun_not_placed_back_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 180: Gun Not Placed Back Alarm
    ccs_secc_state: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 211: CCS Secc State
    ccs_secc_error_code: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 212: CCS Secc Error Code
    ccs_ev_error_code: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 213: CCS Ev Error Code
    gun_output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 219: Gun Output Voltage
    gun_ccs_main_state_at_session_stop: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 224: GUN CCS Main State at Session stop
    gun_ccs_sub_state_at_session_stop: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 225: GUN CCS Sub State at Session stop
    gun_insert_counter_charger_socket: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 227: Gun Insert Counter- Charger Socket
    gun_over_temperature_counter: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 228: Gun Over Temperature Counter
    gun_placed_in_charger_holder: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 230: Gun Placed in Charger Holder

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "connector_id",
            "event_time",
            "frame_sequence",
            name="uq_silver_connector_telemetry",
        ),
        sa.Index(
            "ix_silver_connector_telemetry_lookup",
            "charger_id",
            "connector_id",
            "event_time",
            "frame_sequence",
        ),
    )


class SilverRectifierTelemetry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rectifier sub-assembly telemetry (18 fields) including internal temp sentinel tracking."""

    __tablename__ = "silver_rectifier_telemetry"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    rectifier_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True, default=1)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Sentinel tracking
    rect_max_temperature_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    rect_max_temperature_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    rectifier_internal_temp_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    rectifier_internal_temp_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )

    rect_max_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 57: Rect Max Temperature
    all_rectifier_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 117: All Rectifier Fail
    all_rectifier_communication_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 118: All Rectifier Communication Fail
    any_rect_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 125: Any Rect Fail
    any_rect_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 128: Any Rect Comm Fail
    no_of_active_rectifiers: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 145: No Of Active Rectifiers
    group_rect_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 152: Group Rect Fail
    group_rect_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 153: Group Rect Comm Fail
    gun_rect_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 170: Gun Rect Fail
    gun_rect_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 171: Gun Rect Comm Fail
    rectifier_dc_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 233: Rectifier Dc Status
    rectifier_internal_temp: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 234: Rectifier Internal Temp
    rectifier_output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 237: Rectifier Output Voltage
    rectifier_output_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 238: Rectifier Output Current
    rectifier_available_max_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 239: Rectifier Available Max Voltage
    rectifier_available_max_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 240: Rectifier Available Max Current
    rectifier_available_max_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 241: Rectifier Available MaxPower
    rectifier_output_short: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 244: Rectifier Output Short

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "rectifier_id",
            "event_time",
            "frame_sequence",
            name="uq_silver_rectifier_telemetry",
        ),
        sa.Index(
            "ix_silver_rectifier_telemetry_lookup",
            "charger_id",
            "rectifier_id",
            "event_time",
            "frame_sequence",
        ),
    )


class SilverSmrTelemetry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Switched-mode rectifier modular telemetry (118 fields) including probe sentinel tracking."""

    __tablename__ = "silver_smr_telemetry"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    smr_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True, default=1)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Sentinel tracking for modular thermocouples
    smr_dc_dc_temperature_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    smr_dc_dc_temperature_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    smr_pfc_temperature_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    smr_pfc_temperature_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    smr_rectifierinternal_temp_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    smr_rectifierinternal_temp_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    smrdcdc_temperature_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    smrdcdc_temperature_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    smrpfc_temperature_raw: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    smrpfc_temperature_masked: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )

    smr_set_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 220: SMR Set Voltage
    smr_set_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 221: SMR Set Current
    smr_available_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 222: SMR Available Current
    smr_max_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 223: SMR Max Power
    smr_dc_dc_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 235: SMR DcDc Temperature
    smr_pfc_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 236: SMR Pfc Temperature
    smr_hardware_version: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 242: SMR Hardware Ver
    smr_software_version: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 243: SMR Soft Ver
    pfc_side_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 246: PFC Side Abnormal
    pfc_side_is_off: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 263: PFC Side Is Off
    pfc_dcdc_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 265: PFC DCDC Comm Fail
    pfc_eeprom_faults: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 274: PFC Eeprom Faults
    smr_mapped_gun: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 300: SMR Mapped GUN
    smr_group_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 301: SMR GroupId
    smr_output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 302: SMR OutputVoltage
    smr_output_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 303: SMR OutputCurrent
    smr_output_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 304: SMR Output Power
    smr_available_max_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 305: SMR AvailableMaxCurrent
    smr_available_max_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 306: SMR AvailableMaxPower
    smr_rectifier_d_cstatus: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 307: SMR RectifierDCstatus
    smr_rectifierinternal_temp: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 308: SMR RectifierinternalTemp
    smrdcdc_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 309: SMRDCDCTemperature
    smrpfc_temperature: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 310: SMRPFCTemperature
    smr_available_max_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 311: SMR AvailableMaxVoltage
    smr_rated_maximum_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 312: SMR Rated Maximum Current
    smr_rated_maximum_power: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 313: SMR Rated Maximum Power
    smr_module_hardware_version: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 314: SMRHardwareVer
    smr_module_software_version: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 315: SMRSoftVer
    smrpfc_ver: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 316: SMRPFCVer
    smr_line1_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 317: SMR Line1 Voltage
    smr_line2_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 318: SMR Line2 Voltage
    smr_line3_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 319: SMR Line3 Voltage
    smr_rated_minimum_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 320: SMR Rated Minimum Voltage
    smr_rated_maximum_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 321: SMR Rated Maximum Voltage
    smr_fan_speed: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 322: SMR Fan Speed
    smr_output_short: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 323: SMR Output Short
    smr_inner_comm_interrupt: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 324: SMR Inner Comm Interrupt
    smr_pfc_side_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 325: SMR PFC Side Abnormal
    smr_discharge_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 326: SMR Discharge Abnormal
    smr_dc_side_is_off: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 327: SMR DC Side is OFF
    smr_mdl_fault: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 328: SMR MDL Fault
    smr_mdl_protect: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 329: SMR MDL Protect
    smr_fan_fault: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 330: SMR Fan Fault
    smr_over_temperature: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 331: SMR Over Temperature
    smr_output_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 332: SMR Output Over Voltage
    smr_walk_in_enable: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 333: SMR WALK-IN Enable
    smr_can_communication_interrupt: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 334: SMR CAN Communication Interrupt
    smr_power_limit: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 335: SMR Power Limit
    smr_dl_id_repetition: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 336: SMR DL ID Repetition
    smr_load_sharing: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 337: SMR Load Sharing
    smr_input_phase_loss: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 338: SMR Input Phase loss
    smr_input_unbalance: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 339: SMR Input Unbalance
    smr_input_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 340: SMR Input Under Voltage
    smr_input_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 341: SMR Input Over Voltage
    smr_pfc_side_is_off: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 342: SMR PFC Side is OFF
    smr_fuse_burn_out: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 343: SMR Fuse Burn Out
    smr_pfc_dcdc_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 344: SMR PFC DCDC Comm Fail
    smr_bus_unbalanced_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 345: SMR Bus Unbalanced Voltage
    smr_bus_over_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 346: SMR Bus Over Voltage
    smr_bus_voltage_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 347: SMR Bus Voltage Abnormal
    smr_bus_under_voltage: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 348: SMR Bus Under Voltage
    smr_fan_at_full_speed: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 349: SMR Fan At Full Speed
    smr_output_derating_temp: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 350: SMR Output Derating Temp
    smr_output_derating_ac: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 351: SMR Output Derating AC
    smr_dcdc_eeprom_faults: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 352: SMR DCDC Eeprom Faults
    smr_pfc_eeprom_faults: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 353: SMR PFC Eeprom Faults
    smr_module_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 354: SMR Module Fail
    smr_module_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 355: SMR Module Comm Fail
    in_pfc_1: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 356: IN_PFC-1
    in_pfc_2: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 357: IN_PFC-2
    in_pfc_3: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 358: IN_PFC-3
    in_pfc_4: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 359: IN_PFC-4
    in_pfc_5: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 360: IN_PFC-5
    in_pfc_6: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 361: IN_PFC-6
    in_pfc_7: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 362: IN_PFC-7
    in_pfc_8: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 363: IN_PFC-8
    in_pfc_9: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # pos 364: IN_PFC-9
    in_pfc_10: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 365: IN_PFC-10
    in_pfc_11: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 366: IN_PFC-11
    in_pfc_12: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 367: IN_PFC-12
    out_pfc_1: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 368: Out_PFC-1
    out_pfc_2: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 369: Out_PFC-2
    out_pfc_3: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 370: Out_PFC-3
    out_pfc_4: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 371: Out_PFC-4
    out_pfc_5: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 372: Out_PFC-5
    out_pfc_6: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 373: Out_PFC-6
    out_pfc_7: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 374: Out_PFC-7
    out_pfc_8: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 375: Out_PFC-8
    out_pfc_9: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 376: Out_PFC-9
    out_pfc_10: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 377: Out_PFC-10
    out_pfc_11: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 378: Out_PFC-11
    out_pfc_12: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 379: Out_PFC-12
    floating_smr1_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 380: Floating SMR1 Fail
    floating_smr1_group_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 381: Floating SMR1 Group Fail
    floating_smr1_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 382: Floating SMR1 Comm Fail
    floating_smr1_group_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 383: Floating SMR1 Group Comm Fail
    floating_smr2_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 384: Floating SMR2 Fail
    floating_smr2_group_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 385: Floating SMR2 Group Fail
    floating_smr2_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 386: Floating SMR2 Comm Fail
    floating_smr2_group_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 387: Floating SMR2 Group Comm Fail
    floating_smr3_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 388: Floating SMR3 Fail
    floating_smr3_group_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 389: Floating SMR3 Group Fail
    floating_smr3_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 390: Floating SMR3 Comm Fail
    floating_smr3_group_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 391: Floating SMR3 Group Comm Fail
    floating_smr4_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 392: Floating SMR4 Fail
    floating_smr4_group_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 393: Floating SMR4 Group Fail
    floating_smr4_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 394: Floating SMR4 Comm Fail
    floating_smr4_group_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 395: Floating SMR4 Group Comm Fail
    smr_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 446: SMR Fail Count
    smr_comm_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 447: SMR Comm Fail Count
    guna_smr_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 448: GUNA SMR Fail Count
    guna_smr_comm_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 449: GUNA SMR Comm Fail Count
    gunb_smr_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 450: GUNB SMR Fail Count
    gunb_smr_comm_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 451: GUNB SMR Comm Fail Count
    fr1_smr_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 452: FR1 SMR Fail Count
    fr1_smr_comm_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 453: FR1 SMR Comm Fail Count
    fr2_smr_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 454: FR2 SMR Fail Count
    fr2_smr_comm_fail_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 455: FR2 SMR Comm Fail Count

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "smr_id", "event_time", "frame_sequence", name="uq_silver_smr_telemetry"
        ),
        sa.Index(
            "ix_silver_smr_telemetry_lookup", "charger_id", "smr_id", "event_time", "frame_sequence"
        ),
    )


class SilverContactorObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Contactor auxiliary switch states and cycle counts (53 fields)."""

    __tablename__ = "silver_contactor_observation"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    ac_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 15: AC Contactor Status
    input_contactor_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 98: Input Contactor Fail
    gun_dc_contactor_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 174: Gun Dc Contactor Fail
    ac_contactor_switching_cycle: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 187: AC Contactor Switching Cycle
    ac_contactor_feedback_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 188: AC Contactor Feedback Status
    dc_contactor_switching_cycle: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 226: DC Contactor Switching Cycle
    ac1_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 396: AC1 Contactor Status
    ac2_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 397: AC2 Contactor Status
    ac3_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 398: AC3 Contactor Status
    ac4_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 399: AC4 Contactor Status
    ac5_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 400: AC5 Contactor Status
    ac6_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 401: AC6 Contactor Status
    ac1_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 402: AC1 Contactor Cycle Count
    ac2_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 403: AC2 Contactor Cycle Count
    ac3_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 404: AC3 Contactor Cycle Count
    ac4_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 405: AC4 Contactor Cycle Count
    ac5_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 406: AC5 Contactor Cycle Count
    ac6_contactor_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 407: AC6 Contactor Cycle Count
    ac1_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 408: AC1 Contactor Fail  Alarm
    ac2_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 409: AC2 Contactor Fail  Alarm
    ac3_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 410: AC3 Contactor Fail  Alarm
    ac4_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 411: AC4 Contactor Fail  Alarm
    ac5_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 412: AC5 Contactor Fail  Alarm
    ac6_contactor_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 413: AC6 Contactor Fail  Alarm
    ac1_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 414: AC1 Contactor Welded Alarm
    ac2_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 415: AC2 Contactor Welded Alarm
    ac3_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 416: AC3 Contactor Welded Alarm
    ac4_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 417: AC4 Contactor Welded Alarm
    ac5_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 418: AC5 Contactor Welded Alarm
    ac6_contactor_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 419: AC6 Contactor Welded Alarm
    dc_merger_contactor_c0_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 420: DC Merger Contactor (C0) Cycle Count
    dc_merger_contactor_c1_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 421: DC Merger Contactor (C1) Cycle Count
    dc_merger_contactor_c2_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 422: DC Merger Contactor (C2) Cycle Count
    dc_merger_contactor_c3_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 423: DC Merger Contactor (C3) Cycle Count
    dc_merger_contactor_c4_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 424: DC Merger Contactor (C4) Cycle Count
    external_contactor_cycle_count_ring: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 425: External Contactor Cycle Count(Ring)
    merger_contactor_c0_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 426: Merger Contactor (C0) Fail Alarm
    merger_contactor_c1_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 427: Merger Contactor (C1) Fail Alarm
    merger_contactor_c2_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 428: Merger Contactor (C2) Fail Alarm
    merger_contactor_c3_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 429: Merger Contactor (C3) Fail Alarm
    merger_contactor_c4_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 430: Merger Contactor (C4) Fail Alarm
    external_contactor_fail_alarm_ring: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 431: External Contactor Fail Alarm(Ring)
    merger_contactor_c0_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 432: Merger Contactor (C0) Welded Alarm
    merger_contactor_c1_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 433: Merger Contactor (C1) Welded Alarm
    merger_contactor_c2_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 434: Merger Contactor (C2) Welded Alarm
    merger_contactor_c3_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 435: Merger Contactor (C3) Welded Alarm
    merger_contactor_c4_welded_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 436: Merger Contactor (C4) Welded Alarm
    c0_merger_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 437: C0 Merger Contactor Status
    c1_merger_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 438: C1 Merger Contactor Status
    c2_merger_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 439: C2 Merger Contactor Status
    c3_merger_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 440: C3 Merger Contactor Status
    c4_merger_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 441: C4 Merger Contactor Status
    external_contactor_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 442: External Contactor Status

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_contactor_observation"
        ),
        sa.Index(
            "ix_silver_contactor_observation_lookup", "charger_id", "event_time", "frame_sequence"
        ),
    )


class SilverAlarmObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alarm flags, protection trips, and insulation diagnostics (60 fields)."""

    __tablename__ = "silver_alarm_observation"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    active_alarms_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    active_alarm_codes: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    ground_resistance_value: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 23: Ground resistance value
    rtc_clock_drift_warning: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 42: RTC Clock Drift Warning
    rms_disabled_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 43: RMS Disabled Alarm
    grid_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 82: Grid Fail
    class_c_spd_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 83: Class-C SPD Fail
    ne_voltage_high_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 84: NE Voltage High Alarm
    line_1_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 85: Line 1 Fail
    line_2_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 86: Line 2 Fail
    line_3_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 87: Line 3 Fail
    door_open: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 94: Door Open
    smoke_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 95: Smoke Alarm
    emergency_stop_active: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 96: Emergency Stop Active
    system_fan_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 101: System FAN Fail
    filter_maintenance_warning: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 102: Filter Maintenance Warning
    grid_abnormal: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 105: Grid Abnormal
    sd_card_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 107: SD Card Fail
    sd_card_crc_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 108: SD Card Crc Fail
    input_rcbo_tripped: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 109: Input RCBO Tripped
    mccb_tripped: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 112: MCCB Tripped
    class_d_spd_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 113: Class-D SPD Fail Alarm
    ground_fault_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 114: Ground Fault Alarm
    hvlv_cut_off_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 115: HVLV Cut-Off Alarm
    auxillary_mcb_trip_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 116: Auxillary MCB Trip Alarm
    backup_battery_low: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 120: BackupBatteryLow
    earth_leakage_sensed_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 121: Earth Leakage Sensed Alarm
    short_circuit: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 155: Short Circuit
    last_insulation_test_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 157: Last Insulation Test Fail
    fuse_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 167: Fuse Fail Alarm
    ac_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 190: AC Fail Alarm
    dc_positive_insulation_resistance: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 199: DC + Insulation Resistance
    dc_negative_insulation_resistance: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 200: DC - Insulation Resistance
    last_insulation_test_status: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 201: Last Insulation Test Status
    calculated_insulation_resistance: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 218: Calculated Insulation Resistance
    mdl_fault: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 249: MDL Fault
    fan_fault: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 251: Fan Fault
    dcdc_eeprom_faults: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 273: DCDC Eeprom Faults
    fan_1_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 275: Fan 1 Fail
    fan_2_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 276: Fan 2 Fail
    fan_3_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 277: Fan 3 Fail
    fan_4_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 278: Fan 4 Fail
    fan_5_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 279: Fan 5 Fail
    fan_6_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 280: Fan 6 Fail
    fan_7_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 281: Fan 7 Fail
    fan_8_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 282: Fan 8 Fail
    fan_9_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 283: Fan 9 Fail
    fan_10_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 284: Fan 10 Fail
    fan_11_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 285: Fan 11 Fail
    fan_12_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 286: Fan 12 Fail
    fan_13_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 287: Fan 13 Fail
    fan_14_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 288: Fan 14 Fail
    fan_15_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 289: Fan 15 Fail
    fan_16_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 290: Fan 16 Fail
    fan_17_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 291: Fan 17 Fail
    fan_18_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 292: Fan 18 Fail
    fan_19_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 293: Fan 19 Fail
    fan_20_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 294: Fan 20 Fail
    fan_21_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 295: Fan 21 Fail
    fan_22_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 296: Fan 22 Fail
    fan_23_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 297: Fan 23 Fail
    dc_section_fan_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 298: DC Section Fan Fail

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_alarm_observation"
        ),
        sa.Index(
            "ix_silver_alarm_observation_lookup", "charger_id", "event_time", "frame_sequence"
        ),
    )


class SilverSessionObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Charging session status, power delivery, and stop reasons (13 fields)."""

    __tablename__ = "silver_session_observation"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True, default=1)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Connector-disambiguated stop reason
    stop_reason: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    last_charge_session_stop_reason: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 144: Last Charge Session Stop Reason
    session_type: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 193: Session Type
    session_id: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 194: Session Id
    session_output_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 195: Session Output Voltage
    session_output_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 196: Session Output Current
    session_demand_voltage: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 197: Session Demand Voltage
    session_demand_current: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 198: Session Demand Current
    session_start_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 202: Session Start Energy
    session_consumed_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 203: Session Consumed Energy
    start_soc: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 204: Start Soc
    stop_soc: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 205: Stop Soc
    begin_time: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )  # pos 206: Begin Time
    last_charge_session_stop_reason_secondary: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 210: Last Charge Session Stop Reason

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "connector_id",
            "event_time",
            "frame_sequence",
            name="uq_silver_session_observation",
        ),
        sa.Index(
            "ix_silver_session_observation_lookup",
            "charger_id",
            "connector_id",
            "event_time",
            "frame_sequence",
        ),
    )


class SilverLifecycleCounterObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cumulative energy and cycle counters (2 fields)."""

    __tablename__ = "silver_lifecycle_counter_observation"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    ems_cumulative_energy: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 186: Ems Cumulative Energy
    charging_cycle_count: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 229: Charging Cycle Count

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id",
            "event_time",
            "frame_sequence",
            name="uq_silver_lifecycle_counter_observation",
        ),
        sa.Index(
            "ix_silver_lifecycle_counter_observation_lookup",
            "charger_id",
            "event_time",
            "frame_sequence",
        ),
    )


class SilverCommunicationObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cellular signal quality and internal bus communication statuses (25 fields)."""

    __tablename__ = "silver_communication_observation"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    ccu_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 29: CCU Comm Fail
    led_strip_card_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 30: LED Strip Card Comm Fail
    dcsi_card_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 31: DCSI Card Comm Fail
    ac_sense_card_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 32: AC Sense Card CommFail
    led_board_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 33: LED Board Comm Fail
    rfid_reader_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 34: RFID Reader Comm Fail
    modem_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 35: Modem Comm Fail
    modem_sim_present: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 36: Modem Sim Present
    display_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 37: Display Comm Fail
    cms_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 38: CMS Comm Fail
    fan_card_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 39: Fan Card Comm Fail
    i_o_card_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 40: I/O Card Comm Fail
    input_acem_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 41: Input ACEM Comm Fail
    led_card2_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 44: LEDCard2 Comm Fail
    rsrp: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 46: RSRP
    rsrq: Mapped[float | None] = mapped_column(sa.Float, nullable=True)  # pos 47: RSRQ
    gmd_comm_fail_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 122: GMD Comm Fail alarm
    ring_communication_break: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 123: Ring Communication Break
    sim_not_inserted_alarm: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 124: SIM not inserted Alarm
    insulation_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 156: Insulation Comm Fail
    plc_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 163: PLC Comm Fail
    energy_meter_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 165: Energy Meter Comm Fail
    ac_energy_meter_comm_fail: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 192: AC EnergyMeterCommFail
    inner_comm_interrupt: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 245: Inner Comm Interrupt
    can_communication_interrupt: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 255: CAN Communication Interrupt

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_communication_observation"
        ),
        sa.Index(
            "ix_silver_communication_observation_lookup",
            "charger_id",
            "event_time",
            "frame_sequence",
        ),
    )


class SilverConfigurationSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Static configuration and operating parameters (8 fields)."""

    __tablename__ = "silver_configuration_snapshot"

    charger_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    event_time: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    frame_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )

    config_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    raw_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    modem_signal_intensity: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 45: Modem Signal Intensity
    charge_selected_mode: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 143: Charge Selected Mode
    charging_start_method: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 208: Charging Start Method
    charging_mode: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 209: Charging Mode
    ev_max_voltage_limit: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 214: EV Max Voltage Limit
    ev_max_current_limit: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # pos 215: EV Max Current Limit
    power_limit: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 256: Power Limit
    ring_current_operating_mode: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )  # pos 445: Ring Current Operating Mode

    __table_args__ = (
        sa.UniqueConstraint(
            "charger_id", "event_time", "frame_sequence", name="uq_silver_configuration_snapshot"
        ),
        sa.Index(
            "ix_silver_configuration_snapshot_lookup", "charger_id", "event_time", "frame_sequence"
        ),
    )


class SilverObservationProvenance(UUIDPrimaryKeyMixin, Base):
    """Lineage bridge mapping every Silver cell back to Bronze position, file, and raw value."""

    __tablename__ = "silver_observation_provenance"

    silver_table_name: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    silver_record_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=False, index=True
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_source_frame.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bronze_row_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True, index=True
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    canonical_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    transformation_applied: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    masked_sentinel: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)

    __table_args__ = (
        sa.Index("ix_silver_provenance_record", "silver_table_name", "silver_record_id"),
        sa.Index("ix_silver_provenance_frame", "frame_id"),
    )


class SilverNormalizationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lifecycle and accounting record for a file normalization run."""

    __tablename__ = "silver_normalization_run"

    file_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("telemetry_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="STARTED")
    frames_input: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    frames_normalized: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    frames_with_warnings: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    frames_failed: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    records_created_by_table: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    sentinels_masked_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    conflicts_detected_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
