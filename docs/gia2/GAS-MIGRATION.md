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

- `get(resource_uri, view?, at_revision?, cursor?, limit?)`
- `search(resource_type, query?, cursor?, limit?)`
- `act(capability_id, expected_revision, input, idempotency_key, scope?)`
- `why_not(resource_uri, command, input?)`

Stateful `get` calls use a URI such as `gia://session/gs-…`. The local MCP
transport also accepts `session_id` on `search` and `act` as the explicit
execution-scope handle required by the session model. It is not an
authorization input; the server-derived actor, tenant, scope, current policy,
and capability ID are still revalidated by the reference monitor.

## Building a GAS surface

`JsonGameRuntimeAdapter` (JSON strings, action names, and flattened
`affordances`) and its successor `GasRuntime` (a hand-rolled GAS 2.0
implementation) were both removed in PR 19 ("Migrate callers and remove
compatibility paths", `docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`) once a
repository-wide usage search confirmed every first-party Director,
playthrough, demo, agent, and test caller had migrated off them.

The current, sole path is `havoc_server.runtime.build_gas_service(runtime: GameRuntime)
-> GasService`: it composes a `GiaGasAdapter` over the runtime's application
ports and wraps it in `gas_protocol.service.GasService`. This is the exact
composition the live MCP server (`havoc_server.app`) and the Director
(`playthrough.director`) both build from — there is no separate
"legacy" or "GAS 2.0" adapter to choose between anymore.

```python
from havoc_server.runtime import GameRuntime, build_gas_service

runtime = GameRuntime()
gas = build_gas_service(runtime)
session = gas.create_session()
```

`GasService` delegates to the same `GameRuntime`, command registry, policy
provider, and execution service as any other caller. It cannot add an
action or bypass the capability revalidation path.

## Locality and recovery

Capability responses declare their scope using the canonical form
`tenant:<tenant>/<kind>:<identifier>`. The renderer uses session scopes for a
workflow, collection scopes for search results, and resource scopes for a
target-local view. `workflow`, `collection`, and `resource` scopes are
contextual labels, not alternate authorization systems: `act` still
re-projects the command binding against the authoritative session.

Large command sets are bounded by a deterministic page budget. A response
with `complete=false` carries `next_cursor`; target-heavy pages also expose
non-executable `binding_templates` that point clients toward search followed
by a target-local `get`. Cursors bind the resource, query, scope, state
revision, and policy version. Reusing one after the resource, query, or
scope it was minted against no longer matches the request returns the
typed `invalid_input` error — the cursor was never valid for this request.
Reusing one after only the state revision or policy version has since
advanced returns the typed `stale_view` error; in that case clients should
restart discovery. See `docs/specs/GAS-PROTOCOL.md` §7 for the full rule.

`why_not` is a diagnostic read. It reports structured reasons and prerequisites
for an unavailable command but always returns an empty executable command set;
it cannot be used to bypass capability-ID dispatch or reveal another tenant's
entities.

## Decision provenance

Every committed mutation writes one versioned `DecisionProvenance` record in
the same SQLite transaction as the state revision and domain events. It binds
the request ID, actor, tenant/scope, selected capability, capability-set hash,
durable snapshot reference, redacted input/result, before/after revisions,
policy version, emitted events, outcome, and optional client/model metadata.
The snapshot records capabilities advertised by the server; alternatives are
labelled "advertised but not selected" and do not claim access to hidden model
reasoning. Explicit caller rationale is stored only as `untrusted_rationale`.

Sensitive fields are recursively redacted before SQLite persistence or graph
projection. Idempotent retries return the original result and do not create a
second provenance record. Rejected or failed mutations do not create a
committed provenance record; their typed error is the observable outcome, and
transaction rollback removes any in-flight state, events, revision, and audit
row together. `get_session_provenance` and `get_provenance` are the canonical
read APIs; `get_session_decisions` remains a 1.x compatibility alias.
