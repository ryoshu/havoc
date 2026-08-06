"""MCP server — 3 generic tools (get, search, act) for the TTRPG backend."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .affordances import compute_affordances, validate_parameters
from .compat import JsonGameRuntimeAdapter
from .context import GameContext
from .domain import (
    DomainError,
    HavocEngine,
    InvalidParameterError,
    InvalidInputError,
    ResourceNotFoundError,
    StaleStateError,
    UnavailableActionError,
    UnsupportedOperationError,
)
from .models import (
    DecisionRecord,
    DiceAllocation,
    EquipmentState,
    GamePhase,
)
from .responses import (
    ActionResponse,
    ResourceResponse,
    format_action_response,
    format_dice_roll,
    format_response,
)


class GameRuntime:
    """Encapsulates game state for a single runtime instance.

    Holds a GameContext, HavocEngine, and transient roll state.
    Sessions are created explicitly and are never selected implicitly.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.ctx = GameContext(db_path=db_path)
        self.engine = HavocEngine()

    def create_session(self) -> ResourceResponse:
        """Create an isolated game session and return its initial state."""
        session = self.ctx.db.create_session()
        return self._format_response(
            session,
            compute_affordances(self.ctx, session.id),
            session.id,
        )

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidInputError(
                "session_id is required for stateful operations.",
                details={"parameter": "session_id"},
            )
        return session_id

    def _state_revision(self, session_id: str | None) -> int | None:
        if not session_id:
            return None
        session = self.ctx.get_session(session_id)
        return session.state_revision if session else None

    def _format_response(self, data: Any, affordances: list, session_id: str | None) -> ResourceResponse:
        return format_response(
            data,
            affordances,
            state_revision=self._state_revision(session_id),
        )

    def _format_action_response(
        self,
        data: Any,
        affordances: list,
        events: list,
        session_id: str,
    ) -> ActionResponse:
        return format_action_response(
            data,
            affordances,
            events,
            state_revision=self._state_revision(session_id),
        )

    @staticmethod
    def _require_mapping(
        value: Mapping[str, Any] | None,
        parameter_name: str,
    ) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise InvalidInputError(f"{parameter_name} must be a mapping.")
        return dict(value)

    def get(
        self,
        resource_type: str,
        id: str = "",
        session_id: str = "",
    ) -> ResourceResponse:
        """Retrieve a resource by type and ID."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        if resource_type == "session":
            sid = self._require_session_id(sid)
            target_id = id or sid
            session = self.ctx.get_session(target_id)
            if not session:
                raise ResourceNotFoundError(
                    f"Session {target_id} not found.",
                    details={"resource_type": "session", "id": target_id},
                )
            affordances = compute_affordances(self.ctx, target_id)
            return self._format_response(session, affordances, target_id)
        if resource_type == "character":
            sid = self._require_session_id(sid)
            char = self.ctx.db.get_character(id)
            if not char or char.session_id != sid:
                raise ResourceNotFoundError(
                    f"Character {id} not found.",
                    details={"resource_type": "character", "id": id},
                )
            sheet = self.ctx.get_character_sheet(id)
            affordances = compute_affordances(self.ctx, sid)
            return self._format_response(sheet, affordances, sid)
        if resource_type == "character_template":
            template = self.ctx.get_character_template(id)
            if not template:
                raise ResourceNotFoundError(
                    f"Character template {id} not found.",
                    details={"resource_type": "character_template", "id": id},
                )
            return self._format_response(template, [], None)
        if resource_type == "location":
            loc = self.ctx.get_location_template(id)
            if not loc:
                raise ResourceNotFoundError(
                    f"Location {id} not found.",
                    details={"resource_type": "location", "id": id},
                )
            return self._format_response(loc, [], None)
        if resource_type == "scene":
            sid = self._require_session_id(sid)
            scene = self.ctx.get_active_scene(sid)
            if not scene:
                raise ResourceNotFoundError(
                    "No active scene.",
                    details={"resource_type": "scene", "session_id": sid},
                )
            affordances = compute_affordances(self.ctx, sid)
            return self._format_response(scene, affordances, sid)
        if resource_type == "enemy":
            enemy = self.ctx.get_enemy_template(id)
            if not enemy:
                raise ResourceNotFoundError(
                    f"Enemy {id} not found.",
                    details={"resource_type": "enemy", "id": id},
                )
            return self._format_response(enemy, [], None)
        if resource_type == "rules":
            rules = self.ctx.graph.get_rules()
            return self._format_response(rules, [], None)
        raise UnsupportedOperationError(
            f"Unknown resource type: {resource_type}",
            details={"operation": "get", "resource_type": resource_type},
        )

    def search(
        self,
        resource_type: str,
        filters: Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> ResourceResponse:
        """Search or browse resources."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        parsed = self._require_mapping(filters, "filters")
        if resource_type == "characters":
            templates = self.ctx.get_all_character_templates()
            results = [{"id": t.id, "name": t.name, "description": t.description[:100]} for t in templates]
            affordances = compute_affordances(self.ctx, self._require_session_id(sid)) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "locations":
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
            affordances = compute_affordances(self.ctx, self._require_session_id(sid)) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "enemies":
            results = self.ctx.graph.get_all_enemies()
            affordances = compute_affordances(self.ctx, self._require_session_id(sid)) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "ubermenschen":
            results = self.ctx.graph.get_ubermenschen()
            affordances = compute_affordances(self.ctx, self._require_session_id(sid)) if sid else []
            return self._format_response(results, affordances, sid or None)
        raise UnsupportedOperationError(
            f"Unknown search type: {resource_type}",
            details={"operation": "search", "resource_type": resource_type},
        )

    def act(
        self,
        action: str,
        params: Mapping[str, Any] | None = None,
        session_id: str = "",
        expected_revision: int | None = None,
        affordance_id: str | None = None,
    ) -> ActionResponse:
        """Execute one state transition under the runtime connection lock."""
        with self.ctx.db.connection_lock:
            return self._act_impl(
                action,
                params,
                session_id,
                expected_revision,
                affordance_id,
            )

    def _act_impl(
        self,
        action: str,
        params: Mapping[str, Any] | None = None,
        session_id: str = "",
        expected_revision: int | None = None,
        affordance_id: str | None = None,
    ) -> ActionResponse:
        """Execute an action discovered via affordances."""
        sid = self._require_session_id(session_id)
        parsed = self._require_mapping(params, "params")

        session_before = self.ctx.get_session(sid)
        if not session_before:
            raise ResourceNotFoundError(
                f"Session {sid} not found.",
                details={"resource_type": "session", "id": sid},
            )
        if expected_revision is None:
            raise InvalidInputError(
                "expected_revision is required for mutating actions.",
                details={"parameter": "expected_revision"},
            )
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
        ):
            raise InvalidInputError(
                "expected_revision must be an integer.",
                details={"parameter": "expected_revision"},
            )

        pre_affordances = compute_affordances(self.ctx, sid)
        if affordance_id:
            candidates = [a for a in pre_affordances if a.id == affordance_id]
            if candidates and candidates[0].action != action:
                raise UnavailableActionError(
                    f"Affordance {affordance_id} does not authorize action {action}.",
                    details={"affordance_id": affordance_id, "action": action},
                )
        else:
            candidates = [a for a in pre_affordances if a.action == action]
        if not candidates:
            raise UnavailableActionError(
                f"Action {action} is not currently available.",
                details={
                    "action": action,
                    "affordance_id": affordance_id,
                    "state_revision": session_before.state_revision,
                },
            )
        validated = [
            (candidate, validate_parameters(candidate, parsed))
            for candidate in candidates
        ]
        matching = [candidate for candidate, errors in validated if not errors]
        if not matching:
            parameter_errors = min((errors for _, errors in validated), key=len)
            raise InvalidParameterError(
                f"Invalid parameters for {action}: {'; '.join(parameter_errors)}.",
                details={"action": action, "errors": parameter_errors},
            )
        if expected_revision != session_before.state_revision:
            raise StaleStateError(
                f"Session {sid} is at revision {session_before.state_revision}, "
                f"not {expected_revision}.",
                details={
                    "session_id": sid,
                    "expected_revision": expected_revision,
                    "current_revision": session_before.state_revision,
                },
            )
        try:
            result, events = self._dispatch_and_record(
                sid,
                action,
                parsed,
                expected_revision,
                session_before,
                pre_affordances,
            )
            affordances = compute_affordances(self.ctx, sid)
            return self._format_action_response(result, affordances, events, sid)
        except KeyError as error:
            missing = str(error.args[0]) if error.args else "unknown"
            raise InvalidInputError(
                f"Missing required action parameter: {missing}.",
                details={"action": action, "parameter": missing},
            ) from error

    def _dispatch_and_record(
        self,
        session_id: str,
        action: str,
        params: dict,
        expected_revision: int,
        session_before,
        pre_affordances: list,
    ):
        """Atomically claim a revision, mutate state, and record the decision."""
        with self.ctx.db.transaction():
            if not self.ctx.db.claim_session_revision(session_id, expected_revision):
                current = self.ctx.get_session(session_id)
                current_revision = current.state_revision if current else None
                raise StaleStateError(
                    f"Session {session_id} changed while the action was being validated.",
                    details={
                        "session_id": session_id,
                        "expected_revision": expected_revision,
                        "current_revision": current_revision,
                    },
                )

            phase_before = session_before.phase.value
            actor_id = session_before.active_character_id or "system"
            actor_name = ""
            if actor_id != "system":
                actor_char = self.ctx.db.get_character(actor_id)
                actor_name = actor_char.name if actor_char else ""

            affordances_snapshot = [
                {
                    "id": a.id,
                    "action": a.action,
                    "description": a.description,
                    "schema": a.schema_,
                    "constraints": a.constraints,
                }
                for a in pre_affordances
            ]
            affordances_not_taken = [
                a.action for a in pre_affordances if a.action != action
            ]

            result, events = self._dispatch_action(session_id, action, params)
            session_after = self.ctx.get_session(session_id)
            phase_after = session_after.phase.value if session_after else phase_before
            result_data = result if isinstance(result, dict) else {}
            decision = DecisionRecord(
                session_id=session_id,
                actor_id=actor_id,
                actor_name=actor_name,
                action=action,
                params=params,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                result_summary=result_data.get("message", "")[:200],
                events=[e.model_dump() for e in events],
                phase_before=phase_before,
                phase_after=phase_after,
            )
            self.ctx.db.record_decision(decision)
            return result, events

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

            ctx.db.save_pending_roll(session_id, roll, player_kept, gm_kept)

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

            pending = ctx.db.get_pending_roll(session_id)
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

            ctx.db.delete_pending_roll(session_id)

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

            pending = ctx.db.get_pending_roll(session_id)
            if not pending:
                raise DomainError("No pending roll for flashback.")

            new_roll, new_kept = engine.use_flashback(active_char, pending["roll"])
            ctx.db.save_pending_roll(session_id, new_roll, new_kept, pending["gm_kept"])

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
# Module-level server entry point. Stateful requests must carry their session
# handle; importing this module does not create a game.
# ---------------------------------------------------------------------------

_default = GameRuntime()
_legacy = JsonGameRuntimeAdapter(_default)
ctx = _default.ctx
engine = _default.engine


# --- Tools ---

mcp = MCPServer(
    name="gia-eat-the-reich",
    title="GIA — EAT THE REICH",
    description="Affordance-driven TTRPG backend for the EAT THE REICH campaign.",
    instructions=(
        "Create a session before stateful requests. Pass the returned session_id "
        "on every get, search, and act call that reads or mutates game state. "
        "Use only actions advertised in affordances and include expected_revision "
        "for mutations."
    ),
    version="0.2.0",
)


@mcp.tool()
def create_session() -> str:
    """Create an isolated game session and return its handle and state."""
    return _legacy.create_session()


@mcp.tool()
def get(resource_type: str, id: str = "", session_id: str = "") -> str:
    """Retrieve a resource by type and ID. Returns data + available affordances.

    resource_type: "session", "character", "character_template", "location", "scene", "enemy", "rules"
    id: resource ID (template_id for templates, character_id for characters, etc.)
    session_id: required for stateful resources; omit for immutable knowledge
    """
    return _legacy.get(resource_type, id, session_id)


@mcp.tool()
def search(resource_type: str, filters: str = "{}", session_id: str = "") -> str:
    """Search/browse resources. Returns results + available affordances.

    resource_type: "characters", "locations", "enemies", "ubermenschen"
    filters: JSON string, e.g. {"sector": 3} for locations
    session_id: required only when requesting state affordances
    """
    return _legacy.search(resource_type, filters, session_id)


@mcp.tool()
def act(
    action: str,
    params: str = "{}",
    session_id: str = "",
    expected_revision: int | None = None,
    affordance_id: str | None = None,
) -> str:
    """Execute an action discovered via affordances. Returns result + next affordances.

    action: action name from affordances
    params: JSON string of action parameters
    session_id: required
    """
    return _legacy.act(action, params, session_id, expected_revision, affordance_id)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        host = os.environ.get("MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MCP_PORT", "8000"))
        allowed_hosts = [
            item.strip()
            for item in os.environ.get(
                "MCP_ALLOWED_HOSTS",
                f"{host},localhost,127.0.0.1",
            ).split(",")
            if item.strip()
        ]
        mcp.run(
            "streamable-http",
            host=host,
            port=port,
            stateless_http=True,
            transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
        )
    else:
        mcp.run("stdio")
