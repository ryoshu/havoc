# GAS 2.0 migration guide

PR7 makes GAS a renderer over the GIA capability set. A read returns separate
`links` and executable `commands`, together with `subject`, `scope`,
`state_revision`, and `policy_version` metadata. A mutation names only the
advertised capability:

```json
{
  "capability_id": "cap-…",
  "expected_revision": 3,
  "input": {"template_id": "iryna"},
  "idempotency_key": "request-123",
  "session_id": "gs-…"
}
```

The local runtime exposes the operations as:

- `get(resource_uri, view?, at_revision?)`
- `search(resource_type, query?, cursor?, limit?)`
- `act(capability_id, expected_revision, input, idempotency_key)`

Stateful `get` calls use a URI such as `gia://session/gs-…`. The local MCP
transport also accepts `session_id` on `search` and `act` as the explicit
execution-scope handle required by the session model. It is not an
authorization input; the server-derived actor, tenant, scope, current policy,
and capability ID are still revalidated by the reference monitor.

## Legacy callers

`JsonGameRuntimeAdapter` is the explicit `gas-legacy` boundary for callers that
still need JSON strings, action names, and `affordances`. Its methods emit a
`DeprecationWarning` and are intentionally not registered as MCP tools. Use
`GasRuntime` for new code. The adapter is scheduled for deletion in PR13 after
a repository-wide usage search confirms that first-party Director,
playthrough, and evaluation callers have migrated.

The adapter and GAS 2.0 delegate to the same `GameRuntime`, command registry,
policy provider, and execution service. It cannot add an action or bypass the
capability revalidation path.
