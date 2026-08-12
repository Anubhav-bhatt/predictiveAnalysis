"""Frame reconstruction algorithm (Phase 1D sections 54-64).

The single most important test in this file is
``test_same_timestamp_distinct_frames_are_both_kept``: it pins the behaviour that
``drop_duplicates(timestamp, connector, smr)`` would destroy.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pipelines.frame_reconstruction.models import (
    RECONSTRUCTION_VERSION,
    DuplicateClassification,
    FrameStatus,
    LogicalPosition,
)
from pipelines.frame_reconstruction.topology import TopologyBasis
from tests.fixtures.frames import CHARGER, T0, make_row, normal_frame_rows, run_reconstruction

# ---------------------------------------------------------------------------
# Section 54 - the normal frame
# ---------------------------------------------------------------------------


def test_normal_eight_row_frame_is_one_complete_canonical_frame() -> None:
    outcome = run_reconstruction(normal_frame_rows())

    assert outcome.metrics.raw_rows == 8
    assert outcome.metrics.unique_timestamps == 1
    assert outcome.metrics.expected_positions_per_frame == 8
    assert len(outcome.frames) == 1

    frame = outcome.frames[0]
    assert frame.status is FrameStatus.COMPLETE
    assert frame.duplicate_classification is DuplicateClassification.UNIQUE
    assert frame.frame_sequence == 0
    assert frame.observed_position_count == 8
    assert frame.missing_position_count == 0
    assert frame.completeness_percentage == pytest.approx(100.0)
    assert frame.is_canonical is True
    assert len(frame.rows) == 8

    assert outcome.metrics.canonical_frames == 1
    assert outcome.metrics.rows_unassigned == 0
    assert outcome.metrics.reconstruction_version == RECONSTRUCTION_VERSION


def test_topology_comes_from_charger_configuration() -> None:
    outcome = run_reconstruction(normal_frame_rows())
    assert outcome.topology.basis is TopologyBasis.CHARGER_CONFIGURATION
    assert outcome.topology.expected_position_count == 8
    assert outcome.topology.connectors == ("1", "2")
    assert outcome.topology.smrs == ("1", "2", "3", "4")


def test_topology_is_not_hard_coded_to_two_by_four() -> None:
    """A 3x2 charger must reconstruct as 6 positions, not 8 (section 6)."""
    rows = normal_frame_rows(connectors=("1", "2", "3"), smrs=("1", "2"))
    outcome = run_reconstruction(rows, connector_count=3, smr_count=2)

    assert outcome.topology.expected_position_count == 6
    assert len(outcome.frames) == 1
    assert outcome.frames[0].status is FrameStatus.COMPLETE


def test_topology_falls_back_to_observed_when_unconfigured() -> None:
    outcome = run_reconstruction(
        normal_frame_rows(), connector_count=None, smr_count=None
    )
    assert outcome.topology.basis is TopologyBasis.OBSERVED_STABLE
    assert outcome.topology.expected_position_count == 8


# ---------------------------------------------------------------------------
# Section 55, 56 - full replay
# ---------------------------------------------------------------------------


def test_sixteen_identical_rows_yield_one_canonical_and_one_full_replay() -> None:
    outcome = run_reconstruction(normal_frame_rows() * 2)

    assert outcome.metrics.raw_rows == 16
    assert len(outcome.frames) == 2

    canonical, replay = outcome.frames
    assert canonical.frame_sequence == 0
    assert canonical.duplicate_classification is DuplicateClassification.UNIQUE
    assert canonical.status is FrameStatus.COMPLETE

    assert replay.frame_sequence == 1
    assert replay.duplicate_classification is DuplicateClassification.FULL_FRAME_REPLAY
    assert replay.replay_of_sequence == 0
    assert replay.status is FrameStatus.COMPLETE, "a replay can be structurally complete"
    assert replay.is_canonical is False

    # Identical payloads must fingerprint identically.
    assert canonical.frame_fingerprint == replay.frame_fingerprint

    assert outcome.metrics.canonical_frames == 1
    assert outcome.metrics.full_frame_replays == 1
    # Provenance is retained - the replay's rows are not discarded.
    assert len(replay.rows) == 8


def test_sixty_four_row_timestamp_yields_one_canonical_and_seven_replays() -> None:
    """Section 56: the known 64-row anomaly, with identical payloads."""
    outcome = run_reconstruction(normal_frame_rows() * 8)

    assert outcome.metrics.raw_rows == 64
    assert outcome.metrics.unique_timestamps == 1
    assert len(outcome.frames) == 8

    assert outcome.metrics.canonical_frames == 1
    assert outcome.metrics.full_frame_replays == 7
    assert all(frame.status is FrameStatus.COMPLETE for frame in outcome.frames)
    assert [frame.frame_sequence for frame in outcome.frames] == list(range(8))

    # Every one of the 64 rows is accounted for.
    assert outcome.metrics.rows_assigned == 64
    assert outcome.metrics.rows_unassigned == 0


def test_sixty_four_rows_with_differing_payloads_are_not_replays() -> None:
    """Section 56: if payloads differ, they are distinct frames, not replays."""
    rows = []
    for index in range(8):
        rows.extend(normal_frame_rows(output_current=f"{10 + index}.0"))

    outcome = run_reconstruction(rows)
    assert len(outcome.frames) == 8
    assert outcome.metrics.full_frame_replays == 0
    assert outcome.metrics.same_timestamp_distinct_frames == 7
    assert outcome.metrics.canonical_frames == 8


# ---------------------------------------------------------------------------
# Section 57 - same-timestamp distinct frames. THE critical case.
# ---------------------------------------------------------------------------


def test_same_timestamp_distinct_frames_are_both_kept() -> None:
    """Two real state transitions in one second must both survive.

    This is the case a naive drop_duplicates on
    (timestamp, connector, smr) would silently destroy.
    """
    first = normal_frame_rows(connector_status="Idle", ocpp_state="Available")
    second = normal_frame_rows(
        connector_status="Charge Finished", ocpp_state="Finishing"
    )
    outcome = run_reconstruction(first + second)

    assert outcome.metrics.raw_rows == 16
    assert len(outcome.frames) == 2

    frame0, frame1 = outcome.frames
    assert frame0.event_time == frame1.event_time == T0
    assert (frame0.frame_sequence, frame1.frame_sequence) == (0, 1)

    assert frame0.duplicate_classification is DuplicateClassification.UNIQUE
    assert frame1.duplicate_classification is (
        DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME
    )
    assert frame1.replay_of_sequence is None, "a distinct frame is not a replay"

    # Both are canonical: Phase 1E must consume both.
    assert frame0.is_canonical and frame1.is_canonical
    assert outcome.metrics.canonical_frames == 2
    assert outcome.metrics.full_frame_replays == 0
    assert outcome.metrics.collision_timestamps == 1

    # Different payload means different fingerprint.
    assert frame0.frame_fingerprint != frame1.frame_fingerprint

    # The changed positions are recorded so the API can show what differed.
    assert frame1.detail["differing_positions"]
    assert len(frame1.detail["differing_positions"]) == 8  # type: ignore[arg-type]


def test_no_fabricated_subsecond_timestamps() -> None:
    """Section 18/9: identity is event_time + frame_sequence, never fake millis."""
    first = normal_frame_rows(ocpp_state="Available")
    second = normal_frame_rows(ocpp_state="Finishing")
    outcome = run_reconstruction(first + second)

    for frame in outcome.frames:
        assert frame.event_time == T0
        assert frame.event_time.microsecond == 0, "no synthetic sub-second component"

    # Distinguished purely by sequence.
    assert {frame.frame_sequence for frame in outcome.frames} == {0, 1}


def test_a_single_differing_field_still_makes_a_distinct_frame() -> None:
    """Strict equality: one changed signal value is a real difference."""
    first = normal_frame_rows(rsrp="-83")
    second = normal_frame_rows(rsrp="-87")
    outcome = run_reconstruction(first + second)

    assert outcome.metrics.same_timestamp_distinct_frames == 1
    assert outcome.metrics.full_frame_replays == 0


# ---------------------------------------------------------------------------
# Section 58 - partial second frame
# ---------------------------------------------------------------------------


def test_partial_second_frame_is_not_forced_into_a_complete_frame() -> None:
    """8 complete rows + 4 repeated positions (section 10, 58)."""
    rows = normal_frame_rows() + normal_frame_rows(connectors=("1",))
    outcome = run_reconstruction(rows)

    assert outcome.metrics.raw_rows == 12
    assert len(outcome.frames) == 2

    complete, fragment = outcome.frames
    assert complete.status is FrameStatus.COMPLETE
    assert complete.observed_position_count == 8

    # The fragment holds only the 4 positions that genuinely repeated. No rows
    # were invented to round it up to 8.
    assert fragment.observed_position_count == 4
    assert fragment.missing_position_count == 4
    assert fragment.status is FrameStatus.PARTIAL
    assert fragment.duplicate_classification is (
        DuplicateClassification.PARTIAL_FRAME_REPLAY
    )
    assert fragment.replay_of_sequence == 0
    assert fragment.is_canonical is False


def test_uneven_occurrences_produce_one_complete_and_one_partial() -> None:
    """Section 10's worked example."""
    rows = normal_frame_rows() + normal_frame_rows(
        connectors=("1",), output_current="99.0"
    )
    outcome = run_reconstruction(rows)

    statuses = [frame.status for frame in outcome.frames]
    assert statuses == [FrameStatus.COMPLETE, FrameStatus.PARTIAL]
    # Differing payload means the fragment is a distinct observation, not a replay.
    assert outcome.frames[1].duplicate_classification is (
        DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME
    )


# ---------------------------------------------------------------------------
# Section 59, 60 - missing and unexpected positions
# ---------------------------------------------------------------------------


def test_seven_rows_is_partial_with_the_missing_position_named() -> None:
    rows = normal_frame_rows()[:-1]  # drop C2/S4
    outcome = run_reconstruction(rows)

    assert len(outcome.frames) == 1
    frame = outcome.frames[0]
    assert frame.status is FrameStatus.PARTIAL
    assert frame.observed_position_count == 7
    assert frame.missing_position_count == 1
    assert frame.missing_positions == (LogicalPosition(connector_id="2", smr_id="4"),)
    assert "FRAME_MISSING_POSITION" in {issue.value for issue in frame.issues}


def test_unexpected_smr_is_retained_and_flagged() -> None:
    """Section 21: SMR 9 is reported, never discarded."""
    rows = normal_frame_rows() + [make_row(connector="1", smr="9")]
    outcome = run_reconstruction(rows)

    frame = outcome.frames[0]
    assert frame.unexpected_position_count == 1
    assert frame.unexpected_positions == (LogicalPosition(connector_id="1", smr_id="9"),)
    assert frame.status is FrameStatus.MALFORMED
    assert "FRAME_UNEXPECTED_POSITION" in {issue.value for issue in frame.issues}

    # The row survives: 9 rows in, 9 rows assigned.
    assert outcome.metrics.rows_assigned == 9
    assert outcome.metrics.rows_unassigned == 0


def test_severely_incomplete_frame() -> None:
    rows = normal_frame_rows()[:2]  # 2 of 8 positions
    outcome = run_reconstruction(rows)
    assert outcome.frames[0].status is FrameStatus.SEVERELY_INCOMPLETE


# ---------------------------------------------------------------------------
# Section 61 - missing entity identity
# ---------------------------------------------------------------------------


def test_row_without_connector_becomes_unassigned_not_lost() -> None:
    rows = normal_frame_rows() + [make_row(connector=None, smr="1")]
    outcome = run_reconstruction(rows)

    assert outcome.metrics.raw_rows == 9
    assert outcome.metrics.rows_unassigned == 1
    assert outcome.metrics.rows_assigned == 8
    assert len(outcome.unassigned_rows) == 1
    # Provenance survives so the row can be traced back to the file.
    assert outcome.unassigned_rows[0].source_row_number == 8
    assert outcome.unassigned_rows[0].unassigned is True


def test_row_without_smr_becomes_unassigned() -> None:
    outcome = run_reconstruction(normal_frame_rows() + [make_row(connector="1", smr="")])
    assert outcome.metrics.rows_unassigned == 1


def test_row_without_event_time_is_undatable_but_retained() -> None:
    rows = normal_frame_rows() + [make_row(connector="1", smr="1")]
    times = [T0] * 8 + [None]
    outcome = run_reconstruction(rows, event_times=times)

    assert outcome.metrics.rows_unassigned == 1
    assert len(outcome.unassigned_rows) == 1


# ---------------------------------------------------------------------------
# Section 63, 64 - determinism and idempotency of the algorithm
# ---------------------------------------------------------------------------


def test_reconstruction_is_deterministic_across_runs() -> None:
    rows = (
        normal_frame_rows()
        + normal_frame_rows(ocpp_state="Finishing")
        + normal_frame_rows(connectors=("1",))
    )
    first = run_reconstruction(rows)
    second = run_reconstruction(rows)

    assert [f.frame_sequence for f in first.frames] == [
        f.frame_sequence for f in second.frames
    ]
    assert [f.frame_fingerprint for f in first.frames] == [
        f.frame_fingerprint for f in second.frames
    ]
    assert [f.duplicate_classification for f in first.frames] == [
        f.duplicate_classification for f in second.frames
    ]
    assert [f.status for f in first.frames] == [f.status for f in second.frames]


def test_fingerprint_ignores_row_order_within_a_frame() -> None:
    """A frame's identity must not depend on how its rows were interleaved."""
    forward = run_reconstruction(normal_frame_rows())
    shuffled_rows = list(reversed(normal_frame_rows()))
    reversed_outcome = run_reconstruction(shuffled_rows)

    assert (
        forward.frames[0].frame_fingerprint
        == reversed_outcome.frames[0].frame_fingerprint
    )


def test_occurrence_index_follows_source_order() -> None:
    first = normal_frame_rows(output_current="1.0")
    second = normal_frame_rows(output_current="2.0")
    outcome = run_reconstruction(first + second)

    frame0, frame1 = outcome.frames
    # Frame 0 must own the earlier source rows.
    assert frame0.source_order_max < frame1.source_order_min


# ---------------------------------------------------------------------------
# Multi-timestamp behaviour
# ---------------------------------------------------------------------------


def test_multiple_timestamps_each_produce_their_own_frame() -> None:
    rows = []
    for minute in range(5):
        stamp = T0 + dt.timedelta(minutes=minute)
        rows.extend(normal_frame_rows(event_time=stamp))

    outcome = run_reconstruction(rows)
    assert outcome.metrics.unique_timestamps == 5
    assert len(outcome.frames) == 5
    assert outcome.metrics.canonical_frames == 5
    assert outcome.metrics.full_frame_replays == 0
    # Identical payloads at *different* timestamps are not replays of each other.
    assert outcome.metrics.same_timestamp_distinct_frames == 0


def test_frames_are_ordered_chronologically() -> None:
    rows = []
    for minute in (3, 1, 2):
        rows.extend(normal_frame_rows(event_time=T0 + dt.timedelta(minutes=minute)))
    outcome = run_reconstruction(rows)

    times = [frame.event_time for frame in outcome.frames]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# Safety valve
# ---------------------------------------------------------------------------


def test_absurd_occurrence_count_is_ambiguous_not_unbounded() -> None:
    """A corrupt file must not be able to generate unbounded frames."""
    outcome = run_reconstruction(
        normal_frame_rows() * 10, max_frames_per_timestamp=4
    )
    assert len(outcome.frames) == 1
    assert outcome.frames[0].status is FrameStatus.AMBIGUOUS
    assert "AMBIGUOUS_FRAME_BOUNDARY" in {
        issue.value for issue in outcome.frames[0].issues
    }


def test_charger_id_is_part_of_frame_identity() -> None:
    rows = normal_frame_rows() + normal_frame_rows(charger_id="OTHER_CHARGER")
    outcome = run_reconstruction(rows)

    # Two chargers at the same timestamp are two separate groups, not replays.
    assert len(outcome.frames) == 2
    assert {frame.charger_id for frame in outcome.frames} == {CHARGER, "OTHER_CHARGER"}
    assert all(frame.frame_sequence == 0 for frame in outcome.frames)
    assert outcome.metrics.full_frame_replays == 0
