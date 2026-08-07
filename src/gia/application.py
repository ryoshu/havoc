"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/application.py``.

``HavocGiaApplication`` moved to ``havoc_domain`` in PR 18. Kept here so
existing imports (``from gia.application import HavocGiaApplication``) keep
working; PR 19 migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.application import HavocGiaApplication

__all__ = ["HavocGiaApplication"]
