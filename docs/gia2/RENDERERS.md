# GIA capability renderers

PR10 makes the renderer boundary explicit. The command registry and capability
projection remain GIA concerns; GAS, native MCP tools, and a debug/CLI view are
different presentations of the same contextual `CapabilitySet`.

## Renderer contract

Every renderer receives an already policy-filtered capability set. It may shape
field names, add transport envelopes, or add navigation metadata, but it may
not invent, remove, or authorize a command binding. For a fixed subject, scope,
state revision, and policy version, renderer output must preserve the same
capability IDs.

The `DebugRenderer` is the smallest inspection surface:

```python
from gia.renderers import DebugRenderer

payload = DebugRenderer().render(runtime.capability_set(session_id))
```

Its JSON form is canonical and useful for CLI inspection, fixtures, and
comparing transports without involving MCP.

## Native MCP tools

`NativeMcpRenderer` creates one MCP tool for each command in the supplied
capability set. The generated tool binds the capability ID and scope in its
handler closure, publishes the command's input schema under `input`, and maps
effect metadata to MCP annotations. The handler accepts only the execution
envelope (`input`, `expected_revision`, `idempotency_key`, and `session_id`) and
delegates to a caller-provided invoker such as `GasRuntime.act`.

`NativeMcpRenderer`/`NativeMcpTool` live in `gas_mcp.native` as of PR 17
(`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`) — MCP transport moved out of
`src/gia/` entirely. `gia.renderers.NativeMcpRenderer` (the import below)
is now a thin, silent re-export shim over `gas_mcp.native`, kept so
existing imports don't need to change; new code should prefer importing
from `gas_mcp` directly.

```python
from gia.renderers import NativeMcpRenderer  # or: from gas_mcp import NativeMcpRenderer

renderer = NativeMcpRenderer()
renderer.install(
    context_specific_mcp_server,
    runtime.capability_set(session_id),
    lambda **request: gas.act(**request),
)
```

Native tools are intentionally installed on a context-specific or isolated MCP
server. Installing a session's filtered tools on the shared module-level GAS
server would leave stale tools visible after the session or policy changes.
The reference monitor still revalidates the capability at execution time;
native tool registration is not an authorization grant.

## Completeness and limitations

GAS responses retain `complete` and continuation cursors. Native MCP tool
registration is a snapshot: when state, policy, actor, or scope changes, the
renderer must be run again and the old server/tool registry retired. A native
tool list therefore does not claim to be a permanent or globally complete
action space. Renderers preserve policy semantics, but transport-specific
limits such as MCP tool-name and payload budgets remain explicit.

