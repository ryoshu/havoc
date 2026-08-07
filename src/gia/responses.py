"""Transport-neutral response envelopes for the GIA runtime.

The envelope types and builders moved to ``gia_core.responses`` (PR 14
of the GIA/GAS 2.0 plan) — none of them ever referenced a Havoc concept.
They are re-exported here so every existing
``from .responses import ResourceResponse, format_response, ...`` import
keeps working unchanged. This module now holds only ``format_dice_roll``,
the one Havoc-concrete function that used to live alongside them.
"""

from __future__ import annotations

from gia_core.responses import (
    ActionResponse,
    ErrorDetail,
    ErrorResponse,
    ResourceResponse,
    format_action_response,
    format_error,
    format_response,
)
from .models import DiceRoll

__all__ = [
    "ActionResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ResourceResponse",
    "format_action_response",
    "format_error",
    "format_response",
    "format_dice_roll",
]


def format_dice_roll(roll: DiceRoll) -> str:
    """Format a dice roll result for display."""
    lines = []
    lines.append(f"Pool: {roll.pool_size}d6 → {roll.results}")

    if roll.discarded:
        lines.append(f"Discarded (failures): {roll.discarded}")
    if roll.kept:
        successes = sum(2 if d == 6 else 1 for d in roll.kept)
        crits = sum(1 for d in roll.kept if d == 6)
        lines.append(f"Kept: {roll.kept} ({successes} successes, {crits} criticals)")
    else:
        lines.append("Kept: none — total miss!")

    if roll.gm_pool_size > 0:
        lines.append(f"\nGM Attack: {roll.gm_pool_size}d6 → {roll.gm_results}")
        if roll.gm_discarded:
            lines.append(f"GM Discarded: {roll.gm_discarded}")
        if roll.gm_kept:
            lines.append(f"GM Kept: {roll.gm_kept} ({len(roll.gm_kept)} hits)")
        else:
            lines.append("GM Kept: none — attack whiffed!")

    return "\n".join(lines)
