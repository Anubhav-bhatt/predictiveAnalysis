"""Replay and collision classification (Phase 1D sections 15-20).

This is the module the whole phase exists for. Several frames can share one event
timestamp, and they fall into genuinely different cases that must not be conflated:

``FULL_FRAME_REPLAY``
    Same payload as an earlier frame at this timestamp. Adds no observation, so
    Phase 1E skips it - but its provenance is kept, because "this frame arrived 8
    times" is an auditable fact.

``PARTIAL_FRAME_REPLAY``
    A fragment whose positions all match the canonical frame. A partial
    retransmission, not a new observation.

``SAME_TIMESTAMP_DISTINCT_FRAME``
    Same timestamp, **different telemetry**. A real state transition the charger
    reported within one second. Both frames are canonical and both are kept. This
    is precisely the case ``drop_duplicates(timestamp, connector, smr)`` would
    destroy.

The canonical frame within a group is chosen deterministically: lowest frame
sequence, which by construction is the earliest source row order (section 33). No
tie is ever broken randomly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipelines.frame_reconstruction.canonical_serializer import CanonicalSerializer
from pipelines.frame_reconstruction.frame_builder import FrameCandidate
from pipelines.frame_reconstruction.models import (
    DuplicateClassification,
    FrameStatus,
    LogicalPosition,
    ReconstructionIssueType,
)

__all__ = ["ClassifiedFrame", "classify_group"]


@dataclass(frozen=True, slots=True)
class ClassifiedFrame:
    """A candidate with its fingerprint and duplicate verdict resolved."""

    candidate: FrameCandidate
    frame_fingerprint: str
    classification: DuplicateClassification
    replay_of_sequence: int | None
    issues: tuple[ReconstructionIssueType, ...]
    #: Positions whose payload differs from the canonical frame's. Populated for
    #: distinct frames so the API can report *what* changed without re-reading
    #: the raw file.
    differing_positions: tuple[LogicalPosition, ...] = ()
    note: str | None = None

    @property
    def is_canonical(self) -> bool:
        return self.classification in {
            DuplicateClassification.UNIQUE,
            DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
        }


def _position_fingerprints(candidate: FrameCandidate) -> dict[str, str]:
    return {
        str(position): row.row_fingerprint
        for position, row in candidate.rows_by_position.items()
    }


def _compare(
    subject: Mapping[LogicalPosition, str], canonical: Mapping[LogicalPosition, str]
) -> tuple[tuple[LogicalPosition, ...], tuple[LogicalPosition, ...]]:
    """Split shared positions into matching and differing.

    Comparison is on row fingerprints, which are already schema-aware canonical
    hashes - so this is strict semantic equality with no float tolerance. A
    tolerance here would hide small genuine charger-reported changes (section 48
    of the phase brief); tolerance belongs to later analytics, not to replay
    detection.
    """
    shared = set(subject) & set(canonical)
    matching = tuple(sorted(p for p in shared if subject[p] == canonical[p]))
    differing = tuple(sorted(p for p in shared if subject[p] != canonical[p]))
    return matching, differing


def classify_group(
    candidates: Sequence[FrameCandidate],
    *,
    serializer: type[CanonicalSerializer] | CanonicalSerializer = CanonicalSerializer,
) -> list[ClassifiedFrame]:
    """Classify every frame at one event timestamp.

    Frames are processed in sequence order, so a frame is only ever compared
    against frames that preceded it in source order.
    """
    fingerprint_of = (
        serializer.frame_fingerprint
        if isinstance(serializer, CanonicalSerializer)
        else CanonicalSerializer.frame_fingerprint
    )

    results: list[ClassifiedFrame] = []
    #: frame fingerprint -> sequence of the first frame that carried it.
    seen_fingerprints: dict[str, int] = {}
    #: Payload of each accepted canonical frame, for fragment comparison.
    canonical_payloads: dict[int, Mapping[LogicalPosition, str]] = {}

    for candidate in candidates:
        payload = {
            position: row.row_fingerprint
            for position, row in candidate.rows_by_position.items()
        }
        fingerprint = fingerprint_of(_position_fingerprints(candidate))
        issues: list[ReconstructionIssueType] = []

        # Structural issues are independent of duplication.
        if candidate.unexpected_positions:
            issues.append(ReconstructionIssueType.FRAME_UNEXPECTED_POSITION)
        if candidate.status is FrameStatus.AMBIGUOUS:
            issues.append(ReconstructionIssueType.AMBIGUOUS_FRAME_BOUNDARY)
        elif candidate.missing_positions:
            issues.append(ReconstructionIssueType.FRAME_MISSING_POSITION)

        # --- the first frame at a timestamp is canonical by definition -----
        if not results:
            seen_fingerprints[fingerprint] = candidate.sequence
            canonical_payloads[candidate.sequence] = payload
            results.append(
                ClassifiedFrame(
                    candidate=candidate,
                    frame_fingerprint=fingerprint,
                    classification=DuplicateClassification.UNIQUE,
                    replay_of_sequence=None,
                    issues=tuple(issues),
                    note=candidate.note,
                )
            )
            continue

        # --- whole-payload match against any earlier frame -----------------
        if fingerprint in seen_fingerprints:
            issues.append(ReconstructionIssueType.FULL_FRAME_REPLAY)
            results.append(
                ClassifiedFrame(
                    candidate=candidate,
                    frame_fingerprint=fingerprint,
                    classification=DuplicateClassification.FULL_FRAME_REPLAY,
                    replay_of_sequence=seen_fingerprints[fingerprint],
                    issues=tuple(issues),
                    note=candidate.note,
                )
            )
            continue

        # --- compare against the earliest canonical frame ------------------
        canonical_sequence = min(canonical_payloads)
        canonical_payload = canonical_payloads[canonical_sequence]
        matching, differing = _compare(payload, canonical_payload)

        if differing:
            # Genuinely different telemetry at the same second. Both frames stand.
            issues.append(ReconstructionIssueType.SAME_TIMESTAMP_DISTINCT_FRAME)
            seen_fingerprints[fingerprint] = candidate.sequence
            canonical_payloads[candidate.sequence] = payload
            results.append(
                ClassifiedFrame(
                    candidate=candidate,
                    frame_fingerprint=fingerprint,
                    classification=DuplicateClassification.SAME_TIMESTAMP_DISTINCT_FRAME,
                    replay_of_sequence=None,
                    issues=tuple(issues),
                    differing_positions=differing,
                    note=candidate.note,
                )
            )
            continue

        # Nothing differs, but the fingerprints did not match - so this frame is a
        # subset of the canonical one: a partial retransmission.
        if matching:
            issues.append(ReconstructionIssueType.PARTIAL_FRAME_REPLAY)
            results.append(
                ClassifiedFrame(
                    candidate=candidate,
                    frame_fingerprint=fingerprint,
                    classification=DuplicateClassification.PARTIAL_FRAME_REPLAY,
                    replay_of_sequence=canonical_sequence,
                    issues=tuple(issues),
                    note=(
                        candidate.note
                        or f"{len(matching)} position(s) repeat the canonical frame's "
                        f"payload with no contradicting value"
                    ),
                )
            )
            continue

        # No shared positions at all: disjoint from the canonical frame. Cannot be
        # called a replay, and cannot be shown to be a distinct observation either.
        issues.append(ReconstructionIssueType.AMBIGUOUS_FRAME_BOUNDARY)
        seen_fingerprints[fingerprint] = candidate.sequence
        canonical_payloads[candidate.sequence] = payload
        results.append(
            ClassifiedFrame(
                candidate=candidate,
                frame_fingerprint=fingerprint,
                classification=DuplicateClassification.AMBIGUOUS,
                replay_of_sequence=None,
                issues=tuple(issues),
                note="shares no logical position with the canonical frame at this "
                "event timestamp; frame boundary cannot be confirmed",
            )
        )

    return results
