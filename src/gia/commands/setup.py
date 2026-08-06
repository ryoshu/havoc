"""Setup-phase commands (PR 4 of the GIA/GAS 2.0 plan): select_character,
view_character_template, start_mission.

Each `applicable`/`execute` pair reproduces the setup-phase branch that used
to live in `affordances.py`/`server.py::_dispatch_action`; see
`src/gia/commands/kernel.py` for the registry that replaces those branches.
"""

from __future__ import annotations

from ..capabilities import EffectMetadata
from ..context import GameContext
from ..domain import DomainError, DomainEvent
from ..models import GamePhase
from .base import Actor, Binding, Command, Snapshot


class SelectCharacterCommand(Command):
    name = "select_character"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase != GamePhase.setup:
            return []
        selected = {
            cs.template_id for cs in snapshot.ctx.db.get_session_characters(snapshot.session.id)
        }
        return [
            Binding(
                command=self.name,
                target={"resource_type": "character_template", "id": template.id},
                title=f"Select {template.name} — {template.description[:80]}...",
                input_schema={"template_id": {"type": "string", "const": template.id}},
            )
            for template in snapshot.ctx.get_all_character_templates()
            if template.id not in selected
        ]

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)
        template_id = input["template_id"]
        existing = snapshot.ctx.db.get_session_characters(snapshot.session.id)
        if any(c.template_id == template_id for c in existing):
            raise DomainError(f"Character {template_id} already selected.")
        if not snapshot.ctx.get_character_template(template_id):
            raise DomainError(f"Template {template_id} not found.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        cs = snapshot.ctx.create_character_state(snapshot.session.id, input["template_id"])
        return {"message": f"{cs.name} joins the mission!", "character_id": cs.id}, []


class ViewCharacterTemplateCommand(Command):
    name = "view_character_template"
    effects = EffectMetadata(mutating=False)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase != GamePhase.setup:
            return []
        return [
            Binding(
                command=self.name,
                target={"resource_type": "character_template", "id": template.id},
                title=f"View {template.name}'s full character sheet",
                input_schema={"template_id": {"type": "string", "const": template.id}},
            )
            for template in snapshot.ctx.get_all_character_templates()
        ]

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)
        if not snapshot.ctx.get_character_template(input["template_id"]):
            raise DomainError(f"Template {input['template_id']} not found.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        template = snapshot.ctx.get_character_template(input["template_id"])
        if not template:
            raise DomainError(f"Template {input['template_id']} not found.")
        return template.model_dump(), []


class StartMissionCommand(Command):
    name = "start_mission"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase != GamePhase.setup:
            return []
        selected = snapshot.ctx.db.get_session_characters(snapshot.session.id)
        if not selected:
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title=f"Begin the mission with {len(selected)} character(s)",
                input_schema={},
                constraints=[f"{len(selected)} character(s) selected"],
            )
        ]

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)
        if not snapshot.ctx.db.get_session_characters(snapshot.session.id):
            raise DomainError("Select at least one character first.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx: GameContext = snapshot.ctx
        session = snapshot.session
        characters = ctx.db.get_session_characters(session.id)
        if not characters:
            raise DomainError("Select at least one character first.")
        start_locations = [loc for loc in ctx.get_all_locations() if loc.sector == 3]
        start_loc = start_locations[0] if start_locations else ctx.get_all_locations()[0]

        session.phase = GamePhase.exploration
        session.current_location_id = start_loc.id
        session.active_character_id = characters[0].id
        session.scene_number = 1
        session.round_number = 1
        ctx.db.update_session(session)

        for character in characters:
            character.current_location_id = start_loc.id
            ctx.db.update_character(character)

        scene = ctx.create_scene_from_location(session.id, start_loc.id)

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
