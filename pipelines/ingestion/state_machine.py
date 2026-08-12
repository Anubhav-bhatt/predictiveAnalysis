"""Explicit ingestion state machine (section 6).

Transitions are data, not scattered ``if`` statements, so that they can be
asserted in tests and reasoned about in review.  Any move not listed here is a
programming error and raises rather than silently corrupting lifecycle state.

Phase 1A drives the happy path only as far as ``READY_FOR_NORMALIZATION``.
``COMPLETED`` becomes reachable when a later phase performs normalization.
"""

from __future__ import annotations

from collections.abc import Mapping

from backend.app.models.enums import FileStatus

__all__ = [
    "ALLOWED_TRANSITIONS",
    "PHASE_1A_HAPPY_PATH",
    "TERMINAL_STATES",
    "IllegalStateTransition",
    "assert_transition_allowed",
    "can_transition",
    "is_terminal",
    "next_states",
]


class IllegalStateTransition(RuntimeError):
    """Raised when code attempts a lifecycle move the contract does not allow."""

    def __init__(self, current: FileStatus, target: FileStatus) -> None:
        self.current = current
        self.target = target
        allowed = ", ".join(sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset())))
        super().__init__(
            f"Illegal ingestion state transition {current.value} -> {target.value}. "
            f"Allowed from {current.value}: [{allowed or 'none - terminal state'}]"
        )


#: Failure outcomes reachable from any in-flight state.
_FAILURE_EXITS = frozenset({FileStatus.FAILED, FileStatus.QUARANTINED})


ALLOWED_TRANSITIONS: Mapping[FileStatus, frozenset[FileStatus]] = {
    FileStatus.DISCOVERED: (
        frozenset({FileStatus.REGISTERED, FileStatus.DUPLICATE}) | _FAILURE_EXITS
    ),
    FileStatus.REGISTERED: frozenset({FileStatus.LANDING, FileStatus.DUPLICATE}) | _FAILURE_EXITS,
    FileStatus.LANDING: frozenset({FileStatus.PROFILING}) | _FAILURE_EXITS,
    FileStatus.PROFILING: frozenset({FileStatus.SCHEMA_VALIDATION}) | _FAILURE_EXITS,
    FileStatus.SCHEMA_VALIDATION: frozenset({FileStatus.QUALITY_VALIDATION}) | _FAILURE_EXITS,
    FileStatus.QUALITY_VALIDATION: (
        frozenset({FileStatus.READY_FOR_NORMALIZATION, FileStatus.PARTIAL}) | _FAILURE_EXITS
    ),
    # Normalization is Phase 1C/1D work; COMPLETED is declared but not driven here.
    FileStatus.READY_FOR_NORMALIZATION: frozenset({FileStatus.COMPLETED, FileStatus.FAILED}),
    FileStatus.PARTIAL: frozenset({FileStatus.READY_FOR_NORMALIZATION}) | _FAILURE_EXITS,
    # Re-driving a failed file restarts it from the registered record; the raw
    # object is immutable so nothing needs to be re-landed.
    FileStatus.FAILED: frozenset({FileStatus.REGISTERED}),
    FileStatus.COMPLETED: frozenset(),
    FileStatus.DUPLICATE: frozenset(),
    FileStatus.QUARANTINED: frozenset(),
}

#: States from which no further progress is possible without operator action.
TERMINAL_STATES: frozenset[FileStatus] = frozenset(
    status for status, targets in ALLOWED_TRANSITIONS.items() if not targets
)

#: The ordered path Phase 1A actually drives.
PHASE_1A_HAPPY_PATH: tuple[FileStatus, ...] = (
    FileStatus.DISCOVERED,
    FileStatus.REGISTERED,
    FileStatus.LANDING,
    FileStatus.PROFILING,
    FileStatus.SCHEMA_VALIDATION,
    FileStatus.QUALITY_VALIDATION,
    FileStatus.READY_FOR_NORMALIZATION,
)


def next_states(current: FileStatus) -> frozenset[FileStatus]:
    return ALLOWED_TRANSITIONS.get(current, frozenset())


def can_transition(current: FileStatus, target: FileStatus) -> bool:
    return target in next_states(current)


def is_terminal(status: FileStatus) -> bool:
    return status in TERMINAL_STATES


def assert_transition_allowed(current: FileStatus, target: FileStatus) -> None:
    """Guard used by the orchestrator before every status write."""
    if not can_transition(current, target):
        raise IllegalStateTransition(current, target)
