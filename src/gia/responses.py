"""Response formatting — combines resource data with affordances."""

from __future__ import annotations

from typing import Any

from .models import Affordance, DiceRoll


def format_response(data: Any, affordances: list[Affordance]) -> dict:
    """Format a response with data and available affordances."""
    if hasattr(data, "model_dump"):
        serialized = data.model_dump()
    elif isinstance(data, list):
        serialized = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in data
        ]
    elif isinstance(data, dict):
        serialized = data
    else:
        serialized = data

    return {
        "data": serialized,
        "affordances": [
            {
                "action": a.action,
                "description": a.description,
                "schema": a.schema_,
                "constraints": a.constraints,
            }
            for a in affordances
        ],
    }


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
