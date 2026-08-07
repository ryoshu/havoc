"""share_blood (PR 4): one command, two binding shapes.

`affordances.py` used to project this action twice with different schemas:
in `exploration` the acting character is the implicit giver (schema has no
`giver_id`); in `between_scenes` any Blood-holding character can give, so
the schema names `giver_id` explicitly. Both are one command here — the
shape difference is a binding detail, not a reason to split the policy.
"""

from __future__ import annotations

from gia.capabilities import EffectMetadata
from gia_core.contracts import DomainEvent
from gia_core.errors import DomainError
from havoc_domain.engine import HavocEngine
from havoc_domain.models import GamePhase
from gia.policy import Actor
from gia_core.command import Binding, Command, Snapshot


class ShareBloodCommand(Command):
    name = "share_blood"
    effects = EffectMetadata(mutating=True)

    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        session = snapshot.session
        characters = snapshot.ctx.db.get_session_characters(session.id)
        alive = [c for c in characters if not c.is_dead]
        bindings: list[Binding] = []

        if session.phase == GamePhase.exploration:
            active_char = (
                snapshot.ctx.db.get_character(session.active_character_id)
                if session.active_character_id
                else None
            )
            if len(alive) > 1 and active_char and active_char.blood > 0:
                others = [c for c in alive if c.id != active_char.id]
                bindings.append(
                    Binding(
                        command=self.name,
                        target={"resource_type": "character", "id": active_char.id},
                        title="Share Blood with another vampire",
                        input_schema={
                            "receiver_id": {"type": "string", "enum": [c.id for c in others]},
                            "amount": {"type": "integer", "minimum": 1},
                        },
                    )
                )

        if session.phase == GamePhase.between_scenes:
            for giver in alive:
                if giver.blood <= 0:
                    continue
                others = [c for c in alive if c.id != giver.id]
                if not others:
                    continue
                bindings.append(
                    Binding(
                        command=self.name,
                        target={"resource_type": "character", "id": giver.id},
                        title=f"{giver.name} shares Blood (has {giver.blood})",
                        input_schema={
                            "giver_id": {"type": "string", "const": giver.id},
                            "receiver_id": {"type": "string", "enum": [c.id for c in others]},
                            "amount": {"type": "integer", "minimum": 1},
                        },
                    )
                )

        return bindings

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        super().validate(snapshot, actor, binding, input)
        giver_id = binding.target["id"] if binding.target else None
        if "giver_id" in binding.input_schema and input.get("giver_id", giver_id) != giver_id:
            raise DomainError("Binding does not authorize this giver.")
        if not snapshot.ctx.db.get_character(giver_id):
            raise DomainError("Character not found.")
        if not snapshot.ctx.db.get_character(input["receiver_id"]):
            raise DomainError("Character not found.")

    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        ctx = snapshot.ctx
        giver_id = input.get("giver_id", snapshot.session.active_character_id)
        receiver_id = input["receiver_id"]
        amount = input.get("amount", 1)

        giver = ctx.db.get_character(giver_id)
        receiver = ctx.db.get_character(receiver_id)
        if not giver or not receiver:
            raise DomainError("Character not found.")

        event = HavocEngine.share_blood(giver, receiver, amount)
        ctx.db.update_character(giver)
        ctx.db.update_character(receiver)
        return {"message": f"{giver.name} shares {amount} Blood with {receiver.name}."}, [event]
