"""Engagement + roll/allocation commands (PR 4): build_dice_pool, retreat,
allocate_dice, use_flashback.

Each reproduces the engagement_pre_roll/engagement_post_roll branch that
used to live in `affordances.py`/`server.py::_dispatch_action`. Domain
mechanics (dice pools, allocation, injuries) stay in `HavocEngine`; these
commands only orchestrate them, per PR 4's "preserve domain mechanics"
scope.
"""

from __future__ import annotations

import random

from gia.capabilities import EffectMetadata
from havoc_domain.context import GameContext
from gia_core.contracts import DomainEvent
from gia_core.errors import DomainError
from havoc_domain.engine import HavocEngine
from havoc_domain.models import GamePhase, ObjectiveState
from gia.responses import format_dice_roll
from gia.policy import Actor
from gia_core.command import Binding, Command, Snapshot

DEFAULT_STATS = ["brawl", "con", "fix", "search", "shoot", "sneak", "terrify"]


class BuildDicePoolCommand(Command):
    name = "build_dice_pool"
    effects = EffectMetadata(mutating=True)
    # No validate() override — relies on Command's default schema check, so
    # the fields below (optional in the binding's input_schema) must be
    # declared here too (PR 14 of the GIA/GAS 2.0 plan; see
    # src/gia_core/command.py::Command.optional_parameters).
    optional_parameters = frozenset({"equipment_names", "ability_name", "bonus_dice"})

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.engagement_pre_roll:
            return []
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        scene = snapshot.ctx.get_active_scene(session.id)
        if not (active_char and scene):
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="Choose stat and equipment, then roll dice",
                input_schema={
                    "stat": {
                        "type": "string",
                        "enum": list(active_char.model_dump().get("stats", {}).keys())
                        or DEFAULT_STATS,
                    },
                    "equipment_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Equipment to use (spends 1 use each)",
                    },
                    "ability_name": {
                        "type": "string",
                        "description": "Ability to use (optional)",
                    },
                    "bonus_dice": {
                        "type": "integer",
                        "description": "Bonus dice from conditions (optional)",
                        "default": 0,
                    },
                },
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        active_char = (
            ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char:
            raise DomainError("No active character.")

        scene = ctx.get_active_scene(session.id)
        if not scene:
            raise DomainError("No active scene.")

        stat_name = input.get("stat", "brawl")
        template = ctx.get_character_template(active_char.template_id)
        if not template:
            raise DomainError("Character template not found.")

        stat_value = template.stats.get(stat_name, 2)

        sheet = ctx.get_character_sheet(active_char.id)
        if sheet:
            stat_value = sheet["effective_stats"].get(stat_name, stat_value)

        equipment_used = []
        for eq_name in input.get("equipment_names", []):
            eq = HavocEngine.use_equipment(active_char, eq_name)
            equipment_used.append(eq)

        bonus_dice = input.get("bonus_dice", 0)
        ability_dice = 1 if input.get("ability_name") else 0

        pool_size = HavocEngine.build_pool_size(
            stat_value, equipment_used, ability_dice, bonus_dice,
        )

        engine = HavocEngine()
        gm_attack = engine.get_total_gm_attack(scene)

        discard_threshold = 3
        for threat in scene.active_threats:
            if threat.name == "Rust-Witch" and not threat.is_defeated:
                discard_threshold = 4
                break

        roll, player_kept, gm_kept = engine.resolve_roll(pool_size, gm_attack, discard_threshold)
        roll.session_id = session.id
        roll.character_id = active_char.id
        roll.scene_id = scene.id

        ctx.db.save_pending_roll(session.id, roll, player_kept, gm_kept)
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


class RetreatCommand(Command):
    name = "retreat"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.engagement_pre_roll:
            return []
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        scene = snapshot.ctx.get_active_scene(session.id)
        if not (active_char and scene):
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="Attempt to retreat from engagement (creates Escape objective)",
                input_schema={},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        scene = ctx.get_active_scene(session.id)
        if not scene:
            raise DomainError("No active scene.")

        escape_rating = random.randint(4, 6)
        scene.active_objectives.append(ObjectiveState(name="Escape!", current_rating=escape_rating))
        ctx.db.update_scene(scene)

        session.phase = GamePhase.exploration
        ctx.db.update_session(session)

        return {"message": f"Retreating! New objective: Escape! (rating {escape_rating})"}, []


class AllocateDiceCommand(Command):
    name = "allocate_dice"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.engagement_post_roll:
            return []
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char:
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="Allocate kept dice to objectives, threats, defense, feed, or special",
                input_schema={
                    "allocations": {
                        "type": "object",
                        "properties": {
                            "objective": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Dice values allocated to objective",
                            },
                            "threat": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Dice values allocated to threat",
                            },
                            "defense": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Dice values allocated to defense",
                            },
                            "feed": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Dice values allocated to feeding",
                            },
                            "special": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Dice values allocated to special (6 only)",
                            },
                        },
                    },
                },
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        engine = HavocEngine()
        events: list[DomainEvent] = []

        active_char = (
            ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char:
            raise DomainError("No active character.")

        scene = ctx.get_active_scene(session.id)
        if not scene:
            raise DomainError("No active scene.")

        pending = ctx.db.get_pending_roll(session.id)
        if not pending:
            raise DomainError("No pending roll to allocate.")

        allocations = input.get("allocations", {})
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

        ctx.db.delete_pending_roll(session.id)

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
            alive = [
                c for c in ctx.db.get_session_characters(session.id)
                if not c.is_dead and not c.is_downed
            ]
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
                    {
                        "name": t.name, "rating": t.current_rating,
                        "attack": t.current_attack, "defeated": t.is_defeated,
                    }
                    for t in scene.active_threats
                ],
            },
        }, events


class UseFlashbackCommand(Command):
    name = "use_flashback"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.engagement_post_roll:
            return []
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char or active_char.flashback_used:
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="Use flashback: add 2 dice and reroll everything (once per session)",
                input_schema={},
                constraints=["Can only be used when you rolled 2 or fewer successes"],
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        active_char = (
            ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char:
            raise DomainError("No active character.")

        pending = ctx.db.get_pending_roll(session.id)
        if not pending:
            raise DomainError("No pending roll for flashback.")

        engine = HavocEngine()
        new_roll, new_kept = engine.use_flashback(active_char, pending["roll"])
        ctx.db.save_pending_roll(session.id, new_roll, new_kept, pending["gm_kept"])
        ctx.db.update_character(active_char)

        return {
            "message": f"{active_char.name} triggers a flashback! Rerolling with 2 extra dice!",
            "roll_summary": format_dice_roll(new_roll),
            "player_kept": new_kept,
            "gm_kept": pending["gm_kept"],
        }, []
