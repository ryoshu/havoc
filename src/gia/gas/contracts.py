"""Typed GAS 2.0 request and response contracts.

The contract keeps navigation links separate from executable commands.  A
``Capability`` is the only value that can authorize a mutation; the command
name and target are intentionally absent from :class:`ActRequest`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..capabilities import Capability, Link
from ..models import DomainEvent


class GetRequest(BaseModel):
    """GAS resource read request."""

    model_config = ConfigDict(extra="forbid")

    resource_uri: str
    view: str | None = None
    at_revision: int | None = None

    @field_validator("resource_uri")
    @classmethod
    def _resource_uri_is_present(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("resource_uri must be a non-empty URI.")
        return value.strip()


class SearchRequest(BaseModel):
    """GAS resource search request.

    ``cursor`` and ``limit`` are part of the public shape now so clients do
    not need another contract migration when bounded discovery lands in PR 8.
    PR 7 keeps the result complete and does not issue cursors yet.
    """

    model_config = ConfigDict(extra="forbid")

    resource_type: str
    query: dict[str, Any] = Field(default_factory=dict)
    cursor: str | None = None
    limit: int | None = None

    @field_validator("resource_type")
    @classmethod
    def _resource_type_is_present(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("resource_type must be a non-empty string.")
        return value.strip()

    @field_validator("limit")
    @classmethod
    def _limit_is_positive(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value <= 0):
            raise ValueError("limit must be a positive integer.")
        return value


class ActRequest(BaseModel):
    """GAS mutation request.

    ``session_id`` is an execution-scope transport field for this local
    runtime.  It is not an authorization input: the server-derived request
    context and the capability's scope still have to agree.
    """

    model_config = ConfigDict(extra="forbid")

    capability_id: str
    expected_revision: int
    input: dict[str, Any]
    idempotency_key: str
    session_id: str = ""

    @field_validator("capability_id", "idempotency_key")
    @classmethod
    def _required_token_is_present(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("value must be a non-empty string.")
        return value.strip()

    @field_validator("expected_revision")
    @classmethod
    def _revision_is_integer(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("expected_revision must be an integer.")
        return value


class GasResourceResponse(BaseModel):
    """GAS read response rendered from a contextual capability set."""

    model_config = ConfigDict(extra="forbid")

    data: Any
    links: list[Link] = Field(default_factory=list)
    commands: list[Capability] = Field(default_factory=list)
    subject: str
    scope: str
    state_revision: int
    policy_version: str
    complete: bool = True
    next_cursor: str | None = None


class GasActionResponse(GasResourceResponse):
    """GAS mutation response with events and the next local command set."""

    events: list[DomainEvent] = Field(default_factory=list)


# Verbose aliases are convenient at transport boundaries while the short
# names mirror the operation names in the GAS contract.
GasGetRequest = GetRequest
GasSearchRequest = SearchRequest
GasActRequest = ActRequest
GetResponse = GasResourceResponse
SearchResponse = GasResourceResponse
ActResponse = GasActionResponse
