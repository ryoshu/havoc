"""Affordance layer — computes valid actions from game phase and state."""

from __future__ import annotations

from .context import GameContext
from .models import Affordance, GamePhase, GameSession


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

        return affordances

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
        # Healing
        for char in alive_chars:
            if char.blood >= 3:
                injured_cats = [
                    inj.category for inj in char.injuries
                    if inj.minor_marked or inj.major_marked
                ]
                if injured_cats:
                    affordances.append(Affordance(
                        action="heal",
                        description=f"Heal {char.name} (costs 3 Blood, has {char.blood})",
                        schema={
                            "character_id": {"type": "string", "const": char.id},
                            "category": {"type": "string", "enum": injured_cats},
                        },
                    ))

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

    return affordances
