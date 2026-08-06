"""Per-action effect metadata for the legacy affordance adapter.

The current runtime has no per-action effect classification: MCP
``ToolAnnotations`` are set at the tool level (``get``/``search`` vs
``act``), not per action (see ``src/gia/server.py``). Until PR 4 moves
commands into the kernel and gives each one an owned ``EffectMetadata``
(PR 2's plan work item), the legacy adapter needs a stopgap per-action
mapping.

This mapping is a hardcoded snapshot of the ``mutation`` column in
``docs/gia2/command-matrix.json`` (the PR 1 characterization baseline), not
a runtime read of that file — capability projection must not depend on
docs. ``tests/test_capabilities.py`` cross-checks this map against the JSON
file so the two cannot silently drift apart.

``wait_for_rescue`` has no dispatch branch at all (Gap A / Gap B, frozen in
PR 1) so the matrix records its mutation status as unknown. Its intent is a
state-changing rescue action, so it is treated as mutating here.
"""

from __future__ import annotations

from .models import EffectMetadata

MUTATING_ACTIONS: frozenset[str] = frozenset(
    {
        "select_character",
        "start_mission",
        "move_to_location",
        "engage_threat",
        "loot",
        "share_blood",
        "next_turn",
        "build_dice_pool",
        "retreat",
        "allocate_dice",
        "use_flashback",
        "heal",
        "choose_next_location",
        "wait_for_rescue",
        "trigger_last_stand",
    }
)

READ_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        "view_character_template",
        "view_character_sheet",
        "view_scene",
        "check_inventory",
        "view_epilogue",
    }
)


def effect_metadata_for(action: str) -> EffectMetadata:
    """Look up the stopgap effect metadata for a legacy action name."""
    if action not in MUTATING_ACTIONS and action not in READ_ONLY_ACTIONS:
        raise KeyError(f"No legacy effect metadata registered for action {action!r}")
    return EffectMetadata(mutating=action in MUTATING_ACTIONS)
