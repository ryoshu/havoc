"""MCP server — 3 generic tools (get, search, act) for the TTRPG backend."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .affordances import compute_affordances
from .context import GameContext
from .domain import DomainError, HavocEngine
from .models import (
    DecisionRecord,
    DiceAllocation,
    EquipmentState,
    GamePhase,
)
from .responses import format_dice_roll, format_response


class GameRuntime:
    """Encapsulates game state for a single runtime instance.

    Holds a GameContext, HavocEngine, pending rolls, and a default session.
    Can be instantiated multiple times for parallel/isolated playthroughs.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.ctx = GameContext(db_path=db_path)
        self.engine = HavocEngine()
        self._pending_rolls: dict[str, dict] = {}
        _session = self.ctx.db.create_session()
        self.default_session_id = _session.id

    def _session_id_or_default(self, sid: str) -> str:
        return sid or self.default_session_id

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        """Retrieve a resource by type and ID. Returns data + available affordances."""
        sid = self._session_id_or_default(session_id)
        try:
            if resource_type == "session":
                target_id = id or sid
                session = self.ctx.get_session(target_id)
                if not session:
                    return json.dumps({"error": f"Session {target_id} not found"})
                affordances = compute_affordances(self.ctx, target_id)
                return json.dumps(format_response(session, affordances), indent=2)
            elif resource_type == "character":
                char = self.ctx.db.get_character(id)
                if not char:
                    return json.dumps({"error": f"Character {id} not found"})
                sheet = self.ctx.get_character_sheet(id)
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(sheet, affordances), indent=2)
            elif resource_type == "character_template":
                template = self.ctx.get_character_template(id)
                if not template:
                    return json.dumps({"error": f"Character template {id} not found"})
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(template, affordances), indent=2)
            elif resource_type == "location":
                loc = self.ctx.get_location_template(id)
                if not loc:
                    return json.dumps({"error": f"Location {id} not found"})
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(loc, affordances), indent=2)
            elif resource_type == "scene":
                scene = self.ctx.get_active_scene(sid)
                if not scene:
                    return json.dumps({"error": "No active scene"})
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(scene, affordances), indent=2)
            elif resource_type == "enemy":
                enemy = self.ctx.get_enemy_template(id)
                if not enemy:
                    return json.dumps({"error": f"Enemy {id} not found"})
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(enemy, affordances), indent=2)
            elif resource_type == "rules":
                rules = self.ctx.graph.get_rules()
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(rules, affordances), indent=2)
            else:
                return json.dumps({"error": f"Unknown resource type: {resource_type}"})
        except DomainError as e:
            return json.dumps({"error": str(e)})

    def search(self, resource_type: str, filters: str = "{}", session_id: str = "") -> str:
        """Search/browse resources. Returns results + available affordances."""
        sid = self._session_id_or_default(session_id)
        try:
            parsed = json.loads(filters) if isinstance(filters, str) else filters
        except json.JSONDecodeError:
            parsed = {}
        try:
            if resource_type == "characters":
                templates = self.ctx.get_all_character_templates()
                results = [{"id": t.id, "name": t.name, "description": t.description[:100]} for t in templates]
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(results, affordances), indent=2)
            elif resource_type == "locations":
                locations = self.ctx.get_all_locations()
                if "sector" in parsed:
                    locations = [l for l in locations if l.sector == parsed["sector"]]
                results = [
                    {
                        "id": l.id, "name": l.name, "sector": l.sector,
                        "objective": l.objective.name, "objective_rating": l.objective.rating,
                    }
                    for l in locations
                ]
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(results, affordances), indent=2)
            elif resource_type == "enemies":
                results = self.ctx.graph.get_all_enemies()
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(results, affordances), indent=2)
            elif resource_type == "ubermenschen":
                results = self.ctx.graph.get_ubermenschen()
                affordances = compute_affordances(self.ctx, sid)
                return json.dumps(format_response(results, affordances), indent=2)
            else:
                return json.dumps({"error": f"Unknown search type: {resource_type}"})
        except DomainError as e:
            return json.dumps({"error": str(e)})

    def act(self, action: str, params: str = "{}", session_id: str = "") -> str:
        """Execute an action discovered via affordances. Returns result + next affordances."""
        sid = self._session_id_or_default(session_id)
        try:
            parsed = json.loads(params) if isinstance(params, str) else params
        except json.JSONDecodeError:
            parsed = {}

        # Snapshot state before action
        session_before = self.ctx.get_session(sid)
        phase_before = session_before.phase.value if session_before else ""
        actor_id = session_before.active_character_id or "system" if session_before else "system"
        actor_name = ""
        if actor_id != "system":
            actor_char = self.ctx.db.get_character(actor_id)
            actor_name = actor_char.name if actor_char else ""

        # Snapshot affordances available at decision time
        pre_affordances = compute_affordances(self.ctx, sid)
        affordances_snapshot = [
            {"action": a.action, "description": a.description}
            for a in pre_affordances
        ]
        affordances_not_taken = [
            a.action for a in pre_affordances if a.action != action
        ]

        try:
            result, events = self._dispatch_action(sid, action, parsed)

            # Snapshot phase after
            session_after = self.ctx.get_session(sid)
            phase_after = session_after.phase.value if session_after else phase_before

            # Build result summary
            result_data = result if isinstance(result, dict) else {}
            result_summary = result_data.get("message", "")[:200]

            # Record the decision
            decision = DecisionRecord(
                session_id=sid,
                actor_id=actor_id,
                actor_name=actor_name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                result_summary=result_summary,
                events=[e.model_dump() for e in events],
                phase_before=phase_before,
                phase_after=phase_after,
            )
            self.ctx.db.record_decision(decision)

            affordances = compute_affordances(self.ctx, sid)
            response = format_response(result, affordances)
            if events:
                response["events"] = [e.model_dump() for e in events]
            return json.dumps(response, indent=2)
        except DomainError as e:
            affordances = compute_affordances(self.ctx, sid)
            return json.dumps({
                "error": str(e),
                "affordances": [
                    {"action": a.action, "description": a.description, "schema": a.schema_, "constraints": a.constraints}
                    for a in affordances
                ],
            }, indent=2)

    def _dispatch_action(self, session_id: str, action: str, params: dict):
        """Route action to appropriate domain method."""
        ctx = self.ctx
        engine = self.engine
        session = ctx.get_session(session_id)
        if not session:
            raise DomainError(f"Session {session_id} not found.")

        events = []

        # --- Setup Actions ---
        if action == "select_character":
            template_id = params["template_id"]
            existing = ctx.db.get_session_characters(session_id)
            if any(c.template_id == template_id for c in existing):
                raise DomainError(f"Character {template_id} already selected.")
            cs = ctx.create_character_state(session_id, template_id)
            return {"message": f"{cs.name} joins the mission!", "character_id": cs.id}, []

        elif action == "view_character_template":
            template = ctx.get_character_template(params["template_id"])
            if not template:
                raise DomainError(f"Template {params['template_id']} not found.")
            return template.model_dump(), []

        elif action == "start_mission":
            characters = ctx.db.get_session_characters(session_id)
            if not characters:
                raise DomainError("Select at least one character first.")
            start_locations = [l for l in ctx.get_all_locations() if l.sector == 3]
            start_loc = start_locations[0] if start_locations else ctx.get_all_locations()[0]

            session.phase = GamePhase.exploration
            session.current_location_id = start_loc.id
            session.active_character_id = characters[0].id
            session.scene_number = 1
            session.round_number = 1
            ctx.db.update_session(session)

            for ch in characters:
                ch.current_location_id = start_loc.id
                ctx.db.update_character(ch)

            scene = ctx.create_scene_from_location(session_id, start_loc.id)

            return {
                "message": f"The mission begins! Your drop coffins slam into {start_loc.name}.",
                "location": start_loc.name,
                "location_description": start_loc.description,
                "objective": start_loc.objective.name,
                "objective_rating": start_loc.objective.rating,
                "threats": [
                    {"name": t.name, "rating": t.current_rating, "attack": t.current_attack}
                    for t in scene.active_threats
                ],
                "active_character": characters[0].name,
            }, []

        # --- Exploration Actions ---
        elif action == "move_to_location":
            location_id = params["location_id"]
            loc = ctx.get_location_template(location_id)
            if not loc:
                raise DomainError(f"Location {location_id} not found.")

            session.current_location_id = location_id
            session.scene_number += 1
            session.round_number = 1
            session.phase = GamePhase.exploration
            ctx.db.update_session(session)

            for ch in ctx.db.get_session_characters(session_id):
                if not ch.is_dead:
                    ch.current_location_id = location_id
                    ctx.db.update_character(ch)

            scene = ctx.create_scene_from_location(session_id, location_id)

            return {
                "message": f"The vampires advance to {loc.name}.",
                "location": loc.name,
                "location_description": loc.description,
                "objective": loc.objective.name,
                "objective_rating": loc.objective.rating,
                "threats": [
                    {"name": t.name, "rating": t.current_rating, "attack": t.current_attack}
                    for t in scene.active_threats
                ],
            }, []

        elif action == "engage_threat":
            session.phase = GamePhase.engagement_pre_roll
            ctx.db.update_session(session)
            scene = ctx.get_active_scene(session_id)
            threat_name = params.get("threat_name", "")
            threat = None
            if scene:
                for t in scene.active_threats:
                    if t.name == threat_name and not t.is_defeated:
                        threat = t
                        break

            result = {"message": f"Engaging {threat_name}!"}
            if threat:
                result["threat"] = {
                    "name": threat.name, "rating": threat.current_rating,
                    "attack": threat.current_attack, "challenge": threat.challenge,
                }
            return result, []

        elif action == "loot":
            item_name = params.get("item_name", "")
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")

            loc = ctx.get_location_template(session.current_location_id) if session.current_location_id else None
            if not loc:
                raise DomainError("Not at a location.")

            loot_template = None
            for lt in loc.loot:
                if lt.name == item_name:
                    loot_template = lt
                    break
            if not loot_template:
                raise DomainError(f"'{item_name}' not available at this location.")

            item = EquipmentState(
                name=loot_template.name,
                uses_remaining=loot_template.max_uses,
                bonus_condition=loot_template.bonus_condition,
                bonus_dice=loot_template.bonus_dice,
                is_loot=True,
            )
            event = engine.loot_item(active_char, item)
            ctx.db.update_character(active_char)
            return {"message": f"{active_char.name} loots {item_name}!", "item": item.model_dump()}, [event]

        elif action == "check_inventory":
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")
            return {
                "character": active_char.name,
                "blood": active_char.blood,
                "equipment": [e.model_dump() for e in active_char.equipment],
                "injuries": [i.model_dump() for i in active_char.injuries],
            }, []

        elif action == "share_blood":
            giver_id = params.get("giver_id", session.active_character_id)
            receiver_id = params["receiver_id"]
            amount = params.get("amount", 1)

            giver = ctx.db.get_character(giver_id)
            receiver = ctx.db.get_character(receiver_id)
            if not giver or not receiver:
                raise DomainError("Character not found.")

            event = engine.share_blood(giver, receiver, amount)
            ctx.db.update_character(giver)
            ctx.db.update_character(receiver)
            return {"message": f"{giver.name} shares {amount} Blood with {receiver.name}."}, [event]

        elif action == "next_turn":
            char_id = params["character_id"]
            char = ctx.db.get_character(char_id)
            if not char:
                raise DomainError(f"Character {char_id} not found.")
            session.active_character_id = char_id
            ctx.db.update_session(session)
            return {"message": f"It's {char.name}'s turn.", "active_character": char.name}, []

        # --- Engagement Actions ---
        elif action == "build_dice_pool":
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")

            scene = ctx.get_active_scene(session_id)
            if not scene:
                raise DomainError("No active scene.")

            stat_name = params.get("stat", "brawl")
            template = ctx.get_character_template(active_char.template_id)
            if not template:
                raise DomainError("Character template not found.")

            stat_value = template.stats.get(stat_name, 2)

            sheet = ctx.get_character_sheet(active_char.id)
            if sheet:
                stat_value = sheet["effective_stats"].get(stat_name, stat_value)

            equipment_used = []
            for eq_name in params.get("equipment_names", []):
                eq = engine.use_equipment(active_char, eq_name)
                equipment_used.append(eq)

            bonus_dice = params.get("bonus_dice", 0)
            ability_dice = 1 if params.get("ability_name") else 0

            pool_size = engine.build_pool_size(
                stat_value, equipment_used, ability_dice, bonus_dice,
            )

            gm_attack = engine.get_total_gm_attack(scene)

            discard_threshold = 3
            for threat in scene.active_threats:
                if threat.name == "Rust-Witch" and not threat.is_defeated:
                    discard_threshold = 4
                    break

            roll, player_kept, gm_kept = engine.resolve_roll(pool_size, gm_attack, discard_threshold)
            roll.session_id = session_id
            roll.character_id = active_char.id
            roll.scene_id = scene.id

            self._pending_rolls[session_id] = {
                "roll": roll,
                "player_kept": player_kept,
                "gm_kept": gm_kept,
            }

            ctx.db.update_character(active_char)

            session.phase = GamePhase.engagement_post_roll
            ctx.db.update_session(session)

            return {
                "message": f"{active_char.name} rolls {pool_size}d6 using {stat_name.upper()}!",
                "roll_summary": format_dice_roll(roll),
                "player_kept": player_kept,
                "gm_kept": gm_kept,
                "stat": stat_name,
                "stat_value": stat_value,
                "equipment_used": [e.name for e in equipment_used],
                "pool_breakdown": {
                    "stat": stat_value,
                    "equipment": len(equipment_used),
                    "ability": ability_dice,
                    "bonus": bonus_dice,
                    "total": pool_size,
                },
            }, []

        elif action == "allocate_dice":
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")

            scene = ctx.get_active_scene(session_id)
            if not scene:
                raise DomainError("No active scene.")

            pending = self._pending_rolls.get(session_id)
            if not pending:
                raise DomainError("No pending roll to allocate.")

            allocations = params.get("allocations", {})
            roll = pending["roll"]
            gm_kept = pending["gm_kept"]

            alloc_events, remaining_gm = engine.apply_allocations(
                allocations, scene, active_char, gm_kept,
            )
            events.extend(alloc_events)

            roll.allocations = allocations
            ctx.db.record_roll(roll)

            template = ctx.get_character_template(active_char.template_id)
            injury_slots = {}
            if template:
                injury_slots = {
                    cat: {"minor": slot.minor, "major": slot.major, "major_penalty": slot.major_penalty}
                    for cat, slot in template.injuries.items()
                }

            injury_events = engine.resolve_injuries(remaining_gm, active_char, injury_slots)
            events.extend(injury_events)

            ctx.db.update_character(active_char)
            ctx.db.update_scene(scene)

            del self._pending_rolls[session_id]

            if engine.check_scene_complete(scene):
                scene.completed = True
                ctx.db.update_scene(scene)
                session.phase = GamePhase.between_scenes
                ctx.db.update_session(session)

                if session.current_location_id == "hitlers_broadcast_suite":
                    session.phase = GamePhase.mission_complete
                    ctx.db.update_session(session)
                    return {
                        "message": "MISSION COMPLETE! Hitler's blood is yours. The war is over.",
                        "scene_completed": True,
                    }, events

                return {
                    "message": f"Scene complete! Objective '{scene.active_objectives[0].name}' achieved!",
                    "scene_completed": True,
                    "remaining_gm_dice": len(remaining_gm),
                }, events

            if active_char.is_dead:
                session.phase = GamePhase.last_stand
                ctx.db.update_session(session)
                return {
                    "message": f"{active_char.name} has fallen! Time for a Last Stand!",
                    "remaining_gm_dice": len(remaining_gm),
                }, events

            if active_char.is_downed:
                alive = [c for c in ctx.db.get_session_characters(session_id)
                         if not c.is_dead and not c.is_downed]
                if alive:
                    session.active_character_id = alive[0].id
                session.phase = GamePhase.exploration
                ctx.db.update_session(session)
                return {
                    "message": f"{active_char.name} is downed! Rescue needed.",
                    "remaining_gm_dice": len(remaining_gm),
                }, events

            session.phase = GamePhase.exploration
            ctx.db.update_session(session)

            return {
                "message": "Dice allocated! Turn resolved.",
                "remaining_gm_dice": len(remaining_gm),
                "scene_status": {
                    "objectives": [
                        {"name": o.name, "rating": o.current_rating, "completed": o.is_completed}
                        for o in scene.active_objectives
                    ],
                    "threats": [
                        {"name": t.name, "rating": t.current_rating, "attack": t.current_attack, "defeated": t.is_defeated}
                        for t in scene.active_threats
                    ],
                },
            }, events

        elif action == "use_flashback":
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")

            pending = self._pending_rolls.get(session_id)
            if not pending:
                raise DomainError("No pending roll for flashback.")

            new_roll, new_kept = engine.use_flashback(active_char, pending["roll"])
            self._pending_rolls[session_id]["roll"] = new_roll
            self._pending_rolls[session_id]["player_kept"] = new_kept

            ctx.db.update_character(active_char)

            return {
                "message": f"{active_char.name} triggers a flashback! Rerolling with 2 extra dice!",
                "roll_summary": format_dice_roll(new_roll),
                "player_kept": new_kept,
                "gm_kept": pending["gm_kept"],
            }, []

        elif action == "retreat":
            scene = ctx.get_active_scene(session_id)
            if not scene:
                raise DomainError("No active scene.")

            import random as _r
            escape_rating = _r.randint(4, 6)
            from .models import ObjectiveState
            scene.active_objectives.append(ObjectiveState(
                name="Escape!",
                current_rating=escape_rating,
            ))
            ctx.db.update_scene(scene)

            session.phase = GamePhase.exploration
            ctx.db.update_session(session)

            return {
                "message": f"Retreating! New objective: Escape! (rating {escape_rating})",
            }, []

        # --- Between Scenes Actions ---
        elif action == "heal":
            char_id = params["character_id"]
            category = params["category"]
            char = ctx.db.get_character(char_id)
            if not char:
                raise DomainError(f"Character {char_id} not found.")

            event = engine.heal_injury(char, category)
            ctx.db.update_character(char)
            return {"message": f"Healed {char.name}'s injury in category {category}."}, [event] if event else []

        elif action == "choose_next_location":
            location_id = params["location_id"]
            loc = ctx.get_location_template(location_id)
            if not loc:
                raise DomainError(f"Location {location_id} not found.")

            session.current_location_id = location_id
            session.scene_number += 1
            session.round_number = 1
            session.phase = GamePhase.exploration
            ctx.db.update_session(session)

            for ch in ctx.db.get_session_characters(session_id):
                if not ch.is_dead:
                    ch.current_location_id = location_id
                    ctx.db.update_character(ch)

            scene = ctx.create_scene_from_location(session_id, location_id)

            return {
                "message": f"The vampires press on to {loc.name}!",
                "location": loc.name,
                "location_description": loc.description,
                "objective": loc.objective.name,
                "objective_rating": loc.objective.rating,
                "threats": [
                    {"name": t.name, "rating": t.current_rating, "attack": t.current_attack}
                    for t in scene.active_threats
                ],
            }, []

        # --- Last Stand ---
        elif action == "trigger_last_stand":
            active_char = ctx.db.get_character(session.active_character_id) if session.active_character_id else None
            if not active_char:
                raise DomainError("No active character.")

            results = engine.trigger_last_stand()
            total_successes = sum(2 if d == 6 else (1 if d >= 4 else 0) for d in results)

            alive = [c for c in ctx.db.get_session_characters(session_id)
                     if not c.is_dead and c.id != active_char.id]
            if alive:
                session.active_character_id = alive[0].id
                session.phase = GamePhase.exploration
            else:
                session.phase = GamePhase.mission_complete
            ctx.db.update_session(session)

            template = ctx.get_character_template(active_char.template_id)
            last_stand_name = template.last_stand if template else "Last Stand"

            return {
                "message": f"{active_char.name}'s LAST STAND: {last_stand_name}!",
                "results": results,
                "total_successes": total_successes,
                "note": "Allocate these successes freely to any objectives and threats.",
            }, []

        # --- View Actions ---
        elif action == "view_character_sheet":
            char_id = params.get("character_id", session.active_character_id)
            if not char_id:
                raise DomainError("No character specified.")
            sheet = ctx.get_character_sheet(char_id)
            if not sheet:
                raise DomainError(f"Character {char_id} not found.")
            return sheet, []

        elif action == "view_scene":
            scene = ctx.get_active_scene(session_id)
            if not scene:
                raise DomainError("No active scene.")
            return scene.model_dump(), []

        elif action == "view_epilogue":
            characters = ctx.db.get_session_characters(session_id)
            survivors = [c for c in characters if not c.is_dead]
            fallen = [c for c in characters if c.is_dead]
            return {
                "message": "The vampires ride off into the sunrise. The war is over.",
                "survivors": [c.name for c in survivors],
                "fallen": [c.name for c in fallen],
            }, []

        else:
            raise DomainError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Module-level backward compatibility (MCP server, existing tests, demo)
# ---------------------------------------------------------------------------

_default = GameRuntime()
ctx = _default.ctx
engine = _default.engine
_pending_rolls = _default._pending_rolls
DEFAULT_SESSION_ID = _default.default_session_id

def _session_id_or_default(sid: str) -> str:
    return _default._session_id_or_default(sid)


# --- Tools ---

mcp = FastMCP("gia-eat-the-reich")


@mcp.tool()
def get(resource_type: str, id: str = "", session_id: str = "") -> str:
    """Retrieve a resource by type and ID. Returns data + available affordances.

    resource_type: "session", "character", "character_template", "location", "scene", "enemy", "rules"
    id: resource ID (template_id for templates, character_id for characters, etc.)
    session_id: optional, defaults to current session
    """
    return _default.get(resource_type, id, session_id)


@mcp.tool()
def search(resource_type: str, filters: str = "{}", session_id: str = "") -> str:
    """Search/browse resources. Returns results + available affordances.

    resource_type: "characters", "locations", "enemies", "ubermenschen"
    filters: JSON string, e.g. {"sector": 3} for locations
    session_id: optional
    """
    return _default.search(resource_type, filters, session_id)


@mcp.tool()
def act(action: str, params: str = "{}", session_id: str = "") -> str:
    """Execute an action discovered via affordances. Returns result + next affordances.

    action: action name from affordances
    params: JSON string of action parameters
    session_id: optional
    """
    return _default.act(action, params, session_id)


if __name__ == "__main__":
    mcp.run()
