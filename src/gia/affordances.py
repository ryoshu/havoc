"""Affordance layer — computes valid actions from game phase and state."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .context import GameContext
from .models import Affordance, GamePhase, GameSession


JSON_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
OPTIONAL_PARAMETERS = {"equipment_names", "ability_name", "bonus_dice"}


def _normalize_property(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    if normalized.get("type") == "object":
        properties = normalized.get("properties", {})
        normalized["properties"] = {
            name: _normalize_property(value)
            for name, value in properties.items()
        }
        normalized["required"] = normalized.get("required", [])
        normalized["additionalProperties"] = False
    return normalized


def normalize_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert affordance field fragments into closed JSON Schema objects."""
    if "properties" in raw_schema and raw_schema.get("type") == "object":
        properties = raw_schema["properties"]
    else:
        properties = raw_schema
    normalized_properties = {
        name: _normalize_property(spec)
        for name, spec in properties.items()
    }
    return {
        "$schema": JSON_SCHEMA_URI,
        "type": "object",
        "properties": normalized_properties,
        "required": [
            name
            for name, spec in normalized_properties.items()
            if "default" not in spec and name not in OPTIONAL_PARAMETERS
        ],
        "additionalProperties": False,
    }


def finalize_affordances(affordances: list[Affordance]) -> list[Affordance]:
    """Attach deterministic IDs and complete schemas to generated affordances."""
    finalized = []
    occurrences: dict[str, int] = {}
    for affordance in affordances:
        schema = normalize_schema(affordance.schema_)
        identity = json.dumps(
            {
                "action": affordance.action,
                "schema": schema,
                "constraints": affordance.constraints,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        affordance_id = f"aff-{hashlib.sha256(f'{identity}:{occurrence}'.encode()).hexdigest()[:16]}"
        finalized.append(
            affordance.model_copy(update={"id": affordance_id, "schema_": schema})
        )
    return finalized


def _validate_value(name: str, value: Any, schema: dict[str, Any], errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{name} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{name} must be one of {schema['enum']!r}")

    schema_type = schema.get("type")
    type_matches = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    if schema_type in type_matches and not type_matches[schema_type](value):
        errors.append(f"{name} must be a {schema_type}")
        return
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{name} must be >= {schema['minimum']}")
    if schema_type == "array":
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_value(f"{name}[{index}]", item, item_schema, errors)
    if schema_type == "object":
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        errors.extend(f"{name}.{key} is required" for key in missing)
        extras = [key for key in value if key not in properties]
        errors.extend(f"{name}.{key} is not allowed" for key in extras)
        for key, item in value.items():
            if key in properties:
                _validate_value(f"{name}.{key}", item, properties[key], errors)


def validate_parameters(affordance: Affordance, params: dict[str, Any]) -> list[str]:
    """Return schema violations for one affordance invocation."""
    errors: list[str] = []
    _validate_value("params", params, affordance.schema_, errors)
    return errors


def compute_affordances(
    ctx: GameContext,
    session_id: str,
) -> list[Affordance]:
    """Compute available actions based on current game phase and state."""
    session = ctx.get_session(session_id)
    if not session:
        return []

    affordances: list[Affordance] = []
    phase = session.phase

    # --- Setup Phase ---
    if phase == GamePhase.setup:
        # Show available characters to select
        selected = {
            cs.template_id
            for cs in ctx.db.get_session_characters(session_id)
        }
        templates = ctx.get_all_character_templates()
        for t in templates:
            if t.id not in selected:
                affordances.append(Affordance(
                    action="select_character",
                    description=f"Select {t.name} — {t.description[:80]}...",
                    schema={"template_id": {"type": "string", "const": t.id}},
                ))

        if selected:
            affordances.append(Affordance(
                action="start_mission",
                description=f"Begin the mission with {len(selected)} character(s)",
                schema={},
                constraints=[f"{len(selected)} character(s) selected"],
            ))

        # Always can view characters
        for t in templates:
            affordances.append(Affordance(
                action="view_character_template",
                description=f"View {t.name}'s full character sheet",
                schema={"template_id": {"type": "string", "const": t.id}},
            ))

        return finalize_affordances(affordances)

    # --- Get active character and scene ---
    active_char = None
    if session.active_character_id:
        active_char = ctx.db.get_character(session.active_character_id)

    scene = ctx.get_active_scene(session_id)
    characters = ctx.db.get_session_characters(session_id)
    alive_chars = [c for c in characters if not c.is_dead]

    # --- Always available (non-setup) ---
    affordances.append(Affordance(
        action="view_character_sheet",
        description="View a character's current status",
        schema={"character_id": {"type": "string", "enum": [c.id for c in alive_chars]}},
    ))

    if scene:
        affordances.append(Affordance(
            action="view_scene",
            description="View current scene status (threats, objectives)",
            schema={},
        ))

    # --- Exploration Phase ---
    if phase == GamePhase.exploration:
        if session.current_location_id:
            connected = ctx.get_connected_locations(session.current_location_id)
            for loc in connected:
                affordances.append(Affordance(
                    action="move_to_location",
                    description=f"Move to {loc.name} (Sector {loc.sector})",
                    schema={"location_id": {"type": "string", "const": loc.id}},
                ))

        if scene:
            active_threats = [t for t in scene.active_threats if not t.is_defeated]
            for threat in active_threats:
                affordances.append(Affordance(
                    action="engage_threat",
                    description=f"Engage {threat.name} (rating {threat.current_rating}, attack {threat.current_attack})",
                    schema={"threat_name": {"type": "string", "const": threat.name}},
                ))

            # Looting
            if session.current_location_id:
                loc = ctx.get_location_template(session.current_location_id)
                if loc and loc.loot:
                    for loot in loc.loot:
                        affordances.append(Affordance(
                            action="loot",
                            description=f"Loot: {loot.name} ({loot.bonus_condition or 'no bonus'})",
                            schema={"item_name": {"type": "string", "const": loot.name}},
                        ))

        # Check inventory
        if active_char:
            affordances.append(Affordance(
                action="check_inventory",
                description=f"Check {active_char.name}'s equipment",
                schema={},
            ))

        # Blood sharing
        if len(alive_chars) > 1 and active_char and active_char.blood > 0:
            others = [c for c in alive_chars if c.id != active_char.id]
            affordances.append(Affordance(
                action="share_blood",
                description="Share Blood with another vampire",
                schema={
                    "receiver_id": {"type": "string", "enum": [c.id for c in others]},
                    "amount": {"type": "integer", "minimum": 1},
                },
            ))

        # Next turn
        if len(alive_chars) > 1:
            others = [c for c in alive_chars if c.id != session.active_character_id]
            affordances.append(Affordance(
                action="next_turn",
                description="Switch to another character's turn",
                schema={"character_id": {"type": "string", "enum": [c.id for c in others]}},
            ))

    # --- Engagement Pre-Roll ---
    if phase == GamePhase.engagement_pre_roll:
        if active_char and scene:
            # Build dice pool
            affordances.append(Affordance(
                action="build_dice_pool",
                description="Choose stat and equipment, then roll dice",
                schema={
                    "stat": {"type": "string", "enum": list(active_char.model_dump().get("stats", {}).keys()) or ["brawl", "con", "fix", "search", "shoot", "sneak", "terrify"]},
                    "equipment_names": {"type": "array", "items": {"type": "string"}, "description": "Equipment to use (spends 1 use each)"},
                    "ability_name": {"type": "string", "description": "Ability to use (optional)"},
                    "bonus_dice": {"type": "integer", "description": "Bonus dice from conditions (optional)", "default": 0},
                },
            ))

            # Retreat
            affordances.append(Affordance(
                action="retreat",
                description="Attempt to retreat from engagement (creates Escape objective)",
                schema={},
            ))

    # --- Engagement Post-Roll ---
    if phase == GamePhase.engagement_post_roll:
        if active_char:
            affordances.append(Affordance(
                action="allocate_dice",
                description="Allocate kept dice to objectives, threats, defense, feed, or special",
                schema={
                    "allocations": {
                        "type": "object",
                        "properties": {
                            "objective": {"type": "array", "items": {"type": "integer"}, "description": "Dice values allocated to objective"},
                            "threat": {"type": "array", "items": {"type": "integer"}, "description": "Dice values allocated to threat"},
                            "defense": {"type": "array", "items": {"type": "integer"}, "description": "Dice values allocated to defense"},
                            "feed": {"type": "array", "items": {"type": "integer"}, "description": "Dice values allocated to feeding"},
                            "special": {"type": "array", "items": {"type": "integer"}, "description": "Dice values allocated to special (6 only)"},
                        },
                    },
                },
            ))

            # Flashback
            if not active_char.flashback_used:
                affordances.append(Affordance(
                    action="use_flashback",
                    description="Use flashback: add 2 dice and reroll everything (once per session)",
                    schema={},
                    constraints=["Can only be used when you rolled 2 or fewer successes"],
                ))

    # --- Between Scenes ---
    if phase == GamePhase.between_scenes:
        # Blood sharing
        for char in alive_chars:
            if char.blood > 0:
                others = [c for c in alive_chars if c.id != char.id]
                if others:
                    affordances.append(Affordance(
                        action="share_blood",
                        description=f"{char.name} shares Blood (has {char.blood})",
                        schema={
                            "giver_id": {"type": "string", "const": char.id},
                            "receiver_id": {"type": "string", "enum": [c.id for c in others]},
                            "amount": {"type": "integer", "minimum": 1},
                        },
                    ))

        # Choose next location
        if session.current_location_id:
            connected = ctx.get_connected_locations(session.current_location_id)
            for loc in connected:
                affordances.append(Affordance(
                    action="choose_next_location",
                    description=f"Move to {loc.name} (Sector {loc.sector}) — {loc.objective.name} ({loc.objective.rating})",
                    schema={"location_id": {"type": "string", "const": loc.id}},
                ))

    # --- Downed ---
    if phase == GamePhase.downed:
        if active_char and active_char.is_downed:
            affordances.append(Affordance(
                action="wait_for_rescue",
                description=f"{active_char.name} is downed — waiting for another vampire to rescue them",
                schema={},
            ))

    # --- Last Stand ---
    if phase == GamePhase.last_stand:
        if active_char and active_char.is_dead:
            affordances.append(Affordance(
                action="trigger_last_stand",
                description=f"{active_char.name}'s Last Stand! Roll 8D6 and allocate freely",
                schema={},
            ))

    # --- Mission Complete ---
    if phase == GamePhase.mission_complete:
        affordances.append(Affordance(
            action="view_epilogue",
            description="View the mission epilogue",
            schema={},
        ))

    # Commands migrated onto the command-policy kernel (PR 3) self-gate on
    # phase inside their own Command.applicable, so they are projected
    # unconditionally here rather than duplicating a phase check.
    from .commands.kernel import project_affordances as _project_kernel_affordances
    affordances.extend(_project_kernel_affordances(ctx, session))

    return finalize_affordances(affordances)
