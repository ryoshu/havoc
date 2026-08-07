"""Cross-phase commands (PR 4): view_character_sheet, view_scene.

Available in every phase except `setup`, mirroring the "Always available
(non-setup)" block that used to live in `affordances.py::compute_affordances`.
"""

from __future__ import annotations

from gia.capabilities import EffectMetadata
from gia_core.contracts import DomainEvent
from gia_core.errors import DomainError
from havoc_domain.models import GamePhase
from gia.policy import Actor
from gia_core.command import Binding, Command, Snapshot


class ViewCharacterSheetCommand(Command):
    name = "view_character_sheet"
    effects = EffectMetadata(mutating=False)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase == GamePhase.setup:
            return []
        characters = snapshot.ctx.db.get_session_characters(snapshot.session.id)
        alive = [c for c in characters if not c.is_dead]
        return [
            Binding(
                command=self.name,
                target=None,
                title="View a character's current status",
                input_schema={"character_id": {"type": "string", "enum": [c.id for c in alive]}},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        char_id = input.get("character_id", snapshot.session.active_character_id)
        if not char_id:
            raise DomainError("No character specified.")
        sheet = snapshot.ctx.get_character_sheet(char_id)
        if not sheet:
            raise DomainError(f"Character {char_id} not found.")
        return sheet, []


class ViewSceneCommand(Command):
    name = "view_scene"
    effects = EffectMetadata(mutating=False)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase == GamePhase.setup:
            return []
        if not snapshot.ctx.get_active_scene(snapshot.session.id):
            return []
        return [
            Binding(
                command=self.name,
                target=None,
                title="View current scene status (threats, objectives)",
                input_schema={},
            )
        ]

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        scene = snapshot.ctx.get_active_scene(snapshot.session.id)
        if not scene:
            raise DomainError("No active scene.")
        return scene.model_dump(), []
