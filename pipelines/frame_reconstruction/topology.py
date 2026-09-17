"""Expected frame topology (Phase 1D section 6).

The known charger reports 2 connectors x 4 SMRs = 8 logical positions per frame,
but **that shape is not hard-coded anywhere in this module.** Other charger models
differ, and a platform that assumed 2x4 would silently mis-reconstruct every one of
them.

Resolution precedence, highest first:

1. **Charger configuration** - ``expected_connector_count`` / ``expected_smr_count``
   on the charger registry row. An operator's declared expectation wins.
2. **Configured global default** - ``CPI_INGEST_EXPECTED_CONNECTOR_COUNT`` /
   ``..._SMR_COUNT``.
3. **Observed stable topology** - the identities actually seen across the file,
   accepted only when they look stable (see below).

The third tier exists so an unconfigured charger still reconstructs, but it is
guarded: topology is derived from identities observed across the **whole file**,
never from a single timestamp group. One malformed 64-row timestamp must not be
able to redefine what a frame is (section 6).

The resolver produces the *cross product* of expected connectors and SMRs. Where a
charger genuinely has a sparse matrix - not every SMR wired to every connector -
the observed-topology tier narrows it to the pairs actually seen, which is
recorded in ``basis`` so the decision is auditable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pipelines.frame_reconstruction.models import LogicalPosition

__all__ = ["FrameTopology", "TopologyBasis", "FrameTopologyResolver"]


class TopologyBasis(StrEnum):
    """Which precedence tier produced the topology - recorded, never guessed at."""

    CHARGER_CONFIGURATION = "CHARGER_CONFIGURATION"
    CONFIGURED_DEFAULT = "CONFIGURED_DEFAULT"
    OBSERVED_STABLE = "OBSERVED_STABLE"
    #: Nothing usable: no configuration and no coherent observation.
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class FrameTopology:
    """The set of logical positions one frame is expected to contain."""

    positions: frozenset[LogicalPosition]
    connectors: tuple[str, ...]
    smrs: tuple[str, ...]
    basis: TopologyBasis
    #: True when the position set is the full connector x SMR cross product.
    is_full_matrix: bool = True
    note: str | None = None

    @property
    def expected_position_count(self) -> int:
        return len(self.positions)

    @property
    def is_resolved(self) -> bool:
        return bool(self.positions)

    def describe(self) -> str:
        return (
            f"{len(self.connectors)} connectors x {len(self.smrs)} SMRs "
            f"= {self.expected_position_count} positions ({self.basis.value})"
        )


def _cross(connectors: Sequence[str], smrs: Sequence[str]) -> frozenset[LogicalPosition]:
    return frozenset(
        LogicalPosition(connector_id=connector, smr_id=smr)
        for connector in connectors
        for smr in smrs
    )


def _sorted_identities(values: Iterable[str]) -> tuple[str, ...]:
    """Sort identities numerically when they all look numeric, else lexically.

    Keeps ``2`` before ``10`` for the common numeric case without assuming
    identities are numbers at all.
    """
    items = sorted({value for value in values if value})
    if all(item.isdigit() for item in items):
        return tuple(sorted(items, key=int))
    return tuple(items)


class FrameTopologyResolver:
    """Resolves expected frame shape for one charger."""

    def __init__(
        self,
        *,
        default_connector_count: int | None = None,
        default_smr_count: int | None = None,
        #: Minimum share of timestamp groups that must exhibit a candidate
        #: position for it to count as stably observed.
        observed_stability_threshold: float = 0.5,
    ) -> None:
        self._default_connectors = default_connector_count
        self._default_smrs = default_smr_count
        self._stability = observed_stability_threshold

    # -- tier 1 and 2: declared expectations -------------------------------

    def from_configuration(
        self,
        *,
        connector_count: int | None,
        smr_count: int | None,
        observed_connectors: Sequence[str] = (),
        observed_smrs: Sequence[str] = (),
        basis: TopologyBasis = TopologyBasis.CHARGER_CONFIGURATION,
    ) -> FrameTopology | None:
        """Build topology from declared counts.

        A count alone does not name the identities, so observed identities supply
        the labels when their cardinality agrees with the declared count. When it
        does not agree, synthetic 1..N labels are used and the disagreement is
        surfaced in ``note`` rather than hidden - the mismatch is itself a
        finding the daily report should carry.
        """
        if not connector_count or not smr_count:
            return None

        connectors, connector_note = self._labels(
            declared=connector_count, observed=observed_connectors, kind="connector"
        )
        smrs, smr_note = self._labels(declared=smr_count, observed=observed_smrs, kind="SMR")
        notes = [note for note in (connector_note, smr_note) if note]

        return FrameTopology(
            positions=_cross(connectors, smrs),
            connectors=connectors,
            smrs=smrs,
            basis=basis,
            is_full_matrix=True,
            note="; ".join(notes) or None,
        )

    def _labels(
        self, *, declared: int, observed: Sequence[str], kind: str
    ) -> tuple[tuple[str, ...], str | None]:
        identities = _sorted_identities(observed)
        if len(identities) == declared:
            return identities, None
        if not identities:
            # Nothing observed to name them with; fall back to ordinals.
            return tuple(str(index) for index in range(1, declared + 1)), None
        if len(identities) < declared:
            # Fewer identities than expected: keep the observed ones and pad, so
            # the missing slots are still expected and therefore still reported.
            padded = list(identities)
            ordinal = 1
            while len(padded) < declared:
                candidate = str(ordinal)
                if candidate not in padded:
                    padded.append(candidate)
                ordinal += 1
            return _sorted_identities(padded), (
                f"observed {len(identities)} {kind} identities but {declared} expected"
            )

        # More identities observed than declared. The declared count is
        # authoritative - it is precedence tier 1 - so the expected set is the
        # first `declared` identities in deterministic order and the surplus is
        # left *outside* the topology. That is what lets an anomalous SMR 9 be
        # reported as an unexpected position (section 21) instead of being
        # silently absorbed into the expected shape, which would make the anomaly
        # invisible and turn the frame into a merely "partial" one.
        return identities[:declared], (
            f"observed {len(identities)} {kind} identities, exceeding the declared "
            f"{declared}; expecting {list(identities[:declared])} and reporting "
            f"{list(identities[declared:])} as unexpected"
        )

    # -- tier 3: observed, with a stability guard --------------------------

    def from_observation(
        self, position_group_counts: Mapping[LogicalPosition, int], group_total: int
    ) -> FrameTopology | None:
        """Derive topology from what the file actually contains.

        ``position_group_counts`` maps a position to the number of *timestamp
        groups* it appeared in - not the number of rows. Counting groups is what
        makes a single 64-row anomaly unable to invent a position, since it
        contributes 1 to the count no matter how many rows it holds.
        """
        if group_total <= 0 or not position_group_counts:
            return None

        floor = max(1, int(self._stability * group_total))
        stable = {
            position
            for position, groups in position_group_counts.items()
            if groups >= floor and position.is_assigned
        }
        if not stable:
            return None

        connectors = _sorted_identities(position.connector_id for position in stable)
        smrs = _sorted_identities(position.smr_id for position in stable)
        full = _cross(connectors, smrs)

        # A sparse matrix is respected rather than forced: if the charger never
        # reports C2/S4, expecting it would manufacture a permanent gap.
        is_full = stable == full
        return FrameTopology(
            positions=frozenset(stable),
            connectors=connectors,
            smrs=smrs,
            basis=TopologyBasis.OBSERVED_STABLE,
            is_full_matrix=is_full,
            note=(
                None
                if is_full
                else "observed topology is sparse; expecting only position pairs "
                "actually reported in a majority of timestamp groups"
            ),
        )

    # -- entry point -------------------------------------------------------

    def resolve(
        self,
        *,
        charger_connector_count: int | None = None,
        charger_smr_count: int | None = None,
        observed_connectors: Sequence[str] = (),
        observed_smrs: Sequence[str] = (),
        position_group_counts: Mapping[LogicalPosition, int] | None = None,
        group_total: int = 0,
    ) -> FrameTopology:
        """Apply the documented precedence and always return a verdict."""
        from_charger = self.from_configuration(
            connector_count=charger_connector_count,
            smr_count=charger_smr_count,
            observed_connectors=observed_connectors,
            observed_smrs=observed_smrs,
            basis=TopologyBasis.CHARGER_CONFIGURATION,
        )
        if from_charger is not None:
            return from_charger

        from_default = self.from_configuration(
            connector_count=self._default_connectors,
            smr_count=self._default_smrs,
            observed_connectors=observed_connectors,
            observed_smrs=observed_smrs,
            basis=TopologyBasis.CONFIGURED_DEFAULT,
        )
        if from_default is not None:
            return from_default

        if position_group_counts:
            observed = self.from_observation(position_group_counts, group_total)
            if observed is not None:
                return observed

        return FrameTopology(
            positions=frozenset(),
            connectors=(),
            smrs=(),
            basis=TopologyBasis.UNRESOLVED,
            is_full_matrix=False,
            note="no charger configuration, no configured default and no stable "
            "observed topology; frames cannot be assessed for completeness",
        )
