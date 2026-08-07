"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/db.py``.

``GameDB`` moved to ``havoc_domain`` in PR 18 (concrete Havoc persistence).
Kept here so existing imports (``from gia.db import GameDB``) keep working;
PR 19 migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.db import SCHEMA, GameDB

__all__ = ["SCHEMA", "GameDB"]
