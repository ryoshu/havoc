"""Versioned, observable decision-provenance contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROVENANCE_VERSION = "2.0"


def _request_id() -> str:
    return f"req-{uuid4().hex}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionProvenance(BaseModel):
    """Facts needed to reconstruct one committed mutation.

    ``alternatives_not_selected`` means capabilities advertised by the server
    at the request snapshot that were not selected.  It does not claim that a
    model consciously considered or rejected those alternatives.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: str = PROVENANCE_VERSION
    id: str = ""
    request_id: str = Field(default_factory=_request_id)
    session_id: str = ""
    tenant_id: str = "default"
    scope: str = ""
    actor_id: str = ""
    actor_name: str = ""
    capability_id: str | None = None
    capability_set_hash: str = ""
    capability_snapshot_ref: str | None = None
    capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    offered_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    action: str = ""
    # ``input`` is canonical; ``params`` remains an input alias for 1.x data.
    input: dict[str, Any] = Field(default_factory=dict, alias="params")
    result: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)
    alternatives_not_selected: list[str] = Field(default_factory=list)
    state_revision_before: int = 0
    state_revision_after: int = 0
    policy_version: str = "policy-v1"
    phase_before: str = ""
    phase_after: str = ""
    outcome: Literal["committed", "replayed", "rejected", "failed"] = "committed"
    client_metadata: dict[str, Any] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    # Explicitly supplied model text is retained only as untrusted metadata.
    untrusted_rationale: str | None = None
    created_at: str = Field(default_factory=_timestamp)
    committed_at: str | None = None
    # 1.x timestamp spelling; canonical queries use ``created_at`` and
    # ``committed_at`` while the adapter keeps existing consumers working.
    timestamp: str = ""

    # Historical 1.x fields are accepted/read through the adapter but are not
    # used as causal explanations.  They are adapter-only and never projected
    # under the old reasoning predicates.
    affordances_snapshot: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    affordances_not_taken: list[str] = Field(default_factory=list, exclude=True)
    llm_narration: str = Field(default="", exclude=True)
    llm_turn_context: str = Field(default="", exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _adapt_legacy_constructor(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        adapted = dict(data)
        if "state_revision" in adapted:
            revision = adapted["state_revision"]
            adapted.setdefault("state_revision_before", revision)
            adapted.setdefault("state_revision_after", revision)
        if "timestamp" in adapted and "created_at" not in adapted:
            adapted["created_at"] = adapted["timestamp"]
        return adapted

    @field_validator("tenant_id")
    @classmethod
    def _tenant_is_present(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) and value.strip() else "default"

    @model_validator(mode="after")
    def _normalize_legacy_fields(self) -> "DecisionProvenance":
        if not self.timestamp:
            self.timestamp = self.created_at
        if not self.created_at:
            self.created_at = self.timestamp or _timestamp()
        if not self.offered_capabilities and self.affordances_snapshot:
            self.offered_capabilities = list(self.affordances_snapshot)
        if not self.alternatives_not_selected and self.affordances_not_taken:
            self.alternatives_not_selected = list(self.affordances_not_taken)
        if not self.untrusted_rationale and self.llm_narration:
            self.untrusted_rationale = self.llm_narration
        if not self.state_revision_after:
            self.state_revision_after = self.state_revision_before
        return self

    @property
    def params(self) -> dict[str, Any]:
        """1.x compatibility accessor for the canonical redacted input."""
        return self.input

    @property
    def redacted_input(self) -> dict[str, Any]:
        return self.input

    @property
    def state_revision(self) -> int:
        """1.x compatibility accessor (the committed/observed revision)."""
        return self.state_revision_after


# Explicit adapter name retained for existing callers and persisted 1.x rows.
DecisionRecord = DecisionProvenance
