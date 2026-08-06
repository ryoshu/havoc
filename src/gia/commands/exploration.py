"""Exploration-phase commands (PR 4): move_to_location, engage_threat, loot,
check_inventory, next_turn.

Each reproduces the exploration-phase branch that used to live in
`affordances.py`/`server.py::_dispatch_action`.
"""

from __future__ import annotations

from ..capabilities import EffectMetadata
from ..context import GameContext
from ..domain import DomainError, DomainEvent, HavocEngine
from ..models import EquipmentState, GamePhase
from .base import Actor, Binding, Command, Snapshot


class MoveToLocationCommand(Command):
    name = "move_to_location"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.exploration or not session.current_location_id:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "location", "id": loc.id},
                title=f"Move to {loc.name} (Sector {loc.sector})",
                input_schema={"location_id": {"type": "string", "const": loc.id}},
            )
            for loc in snapshot.ctx.get_connected_locations(session.current_location_id)
        ]

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)
        if not snapshot.ctx.get_location_template(input["location_id"]):
            raise DomainError(f"Location {input['location_id']} not found.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        location_id = input["location_id"]
        loc = ctx.get_location_template(location_id)
        if not loc:
            raise DomainError(f"Location {location_id} not found.")

        session.current_location_id = location_id
        session.scene_number += 1
        session.round_number = 1
        session.phase = GamePhase.exploration
        ctx.db.update_session(session)

        for character in ctx.db.get_session_characters(session.id):
            if not character.is_dead:
                character.current_location_id = location_id
                ctx.db.update_character(character)

        scene = ctx.create_scene_from_location(session.id, location_id)

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


class EngageThreatCommand(Command):
    name = "engage_threat"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.exploration:
            return []
        scene = snapshot.ctx.get_active_scene(session.id)
        if not scene:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "threat", "id": threat.name},
                title=(
                    f"Engage {threat.name} (rating {threat.current_rating}, "
                    f"attack {threat.current_attack})"
                ),
                input_schema={"threat_name": {"type": "string", "const": threat.name}},
            )
            for threat in scene.active_threats
            if not threat.is_defeated
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        session.phase = GamePhase.engagement_pre_roll
        ctx.db.update_session(session)
        scene = ctx.get_active_scene(session.id)
        threat_name = input.get("threat_name", "")
        threat = None
        if scene:
            for t in scene.active_threats:
                if t.name == threat_name and not t.is_defeated:
                    threat = t
                    break

        result = {"message": f"Engaging {threat_name}!"}
        if threat:
            result["threat"] = {
                "name": threat.name,
                "rating": threat.current_rating,
                "attack": threat.current_attack,
                "challenge": threat.challenge,
            }
        return result, []


class LootCommand(Command):
    name = "loot"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.exploration:
            return []
        if not snapshot.ctx.get_active_scene(session.id):
            return []
        if not session.current_location_id:
            return []
        loc = snapshot.ctx.get_location_template(session.current_location_id)
        if not loc or not loc.loot:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "loot", "id": loot.name},
                title=f"Loot: {loot.name} ({loot.bonus_condition or 'no bonus'})",
                input_schema={"item_name": {"type": "string", "const": loot.name}},
            )
            for loot in loc.loot
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        item_name = input.get("item_name", "")
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
        event = HavocEngine.loot_item(active_char, item)
        ctx.db.update_character(active_char)
        return {
            "message": f"{active_char.name} loots {item_name}!",
            "item": item.model_dump(),
        }, [event]


class CheckInventoryCommand(Command):
    name = "check_inventory"
    effects = EffectMetadata(mutating=False)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.exploration:
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
                target={"resource_type": "character", "id": active_char.id},
                title=f"Check {active_char.name}'s equipment",
                input_schema={},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        session = snapshot.session
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char:
            raise DomainError("No active character.")
        return {
            "character": active_char.name,
            "blood": active_char.blood,
            "equipment": [e.model_dump() for e in active_char.equipment],
            "injuries": [i.model_dump() for i in active_char.injuries],
        }, []


class NextTurnCommand(Command):
    name = "next_turn"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.exploration:
            return []
        characters = snapshot.ctx.db.get_session_characters(session.id)
        alive = [c for c in characters if not c.is_dead]
        if len(alive) <= 1:
            return []
        others = [c for c in alive if c.id != session.active_character_id]
        return [
            Binding(
                command=self.name,
                target=None,
                title="Switch to another character's turn",
                input_schema={"character_id": {"type": "string", "enum": [c.id for c in others]}},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        char_id = input["character_id"]
        char = ctx.db.get_character(char_id)
        if not char:
            raise DomainError(f"Character {char_id} not found.")
        session.active_character_id = char_id
        ctx.db.update_session(session)
        return {"message": f"It's {char.name}'s turn.", "active_character": char.name}, []
