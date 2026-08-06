"""Transport-neutral response envelopes for the GIA runtime."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .domain import DomainError
from .models import Affordance, DiceRoll, DomainEvent


class ResourceResponse(BaseModel):
    """Result of a runtime read or search operation."""

    data: Any
    affordances: list[Affordance] = Field(default_factory=list)


class ActionResponse(ResourceResponse):
    """Result of a successful state transition."""

    events: list[DomainEvent] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    """Machine-readable description of a failed runtime request."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Typed error envelope used by transport adapters."""

    error: ErrorDetail
    affordances: list[Affordance] = Field(default_factory=list)


def _serialize_data(data: Any) -> Any:
    """Convert domain models into plain values at the response boundary."""
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if isinstance(data, list):
        return [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in data
        ]
    return data


def format_response(data: Any, affordances: list[Affordance]) -> ResourceResponse:
    """Build a typed resource response."""
    return ResourceResponse(data=_serialize_data(data), affordances=affordances)


def format_action_response(
    data: Any,
    affordances: list[Affordance],
    events: list[DomainEvent],
) -> ActionResponse:
    """Build a typed action response."""
    return ActionResponse(
        data=_serialize_data(data),
        affordances=affordances,
        events=events,
    )


def format_error(error: DomainError, affordances: list[Affordance]) -> ErrorResponse:
    """Build a typed error response for a protocol compatibility adapter."""
    return ErrorResponse(
        error=ErrorDetail(
            code=error.code,
            message=str(error),
            details=error.details,
        ),
        affordances=affordances,
    )


def format_dice_roll(roll: DiceRoll) -> str:
    """Format a dice roll result for display."""
    lines = []
    lines.append(f"Pool: {roll.pool_size}d6 → {roll.results}")

    if roll.discarded:
        lines.append(f"Discarded (failures): {roll.discarded}")
    if roll.kept:
        successes = sum(2 if d == 6 else 1 for d in roll.kept)
        crits = sum(1 for d in roll.kept if d == 6)
        lines.append(f"Kept: {roll.kept} ({successes} successes, {crits} criticals)")
    else:
        lines.append("Kept: none — total miss!")

    if roll.gm_pool_size > 0:
        lines.append(f"\nGM Attack: {roll.gm_pool_size}d6 → {roll.gm_results}")
        if roll.gm_discarded:
            lines.append(f"GM Discarded: {roll.gm_discarded}")
        if roll.gm_kept:
            lines.append(f"GM Kept: {roll.gm_kept} ({len(roll.gm_kept)} hits)")
        else:
            lines.append("GM Kept: none — attack whiffed!")

    return "\n".join(lines)
