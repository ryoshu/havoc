"""Domain logic — Havoc Engine mechanics for Eat the Reich.

The domain-neutral error hierarchy that used to live in this module has
moved to ``src.gia_core.errors`` (PR 14 of the GIA/GAS 2.0 plan); it is
re-exported here so every existing ``from .domain import DomainError, ...``
import keeps working unchanged. This module now holds only ``HavocEngine``,
the concrete game-mechanics half PR 18 will relocate to ``havoc-domain``.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from ..gia_core.errors import (
    DomainError,
    IdempotencyConflictError,
    InvalidInputError,
    InvalidParameterError,
    PolicyChangedError,
    ResourceNotFoundError,
    ScopeMismatchError,
    StaleStateError,
    StaleViewError,
    UnavailableActionError,
    UnsupportedOperationError,
)
from .models import (
    CharacterState,
    DiceAllocation,
    DiceRoll,
    DomainEvent,
    EquipmentState,
    GamePhase,
    GameSession,
    InjuryState,
    ObjectiveState,
    SceneState,
    ThreatState,
)

__all__ = [
    "DomainError",
    "IdempotencyConflictError",
    "InvalidInputError",
    "InvalidParameterError",
    "PolicyChangedError",
    "ResourceNotFoundError",
    "ScopeMismatchError",
    "StaleStateError",
    "StaleViewError",
    "UnavailableActionError",
    "UnsupportedOperationError",
    "HavocEngine",
]


class HavocEngine:
    """Implements the Havoc Engine game mechanics."""

    # --- Dice Mechanics ---

    @staticmethod
    def roll_pool(size: int) -> list[int]:
        return [random.randint(1, 6) for _ in range(size)]

    @staticmethod
    def discard_failures(results: list[int], discard_threshold: int = 3) -> tuple[list[int], list[int]]:
        """Split dice into kept (successes) and discarded (failures).

        Standard threshold is 3 (discard 1-3).
        Rust-Witch raises it to 4 (discard 1-4).
        """
        kept = [d for d in results if d > discard_threshold]
        discarded = [d for d in results if d <= discard_threshold]
        return kept, discarded

    @staticmethod
    def count_successes(die_value: int) -> int:
        """4-5 = 1 success, 6 = 2 successes (critical)."""
        if die_value == 6:
            return 2
        if die_value >= 4:
            return 1
        return 0

    @staticmethod
    def is_critical(die_value: int) -> bool:
        return die_value == 6

    # --- Dice Pool Building ---

    @staticmethod
    def build_pool_size(
        stat_value: int,
        equipment_used: list[EquipmentState] | None = None,
        ability_dice: int = 0,
        bonus_dice: int = 0,
        blood_dice: int = 0,
    ) -> int:
        """Calculate total dice pool size.

        Pool = stat + 1 per equipment used + 1 per ability used + bonus dice from conditions.
        Last use of a multi-use item adds 1 extra bonus die.
        """
        pool = stat_value + ability_dice + bonus_dice + blood_dice
        if equipment_used:
            for eq in equipment_used:
                pool += 1  # base die for using equipment
                # Last use bonus: if this is the last use AND item started with >1 use
                if eq.uses_remaining == 1:
                    pool += 1
        return pool

    # --- Combat Resolution ---

    def resolve_roll(
        self,
        player_pool_size: int,
        gm_attack: int,
        discard_threshold: int = 3,
    ) -> tuple[DiceRoll, list[int], list[int]]:
        """Roll both pools, discard failures, return roll record + kept dice.

        Returns: (partial DiceRoll, player_kept, gm_kept)
        """
        player_results = self.roll_pool(player_pool_size)
        gm_results = self.roll_pool(gm_attack) if gm_attack > 0 else []

        player_kept, player_discarded = self.discard_failures(player_results, discard_threshold)
        gm_kept, gm_discarded = self.discard_failures(gm_results, 3)  # GM always uses 3

        roll = DiceRoll(
            id=f"dr-{uuid.uuid4().hex[:8]}",
            session_id="",  # filled in by caller
            character_id="",
            scene_id="",
            pool_size=player_pool_size,
            results=player_results,
            discarded=player_discarded,
            kept=player_kept,
            gm_pool_size=gm_attack,
            gm_results=gm_results,
            gm_discarded=gm_discarded,
            gm_kept=gm_kept,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return roll, player_kept, gm_kept

    def apply_allocations(
        self,
        allocations: dict[str, list[int]],
        scene: SceneState,
        character: CharacterState,
        gm_kept: list[int],
    ) -> tuple[list[DomainEvent], list[int]]:
        """Apply dice allocations to scene state. Returns events and remaining GM dice."""
        events = []
        remaining_gm = list(gm_kept)

        # Objective allocation
        for die in allocations.get("objective", []):
            successes = self.count_successes(die)
            for obj in scene.active_objectives:
                if obj.is_completed:
                    continue
                effective = max(0, successes - obj.challenge)
                obj.current_rating = max(0, obj.current_rating - effective)
                if obj.current_rating == 0:
                    obj.is_completed = True
                    events.append(DomainEvent(
                        type="ObjectiveCompleted",
                        data={"objective": obj.name},
                    ))
                break  # allocate to first incomplete objective

        # Threat allocation
        for die in allocations.get("threat", []):
            successes = self.count_successes(die)
            for threat in scene.active_threats:
                if threat.is_defeated:
                    continue
                effective = max(0, successes - threat.challenge)
                threat.current_rating = max(0, threat.current_rating - effective)
                if threat.current_rating == 0:
                    threat.is_defeated = True
                    threat.current_attack = 0
                    events.append(DomainEvent(
                        type="ThreatDefeated",
                        data={"threat": threat.name},
                    ))
                break  # allocate to first active threat

        # Defense allocation
        for die in allocations.get("defense", []):
            successes = self.count_successes(die)
            for _ in range(successes):
                if remaining_gm:
                    remaining_gm.pop()

        # Feed allocation
        for die in allocations.get("feed", []):
            successes = self.count_successes(die)
            gained = min(successes, 10 - character.blood)
            character.blood += gained
            if gained > 0:
                events.append(DomainEvent(
                    type="BloodGained",
                    data={"amount": gained, "total": character.blood},
                ))

        # Special allocation (crit only)
        for die in allocations.get("special", []):
            if self.is_critical(die):
                events.append(DomainEvent(
                    type="SpecialActivated",
                    data={"die": die},
                ))

        return events, remaining_gm

    # --- Injury Resolution ---

    def resolve_injuries(
        self,
        remaining_gm_dice: list[int],
        character: CharacterState,
        injury_slots: dict,
    ) -> list[DomainEvent]:
        """Apply injuries based on remaining GM attack dice."""
        events = []

        if not remaining_gm_dice:
            return events

        is_downed = len(remaining_gm_dice) >= 3

        # Roll for injury category
        category_roll = random.randint(1, 6)
        if category_roll <= 2:
            category = "1-2"
        elif category_roll <= 4:
            category = "3-4"
        else:
            category = "5-6"

        if is_downed:
            # Mark ALL boxes in the category
            for inj in character.injuries:
                if inj.category == category:
                    inj.minor_marked = True
                    inj.major_marked = True
                    break
            character.is_downed = True
            events.append(DomainEvent(
                type="CharacterDowned",
                data={
                    "character": character.name,
                    "category": category,
                    "injury": injury_slots.get(category, {}).get("major", "Unknown"),
                },
            ))
        else:
            # Mark next available box in category
            for inj in character.injuries:
                if inj.category == category:
                    if not inj.minor_marked:
                        inj.minor_marked = True
                        events.append(DomainEvent(
                            type="InjuryMarked",
                            data={
                                "character": character.name,
                                "category": category,
                                "severity": "minor",
                                "injury": injury_slots.get(category, {}).get("minor", "Unknown"),
                            },
                        ))
                    elif not inj.major_marked:
                        inj.major_marked = True
                        slot = injury_slots.get(category, {})
                        events.append(DomainEvent(
                            type="InjuryMarked",
                            data={
                                "character": character.name,
                                "category": category,
                                "severity": "major",
                                "injury": slot.get("major", "Unknown"),
                                "penalty": slot.get("major_penalty", ""),
                            },
                        ))
                    else:
                        # Both marked in this category — pick alternate
                        for alt_inj in character.injuries:
                            if not alt_inj.minor_marked:
                                alt_inj.minor_marked = True
                                events.append(DomainEvent(
                                    type="InjuryMarked",
                                    data={
                                        "character": character.name,
                                        "category": alt_inj.category,
                                        "severity": "minor",
                                        "injury": injury_slots.get(alt_inj.category, {}).get("minor", "Unknown"),
                                        "note": f"Redirected from full category {category}",
                                    },
                                ))
                                break
                    break

        # Check for death
        total_injuries = sum(
            (1 if i.minor_marked else 0) + (1 if i.major_marked else 0)
            for i in character.injuries
        )
        if total_injuries >= 6:
            character.is_dead = True
            events.append(DomainEvent(
                type="CharacterDead",
                data={"character": character.name, "trigger": "last_stand"},
            ))

        return events

    # --- Reinforcements ---

    def apply_reinforcements(self, scene: SceneState, enemy_templates: dict) -> list[DomainEvent]:
        """End-of-round reinforcement rules."""
        events = []

        for threat in scene.active_threats:
            template = enemy_templates.get(threat.enemy_id)
            if not template:
                continue

            # Solo enemies don't reinforce
            if template.solo:
                if threat.is_defeated:
                    events.append(DomainEvent(
                        type="ThreatPermanentlyDefeated",
                        data={"threat": threat.name},
                    ))
                continue

            if threat.is_defeated:
                # Restore with d6 rating and half base attack
                new_rating = random.randint(1, 6)
                threat.current_rating = new_rating
                threat.current_attack = threat.base_attack // 2
                threat.is_defeated = False
                events.append(DomainEvent(
                    type="Reinforcements",
                    data={
                        "threat": threat.name,
                        "new_rating": new_rating,
                        "new_attack": threat.current_attack,
                    },
                ))
            else:
                # Increase attack by 1
                threat.current_attack += 1
                events.append(DomainEvent(
                    type="ThreatEscalation",
                    data={"threat": threat.name, "new_attack": threat.current_attack},
                ))

        return events

    # --- Healing ---

    @staticmethod
    def heal_injury(character: CharacterState, category: str) -> DomainEvent | None:
        """Spend 3 Blood to heal an injury."""
        if character.blood < 3:
            raise DomainError(f"{character.name} needs 3 Blood to heal (has {character.blood}).")

        for inj in character.injuries:
            if inj.category == category:
                if inj.major_marked:
                    inj.major_marked = False
                    character.blood -= 3
                    return DomainEvent(
                        type="InjuryHealed",
                        data={"character": character.name, "category": category, "severity": "major"},
                    )
                elif inj.minor_marked:
                    inj.minor_marked = False
                    character.blood -= 3
                    return DomainEvent(
                        type="InjuryHealed",
                        data={"character": character.name, "category": category, "severity": "minor"},
                    )
        raise DomainError(f"No injury to heal in category {category}.")

    # --- Blood Sharing ---

    @staticmethod
    def share_blood(giver: CharacterState, receiver: CharacterState, amount: int) -> DomainEvent:
        if giver.blood < amount:
            raise DomainError(f"{giver.name} only has {giver.blood} Blood.")
        if receiver.blood + amount > 10:
            amount = 10 - receiver.blood
        if amount <= 0:
            raise DomainError(f"{receiver.name} is already at max Blood.")

        giver.blood -= amount
        receiver.blood += amount
        return DomainEvent(
            type="BloodShared",
            data={
                "from": giver.name, "to": receiver.name,
                "amount": amount,
                "giver_blood": giver.blood, "receiver_blood": receiver.blood,
            },
        )

    # --- Flashback ---

    def use_flashback(self, character: CharacterState, current_roll: DiceRoll) -> tuple[DiceRoll, list[int]]:
        """Use flashback: add 2 dice and reroll everything."""
        if character.flashback_used:
            raise DomainError(f"{character.name} has already used their flashback this session.")

        character.flashback_used = True
        new_pool_size = current_roll.pool_size + 2
        new_results = self.roll_pool(new_pool_size)
        new_kept, new_discarded = self.discard_failures(new_results)

        new_roll = DiceRoll(
            id=f"dr-{uuid.uuid4().hex[:8]}",
            session_id=current_roll.session_id,
            character_id=current_roll.character_id,
            scene_id=current_roll.scene_id,
            pool_size=new_pool_size,
            results=new_results,
            discarded=new_discarded,
            kept=new_kept,
            gm_pool_size=current_roll.gm_pool_size,
            gm_results=current_roll.gm_results,
            gm_discarded=current_roll.gm_discarded,
            gm_kept=current_roll.gm_kept,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return new_roll, new_kept

    # --- Last Stand ---

    def trigger_last_stand(self) -> list[int]:
        """Roll 8D6 for a Last Stand. All dice kept (no discard)."""
        return self.roll_pool(8)

    # --- Equipment ---

    @staticmethod
    def use_equipment(character: CharacterState, equipment_name: str) -> EquipmentState:
        """Spend one use of equipment. Returns the equipment for pool calculation."""
        for eq in character.equipment:
            if eq.name == equipment_name and eq.uses_remaining > 0:
                eq.uses_remaining -= 1
                return eq
        raise DomainError(f"{character.name} cannot use '{equipment_name}' (not found or no uses left).")

    # --- Looting ---

    @staticmethod
    def loot_item(character: CharacterState, item: EquipmentState) -> DomainEvent:
        """Add a looted item to the character's equipment."""
        # Replace existing loot if any
        character.equipment = [e for e in character.equipment if not e.is_loot]
        item.is_loot = True
        character.equipment.append(item)
        return DomainEvent(
            type="ItemLooted",
            data={"character": character.name, "item": item.name},
        )

    # --- Scene Management ---

    @staticmethod
    def check_scene_complete(scene: SceneState) -> bool:
        """A scene is complete when all objectives are done."""
        return all(obj.is_completed for obj in scene.active_objectives)

    @staticmethod
    def get_total_gm_attack(scene: SceneState) -> int:
        """GM attack = highest active threat attack + 1 per additional active threat."""
        active = [t for t in scene.active_threats if not t.is_defeated]
        if not active:
            return 0
        active.sort(key=lambda t: t.current_attack, reverse=True)
        total = active[0].current_attack
        total += len(active) - 1  # +1 per extra active threat
        return total
