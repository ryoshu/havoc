"""between_scenes, last_stand, and mission_complete commands (PR 4):
choose_next_location, trigger_last_stand, view_epilogue.

Each reproduces the phase branch that used to live in
`affordances.py`/`server.py::_dispatch_action`.
"""

from __future__ import annotations

from gia.capabilities import EffectMetadata
from havoc_domain.context import GameContext
from gia_core.contracts import DomainEvent
from gia_core.errors import DomainError
from havoc_domain.engine import HavocEngine
from havoc_domain.models import GamePhase
from gia.policy import Actor
from gia_core.command import Binding, Command, Snapshot


class ChooseNextLocationCommand(Command):
    name = "choose_next_location"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.between_scenes or not session.current_location_id:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "location", "id": loc.id},
                title=f"Move to {loc.name} (Sector {loc.sector}) — {loc.objective.name} ({loc.objective.rating})",
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


class TriggerLastStandCommand(Command):
    name = "trigger_last_stand"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        if session.phase != GamePhase.last_stand:
            return []
        active_char = (
            snapshot.ctx.db.get_character(session.active_character_id)
            if session.active_character_id
            else None
        )
        if not active_char or not active_char.is_dead:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "character", "id": active_char.id},
                title=f"{active_char.name}'s Last Stand! Roll 8D6 and allocate freely",
                input_schema={},
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

        engine = HavocEngine()
        results = engine.trigger_last_stand()
        total_successes = sum(2 if d == 6 else (1 if d >= 4 else 0) for d in results)

        alive = [
            c for c in ctx.db.get_session_characters(session.id)
            if not c.is_dead and c.id != active_char.id
        ]
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


class ViewEpilogueCommand(Command):
    name = "view_epilogue"
    effects = EffectMetadata(mutating=False)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase != GamePhase.mission_complete:
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="View the mission epilogue",
                input_schema={},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        characters = snapshot.ctx.db.get_session_characters(snapshot.session.id)
        survivors = [c for c in characters if not c.is_dead]
        fallen = [c for c in characters if c.is_dead]
        return {
            "message": "The vampires ride off into the sunrise. The war is over.",
            "survivors": [c.name for c in survivors],
            "fallen": [c.name for c in fallen],
        }, []
