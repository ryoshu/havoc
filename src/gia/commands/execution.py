"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/execution.py``.

Moved to ``havoc_domain.execution`` in PR 18 (the concrete execution
service). Kept here so existing imports
(``from gia.commands.execution import execute``) keep working; PR 19
migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.execution import execute

__all__ = ["execute"]
