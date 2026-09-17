"""Production data contract verification test suite (Phase 5.5).

Verifies that the authoritative field dictionary in `data/dictionaries/` fully
governs all 456 positions of commercial DC fast-charger telemetry
(16092026_170601_charger_status_latest.csv) with zero unmapped columns,
separate identities for repeated headers, sensitive positional fingerprinting,
field-specific sentinel bindings, dynamic topology, and source equivalence.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from backend.app.models.enums import (
    CanonicalDataType,
    FieldClass,
    FieldEntity,
)
from pipelines.frame_reconstruction.models import LogicalPosition
from pipelines.frame_reconstruction.topology import (
    FrameTopologyResolver,
    TopologyBasis,
)
from pipelines.profiling.header_parser import (
    canonicalise,
    compute_fingerprint,
    parse_header,
)
from pipelines.profiling.profiler import profile_file
from pipelines.validation.dictionary import DictionaryRegistry

CSV_PATH = Path("16092026_170601_charger_status_latest.csv")
DICT_DIR = Path("data/dictionaries")
CONTRACTS_DIR = Path("data/contracts")


@pytest.fixture(scope="module")
def registry() -> DictionaryRegistry:
    return DictionaryRegistry.load(DICT_DIR, contracts_dir=CONTRACTS_DIR)


@pytest.fixture(scope="module")
def raw_headers() -> list[str]:
    assert CSV_PATH.exists(), f"Production CSV not found: {CSV_PATH}"
    with CSV_PATH.open(encoding="utf-8", errors="replace") as f:
        return next(csv.reader(f))


# ---------------------------------------------------------------------------
# Gate 2: 456/456 Contract Verification
# ---------------------------------------------------------------------------


def test_456_production_positions_fully_mapped(
    registry: DictionaryRegistry, raw_headers: list[str]
) -> None:
    """Every single source position in the real production header must resolve."""
    assert len(raw_headers) == 456, f"Expected 456 header positions, found {len(raw_headers)}"

    curr_counts: dict[str, int] = {}
    seen_identities: set[tuple[str, int]] = set()
    seen_canonicals: set[str] = set()

    registered_positions = 0
    unmapped_positions = 0
    duplicate_identity_collisions = 0
    canonical_collisions: list[str] = []

    for idx, name in enumerate(raw_headers):
        curr_counts[name] = curr_counts.get(name, 0) + 1
        occ = curr_counts[name]
        identity = (name, occ)

        if identity in seen_identities:
            duplicate_identity_collisions += 1
        seen_identities.add(identity)

        fallback_canon = canonicalise(name, position=idx)
        res = registry.resolve(
            name, occurrence=occ, position=idx, fallback_canonical=fallback_canon
        )

        if res.is_dictionary_mapped:
            registered_positions += 1
        else:
            unmapped_positions += 1

        canon = res.spec.canonical_name
        if canon in seen_canonicals:
            canonical_collisions.append(f"Pos {idx}: {name} (occ {occ}) -> {canon}")
        seen_canonicals.add(canon)

    assert registered_positions == 456
    assert unmapped_positions == 0
    assert duplicate_identity_collisions == 0
    assert not canonical_collisions, f"Canonical collisions detected: {canonical_collisions}"


# ---------------------------------------------------------------------------
# Gate 3: Duplicate Header Handling
# ---------------------------------------------------------------------------


def test_duplicate_header_identity_preserved(registry: DictionaryRegistry) -> None:
    """Pos 143 and Pos 209 of 'Last Charge Session Stop Reason' must resolve separately."""
    header = parse_header(CSV_PATH)
    dup_fields = [f for f in header.fields if f.source_name == "Last Charge Session Stop Reason"]

    assert len(dup_fields) == 2, (
        "Expected exactly 2 occurrences of 'Last Charge Session Stop Reason'"
    )

    f1, f2 = dup_fields[0], dup_fields[1]
    assert f1.position == 143
    assert f1.source_occurrence == 1

    assert f2.position == 209
    assert f2.source_occurrence == 2

    # Direct resolution through registry
    res1 = registry.resolve(
        f1.source_name, occurrence=1, position=143, fallback_canonical=f1.canonical_name
    )
    res2 = registry.resolve(
        f2.source_name, occurrence=2, position=209, fallback_canonical=f2.canonical_name
    )

    assert res1.is_dictionary_mapped is True
    assert res2.is_dictionary_mapped is True

    # Must resolve to distinct explicit canonical names, not pandas .1 or fallback suffixes
    assert res1.spec.canonical_name == "last_charge_session_stop_reason"
    assert res2.spec.canonical_name == "last_charge_session_stop_reason_secondary"
    assert res1.spec.canonical_name != res2.spec.canonical_name
    assert ".1" not in res1.spec.canonical_name
    assert ".1" not in res2.spec.canonical_name

    # Must be explicitly registered by identity
    assert ("Last Charge Session Stop Reason", 1) in registry.by_identity
    assert ("Last Charge Session Stop Reason", 2) in registry.by_identity


# ---------------------------------------------------------------------------
# Gate 7: Schema Fingerprint Sensitivity
# ---------------------------------------------------------------------------


def test_schema_fingerprint_distinguishes_schema_variations(raw_headers: list[str]) -> None:
    """The SHA-256 schema fingerprint must detect every form of structural drift."""
    base_fp = compute_fingerprint(raw_headers)
    assert len(base_fp) == 64

    # 1. Exact schema match
    assert compute_fingerprint(list(raw_headers)) == base_fp

    # 2. Reordered fields
    reordered = list(raw_headers)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert compute_fingerprint(reordered) != base_fp

    # 3. Removed duplicate occurrence
    removed_dup = [h for idx, h in enumerate(raw_headers) if idx != 209]
    assert compute_fingerprint(removed_dup) != base_fp

    # 4. Additional duplicate occurrence
    add_dup = list(raw_headers) + ["Last Charge Session Stop Reason"]
    assert compute_fingerprint(add_dup) != base_fp

    # 5. Renamed field
    renamed = list(raw_headers)
    renamed[10] = "Line 2 Input Current Renamed"
    assert compute_fingerprint(renamed) != base_fp

    # 6. Missing field
    missing = list(raw_headers)
    missing.pop(50)
    assert compute_fingerprint(missing) != base_fp

    # 7. Additional unknown field
    additional = list(raw_headers) + ["Unknown Extra Header"]
    assert compute_fingerprint(additional) != base_fp


# ---------------------------------------------------------------------------
# Gate 5: Sentinel Field-Specificity
# ---------------------------------------------------------------------------


def test_sentinels_are_field_specific_not_global(
    registry: DictionaryRegistry, raw_headers: list[str]
) -> None:
    """Sentinels like 999.0 and -150.0 must be bound strictly to physical temperature sensors."""
    curr_counts: dict[str, int] = {}
    sentinel_fields: dict[str, list[str]] = {}

    for idx, name in enumerate(raw_headers):
        curr_counts[name] = curr_counts.get(name, 0) + 1
        occ = curr_counts[name]
        res = registry.resolve(
            name, occurrence=occ, position=idx, fallback_canonical=canonicalise(name, position=idx)
        )
        if res.spec.sentinel_values:
            sentinel_fields[name] = [s.value for s in res.spec.sentinel_values]

    # Exactly 8 physical temperature sensors have sentinels
    assert len(sentinel_fields) == 8, (
        f"Unexpected fields with sentinels: {list(sentinel_fields.keys())}"
    )

    assert "Gun Temp Dc+" in sentinel_fields
    assert "Gun Temp Dc-" in sentinel_fields
    assert "Rectifier Internal Temp" in sentinel_fields
    assert "SMR DcDc Temperature" in sentinel_fields
    assert "SMR Pfc Temperature" in sentinel_fields
    assert "SMR RectifierinternalTemp" in sentinel_fields
    assert "SMRDCDCTemperature" in sentinel_fields
    assert "SMRPFCTemperature" in sentinel_fields

    # Assert alarms, counters, and disconnect flags do NOT have thermocouple sentinels
    for invalid_name in (
        "GUN Temperature Sensor Disconnect",
        "Gun DC+ Temp Sensor Disconnect",
        "Gun Over Temperature Counter",
        "SMR Over Temperature",
        "Line 1 Over Voltage",
        "Ground resistance value",
    ):
        assert invalid_name not in sentinel_fields, f"Bogus sentinel on {invalid_name}"


# ---------------------------------------------------------------------------
# Gate 9: Field-Class Semantics
# ---------------------------------------------------------------------------


def test_field_class_authoritative_semantics(
    registry: DictionaryRegistry, raw_headers: list[str]
) -> None:
    """Discrete alarm flags must not carry physical units; resistance telemetry is CONTINUOUS."""
    curr_counts: dict[str, int] = {}

    for idx, name in enumerate(raw_headers):
        curr_counts[name] = curr_counts.get(name, 0) + 1
        occ = curr_counts[name]
        res = registry.resolve(
            name, occurrence=occ, position=idx, fallback_canonical=canonicalise(name, position=idx)
        )
        spec = res.spec

        # Alarm flags must not have units like V, °C, rpm, kWh
        if spec.field_class == FieldClass.ALARM_FLAG:
            assert spec.unit is None, f"Alarm flag {name} must have unit=None, got {spec.unit}"
            assert spec.data_type == CanonicalDataType.ENUM

        # Resistance telemetry must be continuous float
        if name in (
            "DC + Insulation Resistance",
            "DC - Insulation Resistance",
            "Calculated Insulation Resistance",
            "Ground resistance value",
        ):
            assert spec.field_class == FieldClass.CONTINUOUS_TELEMETRY
            assert spec.unit == "kOhm"
            assert spec.data_type == CanonicalDataType.FLOAT

        # Charging Time must be session duration
        if name == "Charging Time":
            assert spec.entity == FieldEntity.SESSION
            assert spec.field_class == FieldClass.SESSION_ATTRIBUTE
            assert spec.data_type == CanonicalDataType.FLOAT


# ---------------------------------------------------------------------------
# Gate 12: Dynamic Topology Regression
# ---------------------------------------------------------------------------


def test_dynamic_topology_supports_heterogeneous_fleet() -> None:
    """FrameTopologyResolver must handle varied connector and SMR counts dynamically."""
    resolver = FrameTopologyResolver(default_connector_count=2, default_smr_count=4)

    # 1x1 topology (Fleet depot / AC post)
    t1 = resolver.from_configuration(
        connector_count=1, smr_count=1, observed_connectors=["1"], observed_smrs=["1"]
    )
    assert t1 is not None
    assert t1.expected_position_count == 1

    # 2x6 topology (120 kW dual gun)
    t2 = resolver.from_configuration(
        connector_count=2,
        smr_count=6,
        observed_connectors=["1", "2"],
        observed_smrs=["1", "2", "3", "4", "5", "6"],
    )
    assert t2 is not None
    assert t2.expected_position_count == 12

    # 3x2 topology (Triple gun hub)
    t3 = resolver.from_configuration(
        connector_count=3,
        smr_count=2,
        observed_connectors=["1", "2", "3"],
        observed_smrs=["1", "2"],
    )
    assert t3 is not None
    assert t3.expected_position_count == 6

    # 2x10 topology (High capacity 240 kW bank)
    t4 = resolver.from_configuration(
        connector_count=2,
        smr_count=10,
        observed_connectors=["1", "2"],
        observed_smrs=[str(i) for i in range(1, 11)],
    )
    assert t4 is not None
    assert t4.expected_position_count == 20

    # Observed-stable sparse topology
    sparse_obs = {
        LogicalPosition(connector_id="1", smr_id="1"): 10,
        LogicalPosition(connector_id="1", smr_id="2"): 10,
        LogicalPosition(connector_id="2", smr_id="1"): 10,
        LogicalPosition(connector_id="2", smr_id="2"): 10,
    }
    t_sparse = resolver.from_observation(sparse_obs, group_total=10)
    assert t_sparse is not None
    assert t_sparse.expected_position_count == 4
    assert t_sparse.basis == TopologyBasis.OBSERVED_STABLE


# ---------------------------------------------------------------------------
# Gate 15: Source Equivalence
# ---------------------------------------------------------------------------


def test_source_equivalence_filesystem_and_manual_upload(tmp_path: Path) -> None:
    """Identical telemetry bytes must yield identical profiling metrics across sources."""
    settings = get_settings()

    path_fs = CSV_PATH
    path_manual = tmp_path / "manual_upload_copy.csv"
    path_manual.write_bytes(path_fs.read_bytes())

    prof_fs = profile_file(
        path_fs,
        timestamp_formats=settings.ingest.timestamp_formats,
        source_timezone=settings.fleet.default_source_timezone,
        sentinel_values=settings.ingest.global_sentinel_values,
    )
    prof_manual = profile_file(
        path_manual,
        timestamp_formats=settings.ingest.timestamp_formats,
        source_timezone=settings.fleet.default_source_timezone,
        sentinel_values=settings.ingest.global_sentinel_values,
    )

    assert prof_fs.row_count == prof_manual.row_count == 10000
    assert prof_fs.column_count == prof_manual.column_count == 456
    assert (
        prof_fs.duplicates.exact_duplicate_rows == prof_manual.duplicates.exact_duplicate_rows == 53
    )
    assert (
        prof_fs.duplicates.conflicting_logical_groups
        == prof_manual.duplicates.conflicting_logical_groups
        == 0
    )
    assert prof_fs.timestamps.unique_count == prof_manual.timestamps.unique_count == 700
    assert prof_fs.header.header_fingerprint == prof_manual.header.header_fingerprint
