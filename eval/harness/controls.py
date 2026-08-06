"""Deterministic controls shared by every PR12 evaluation condition.

The model-facing interface is the experimental factor. History and retry
policies are deliberately represented as data so a matrix cannot silently use
different harness behavior for different renderers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


HistoryPolicyName = Literal["full", "compact-affordances"]


@dataclass(frozen=True)
class RetryPolicy:
    """A pinned retry budget and deterministic exponential backoff schedule."""

    max_attempts: int = 6
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
    honor_retry_after: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if any(delay < 0 for delay in self.backoff_seconds):
            raise ValueError("backoff_seconds cannot contain negative values")

    def delay_for(self, failed_attempt: int, retry_after: float | None = None) -> float:
        """Return the delay after a failed attempt (attempts are zero-based)."""
        if self.honor_retry_after and retry_after is not None:
            return max(0.0, retry_after)
        if not self.backoff_seconds:
            return 0.0
        index = min(max(failed_attempt, 0), len(self.backoff_seconds) - 1)
        return self.backoff_seconds[index]


DEFAULT_RETRY_POLICY = RetryPolicy()


def history_policy_id(policy: HistoryPolicyName) -> str:
    """Return the stable serialized identifier used in manifests."""
    return policy

