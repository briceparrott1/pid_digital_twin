# Mutable counters threaded through process/merge calls and assembled into
# Diagnostics at the root.
from __future__ import annotations

from dataclasses import dataclass

from engine.types import Diagnostics


@dataclass
class Counters:
    """Running tallies accumulated during recursion; not a contract type."""

    seam_collisions: int = 0
    equipment_merges: int = 0


def to_diagnostics(
    counters: Counters,
    leftover_splits: list,
    untagged_count: int,
    seam_pairing_failures: list,
) -> Diagnostics:
    """Assembles the final `Diagnostics` from running counters plus the
    fields computed structurally at root collapse (leftover_splits,
    untagged_count, seam_pairing_failures)."""
    return Diagnostics(
        leftover_splits=leftover_splits,
        untagged_count=untagged_count,
        seam_collisions=counters.seam_collisions,
        equipment_merges=counters.equipment_merges,
        seam_pairing_failures=seam_pairing_failures,
    )
