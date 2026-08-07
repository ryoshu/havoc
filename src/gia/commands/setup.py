"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/commands/setup.py``.

Moved to ``havoc_domain.commands.setup`` in PR 18 (concrete Havoc command
definitions). Kept here so existing imports
(``from gia.commands.setup import ...``) keep working; PR 19 migrates
callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.commands.setup import SelectCharacterCommand, ViewCharacterTemplateCommand, StartMissionCommand

__all__ = ['SelectCharacterCommand', 'ViewCharacterTemplateCommand', 'StartMissionCommand']
