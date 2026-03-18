"""Task definition schema for eval tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskDefinition(BaseModel):
    id: str
    tier: int  # 1-4
    name: str
    description: str  # natural language prompt for the LLM
    acting_user_id: str | None = None  # optional per-task user override
    setup: dict = Field(default_factory=dict)  # scenario state to seed
    oracle: list[dict] = Field(default_factory=list)  # post-condition checks
    max_turns: int = 50
