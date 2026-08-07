"""The `heal` command — PR 3's vertical slice through the command-policy kernel.

Chosen over simpler actions (e.g. `check_inventory`) because it has
everything PR 3 needs to prove before PR 4 migrates the rest of the game:
a target (the character being healed), a non-trivial precondition (enough
Blood *and* an unhealed injury in the requested category), parameters,
a mutation, and a domain event.

`applicable` reproduces the between_scenes healing loop that used to live in
`affordances.py`; `execute` reproduces the `heal` branch that used to live in
`server.py::_dispatch_action`. Both are deleted from those modules in this
PR — see `src/gia/commands/kernel.py` for the glue that routes them here.
"""

from __future__ import annotations

from gia.capabilities import EffectMetadata
from gia_core.contracts import DomainEvent
from gia_core.errors import DomainError
from havoc_domain.engine import HavocEngine
from havoc_domain.models import CharacterState, GamePhase
from gia.policy import Actor
from gia_core.command import Binding, Command, Snapshot

HEAL_BLOOD_COST = 3


def _unhealed_categories(character: CharacterState) -> list[str]:
    return [
        injury.category
        for injury in character.injuries
        if injury.minor_marked or injury.major_marked
    ]


class HealCommand(Command):
    name = "heal"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        if snapshot.session.phase != GamePhase.between_scenes:
            return []

        bindings: list[Binding] = []
        for character in snapshot.ctx.db.get_session_characters(snapshot.session.id):
            if character.is_dead or character.blood < HEAL_BLOOD_COST:
                continue
            injured_categories = _unhealed_categories(character)
            if not injured_categories:
                continue
            bindings.append(
                Binding(
                    command=self.name,
                    target={"resource_type": "character", "id": character.id},
                    title=f"Heal {character.name} (costs {HEAL_BLOOD_COST} Blood, has {character.blood})",
                    input_schema={
                        "character_id": {"type": "string", "const": character.id},
                        "category": {"type": "string", "enum": injured_categories},
                    },
                )
            )
        return bindings

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)  # binding.input_schema shape

        character_id = input["character_id"]
        category = input["category"]
        character = snapshot.ctx.db.get_character(character_id)
        if not character or character.session_id != snapshot.session.id:
            raise DomainError(f"Character {character_id} not found.")
        if character.is_dead:
            raise DomainError(f"{character.name} is dead and cannot be healed.")
        if character.blood < HEAL_BLOOD_COST:
            raise DomainError(
                f"{character.name} needs {HEAL_BLOOD_COST} Blood to heal (has {character.blood})."
            )
        if category not in _unhealed_categories(character):
            raise DomainError(f"{character.name} has no unhealed injury in category {category!r}.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        character = snapshot.ctx.db.get_character(input["character_id"])
        category = input["category"]
        event = HavocEngine.heal_injury(character, category)
        snapshot.ctx.db.update_character(character)
        result = {"message": f"Healed {character.name}'s injury in category {category}."}
        return result, [event] if event else []
