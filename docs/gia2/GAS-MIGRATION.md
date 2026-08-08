# Using GAS with Havoc

Havoc exposes the [GAS](../../packages/gas-protocol/docs/GAS-PROTOCOL.md)
resource and action surface over the game's stateful runtime. Clients read a
current view, choose one advertised command, and submit that command with the
revision and session it belongs to.

## Create a service

Python callers can compose the application runtime with the GAS service:

```python
from havoc_server.runtime import GameRuntime, build_gas_service

runtime = GameRuntime()
gas = build_gas_service(runtime)
session = gas.create_session()
session_id = session.data["id"]
```

The MCP server uses this same application path. See
[`OPERATIONS.md`](../OPERATIONS.md) for stdio and Streamable HTTP startup.

## Read, search, and act

The service provides four operations:

- `get(resource_uri, view?, at_revision?, cursor?, limit?)` reads a resource
  and returns data, navigation links, and commands available in that view.
- `search(resource_type, query?, cursor?, limit?, session_id?)` reads a
  collection and returns matching data plus any commands bound to the result.
- `act(capability_id, expected_revision, input, idempotency_key, session_id=..., scope=?)`
  executes one command that was advertised by a prior read.
- `why_not(resource_uri, command, input?)` explains why a command is not
  currently available without returning an executable command.

For a stateful resource, use a URI such as
`gia://session/<session-id>`. The session ID passed to `search` and `act` is
the execution-scope handle; it is not, by itself, authorization.

A mutation request has this shape:

```json
{
  "capability_id": "cap-…",
  "expected_revision": 3,
  "input": {"template_id": "iryna"},
  "idempotency_key": "request-123",
  "session_id": "gs-…"
}
```

## Revisions and retries

Every response includes `state_revision`, `scope`, and `policy_version`.
Before executing a mutation, Havoc checks that the revision is still current,
that the capability is still advertised for the session, and that the input
matches its schema. A stale revision or unavailable capability is rejected
before domain state changes.

Use a new read to recover from `stale_state` or `stale_view`. Reusing the same
`idempotency_key` for the same request returns the original committed result;
reusing it with different input is a conflict.

Large responses are paginated. When `complete` is `false`, follow
`next_cursor` only with the same resource, query, scope, and session. A state
or policy change invalidates the view and requires fresh discovery.

## Provenance

Committed mutations produce a versioned provenance record containing the
selected capability, request and revision metadata, redacted input/result,
and emitted events. Use `get_session_provenance` or `get_provenance` to read
those records. Explicit caller rationale is stored as untrusted metadata and
does not represent hidden model reasoning.

For the complete protocol contract, error vocabulary, cursor rules, and
backend boundary, see [`GAS-PROTOCOL.md`](../../packages/gas-protocol/docs/GAS-PROTOCOL.md).
For the additional guarantees supplied by GIA, see
[`GIA-THREAT-MODEL.md`](../../packages/gia-core/docs/GIA-THREAT-MODEL.md).
