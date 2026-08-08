# Capability renderers

Havoc computes one policy-filtered capability set for the current subject,
scope, state revision, and policy version. Renderers present that set through
different client interfaces; they do not invent commands, grant permissions,
or replace execution-time validation.

## GAS

The GAS service presents capabilities through `get`, `search`, `act`, and
`why_not`. It is the default interface for the MCP server and for Python
callers. See [Using GAS with Havoc](GAS-MIGRATION.md) for request examples.

## Debug and CLI output

`DebugRenderer` produces a compact JSON representation of a capability set.
It is useful for local inspection, fixtures, and comparing transports:

```python
from gia_core.renderers import DebugRenderer

payload = DebugRenderer().render(runtime.capability_set(session_id))
```

The JSON output is for inspection. Clients must still execute mutations
through the service that owns the authoritative session.

## Native MCP tools

`NativeMcpRenderer` creates one MCP tool for each command in a supplied
capability set. Each generated tool binds the capability ID and scope, exposes
the command's input schema, and accepts the execution envelope:
`input`, `expected_revision`, `idempotency_key`, and `session_id`.

```python
from havoc_server.native_mcp import NativeMcpRenderer
from havoc_server.runtime import build_gas_service

gas_service = build_gas_service(runtime)
NativeMcpRenderer().install(
    context_specific_mcp_server,
    runtime.capability_set(session_id),
    lambda **request: gas_service.act(**request),
)
```

Install filtered tools on a context-specific or isolated MCP server. A tool
list is a snapshot: when state, policy, actor, or scope changes, rebuild the
renderer and retire the old registry. Registration is not an authorization
grant; the reference monitor revalidates the capability when the tool runs.

## Limits

GAS responses may be paginated with continuation cursors. Native MCP tool
registration is also bounded by transport-specific tool-name and payload
limits. Clients should treat every rendered capability set as contextual and
refresh it after a state or policy change.
