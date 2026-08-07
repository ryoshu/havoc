"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/engine.py``.

The domain-neutral error hierarchy that used to live in this module moved
to ``gia_core.errors`` (PR 14 of the GIA/GAS 2.0 plan); ``HavocEngine``
moved to ``havoc_domain.engine`` (PR 18). Both are re-exported here so
every existing ``from .domain import DomainError, HavocEngine, ...`` import
keeps working unchanged; PR 19 migrates callers to import from the real
homes directly.
"""

from __future__ import annotations

from gia_core.errors import (
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
from havoc_domain.engine import HavocEngine

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
