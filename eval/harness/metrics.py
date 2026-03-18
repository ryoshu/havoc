"""Metrics collection for eval runs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TurnDetail(BaseModel):
    turn_number: int = 0
    action: str = ""
    params: dict = Field(default_factory=dict)
    was_valid: bool = True
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    state_changed: bool = False
    error_message: str = ""


class EvalMetrics(BaseModel):
    # Run identity
    task_id: str = ""
    task_tier: int = 0
    mode: str = ""  # "gas" or "trad-15" / "trad-30" / "trad-60"
    model_name: str = ""

    # Aggregate metrics
    total_turns: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    invalid_action_count: int = 0
    valid_action_count: int = 0
    error_recovery_turns: int = 0
    time_to_first_valid_action: int = 0
    redundant_calls: int = 0
    affordance_utilization: float = 0.0  # GAS only: fraction of valid actions used
    task_completed: bool = False
    oracle_passed: bool = False
    elapsed_seconds: float = 0.0

    # Per-turn details
    turns: list[TurnDetail] = Field(default_factory=list)

    # Oracle details
    oracle_details: list[dict] = Field(default_factory=list)

    @property
    def invalid_action_rate(self) -> float:
        total = self.valid_action_count + self.invalid_action_count
        if total == 0:
            return 0.0
        return self.invalid_action_count / total

    @property
    def total_tokens(self) -> int:
        return self.total_tokens_in + self.total_tokens_out
