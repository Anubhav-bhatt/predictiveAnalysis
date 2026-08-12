"""Locate the structurally significant columns in an untrusted wide CSV.

Profiling needs to know which of the 449 columns carries the event time, the
charger id, the connector number and so on.  Column names are explicitly
untrusted (section 20), so resolution is deterministic and auditable rather than
clever: an ordered list of exact canonical names first, then anchored regex
patterns, with the earliest source position winning ties.

Every resolution records *which* column was chosen, so a profile can always be
explained.  Nothing here guesses semantics for the other ~440 columns; that is
the data dictionary's job.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "ColumnRole",
    "ResolvedColumn",
    "RoleResolution",
    "resolve_roles",
]


class ColumnRole(StrEnum):
    EVENT_TIME = "EVENT_TIME"
    CHARGER_ID = "CHARGER_ID"
    OCPP_ID = "OCPP_ID"
    CONNECTOR = "CONNECTOR"
    SMR = "SMR"
    SESSION_ID = "SESSION_ID"


@dataclass(frozen=True, slots=True)
class _RoleSpec:
    #: Canonical names tried in order; an exact hit always beats a pattern hit.
    exact: tuple[str, ...]
    #: Anchored fallbacks for vendor variations we have not catalogued.
    patterns: tuple[str, ...] = ()
    #: Roles without which the file cannot be profiled meaningfully.
    required: bool = False


ROLE_SPECS: Final[Mapping[ColumnRole, _RoleSpec]] = {
    ColumnRole.EVENT_TIME: _RoleSpec(
        exact=(
            "event_time",
            "event_timestamp",
            "event_date_time",
            "log_time",
            "log_timestamp",
            "timestamp",
            "date_time",
        ),
        # Deliberately anchored: "session_start_time" must not win this role.
        patterns=(r"^event_?time.*$", r"^log_?time.*$", r"^date_?time$", r"^time_?stamp$"),
        required=True,
    ),
    ColumnRole.CHARGER_ID: _RoleSpec(
        exact=(
            "charger_id",
            "charger_serial_number",
            "charge_point_id",
            "chargepoint_id",
            "cp_id",
            "charger_serial",
        ),
        patterns=(r"^charger_?(id|serial.*)$", r"^charge_?point_?id$"),
        required=True,
    ),
    ColumnRole.OCPP_ID: _RoleSpec(
        exact=("ocpp_id", "ocpp_identity", "charge_box_id", "charge_box_identity"),
        patterns=(r"^ocpp_?(id|identity)$", r"^charge_?box_?id.*$"),
    ),
    ColumnRole.CONNECTOR: _RoleSpec(
        exact=("connector_no", "connector_number", "connector_id", "connector", "connector_index"),
        patterns=(r"^connector(_?(no|num|number|id|index))?$",),
        required=True,
    ),
    ColumnRole.SMR: _RoleSpec(
        exact=("smr_no", "smr_number", "smr_id", "smr", "smr_index", "module_no"),
        patterns=(r"^smr(_?(no|num|number|id|index))?$",),
        required=True,
    ),
    ColumnRole.SESSION_ID: _RoleSpec(
        exact=("session_id", "transaction_id", "charging_session_id", "txn_id"),
        patterns=(r"^(charging_)?session_?id$", r"^transaction_?id$"),
    ),
}


@dataclass(frozen=True, slots=True)
class ResolvedColumn:
    role: ColumnRole
    canonical_name: str
    source_name: str
    position: int
    #: "exact" or "pattern:<regex>" - kept so a profile can justify itself.
    matched_by: str


@dataclass(frozen=True, slots=True)
class RoleResolution:
    resolved: Mapping[ColumnRole, ResolvedColumn]
    missing_required: tuple[ColumnRole, ...]

    def get(self, role: ColumnRole) -> ResolvedColumn | None:
        return self.resolved.get(role)

    def canonical(self, role: ColumnRole) -> str | None:
        found = self.resolved.get(role)
        return found.canonical_name if found else None

    @property
    def is_profilable(self) -> bool:
        """False when a role we cannot proceed without is absent."""
        return not self.missing_required


def resolve_roles(
    canonical_names: Sequence[str],
    source_names: Sequence[str] | None = None,
) -> RoleResolution:
    """Map structural roles onto concrete columns.

    ``canonical_names`` and ``source_names`` are positionally aligned; the latter
    is only carried through for reporting.
    """
    sources = list(source_names) if source_names is not None else list(canonical_names)
    lookup: dict[str, int] = {}
    for position, name in enumerate(canonical_names):
        # First occurrence wins, so a duplicated name resolves to its earliest
        # position deterministically.
        lookup.setdefault(name, position)

    resolved: dict[ColumnRole, ResolvedColumn] = {}
    missing: list[ColumnRole] = []

    for role, spec in ROLE_SPECS.items():
        match: ResolvedColumn | None = None

        for candidate in spec.exact:
            if candidate in lookup:
                position = lookup[candidate]
                match = ResolvedColumn(
                    role=role,
                    canonical_name=candidate,
                    source_name=sources[position],
                    position=position,
                    matched_by="exact",
                )
                break

        if match is None:
            for pattern in spec.patterns:
                compiled = re.compile(pattern)
                hits = [
                    (position, name)
                    for position, name in enumerate(canonical_names)
                    if compiled.match(name)
                ]
                if hits:
                    position, name = min(hits)
                    match = ResolvedColumn(
                        role=role,
                        canonical_name=name,
                        source_name=sources[position],
                        position=position,
                        matched_by=f"pattern:{pattern}",
                    )
                    break

        if match is not None:
            resolved[role] = match
        elif spec.required:
            missing.append(role)

    return RoleResolution(resolved=resolved, missing_required=tuple(missing))
