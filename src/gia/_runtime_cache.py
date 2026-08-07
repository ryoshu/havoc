"""Process-wide cache slot for the module-level runtime singleton.

`gia.server` and `src.gia.server` are distinct module objects in this
repository's import setup (repo root and the editable install both put
`gia` on `sys.path` — one bare, one under the `src.` namespace prefix
tests use; confirmed directly: `gia.server.GameRuntime is
src.gia.server.GameRuntime` is `False`). Constructing the module-level
runtime singleton directly inside `server.py` therefore silently splits
state between whichever copy a given caller happened to import through —
a session created via `src.gia.server.create_session()` would not be
visible to `src.gia.server.mcp` (re-exported from `havoc_server`, which
bare-imports `gia.server`), surfacing as `resource_not_found` (PR 17
review finding).

This module holds no logic of its own and imports nothing from `.server`,
so it carries no import-order-dependent circularity. It is always
imported *absolutely* (`import gia._runtime_cache`), never with an `src.`
prefix, so it is loaded into `sys.modules` exactly once regardless of
which copy of `server.py` reaches it first: whichever copy of
`GameRuntime`/`server.py` executes first populates the attributes below,
and every other copy just reads them back, so `_default` (and everything
built over it) is the same object no matter which import path a caller
used to reach it.
"""

from __future__ import annotations
