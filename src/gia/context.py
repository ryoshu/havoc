"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/context.py``.

``GameContext`` moved to ``havoc_domain`` in PR 18 (concrete Havoc
composition of SQLite + Oxigraph + template loading). Kept here so existing
imports (``from gia.context import GameContext``) keep working; PR 19
migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.context import DATA_DIR, ONTOLOGY_PATH, PROJECT_ROOT, GameContext

__all__ = ["DATA_DIR", "ONTOLOGY_PATH", "PROJECT_ROOT", "GameContext"]
