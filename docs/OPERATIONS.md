# Havoc operations

## Clean checkout setup

Clone the repository with its package submodules:

```bash
git clone --recurse-submodules https://github.com/ryoshu/havoc.git
cd havoc
```

For an existing checkout, initialize or refresh them from the repository root:

```bash
git submodule update --init --recursive
```

The four repositories under `packages/` are pinned Git submodules and are also
the local `uv` workspace members. They must be checked out before installing
the locked dependencies:

```bash
uv sync --locked --extra test
```

To verify the checked-out package revisions:

```bash
git submodule status
```

The project targets Python 3.11 or newer. MCP Python SDK v2
(`mcp[cli]>=2.0,<3`) is an optional dependency (the `mcp` extra) so the
reusable packages (`gia_core`, `gas_protocol`, and `gia_gas_adapter`) install
and import without it; the `test` extra above pulls it in
transitively (`havoc[mcp]`) because the test suite itself covers MCP
transport. To install just the MCP runtime without test tooling, use
`uv sync --locked --extra mcp`.

## Database path

The game runtime accepts a SQLite path through `GameRuntime(db_path=...)`.
The playthrough CLI exposes the same setting as `--db`; use `:memory:` for
ephemeral tests and a file path when a session must survive a process restart.

Every stateful request carries its session handle, while the SQLite database
stores sessions, decisions, completed rolls, and pending roll state. Pending
rolls are therefore recoverable between the roll and allocation requests.

## Deployment boundary

Havoc uses SQLite with a process-local connection and serialized transactions.
This is appropriate for a local server or a single worker. For multiple
workers, give each worker its own connection and coordinate through SQLite's
locking, or move session state to a shared transactional database before
scaling horizontally.

## MCP transports

The default server entry point uses stdio:

```bash
uv run python -m havoc_server
```

For a stateless Streamable HTTP endpoint, set `MCP_TRANSPORT=streamable-http`.
`MCP_HOST`, `MCP_PORT`, and `MCP_ALLOWED_HOSTS` control binding and host
validation; bare hostnames in `MCP_ALLOWED_HOSTS` are matched on the configured
port, and `:*` may be used to allow every port. The default endpoint is
`http://127.0.0.1:8000/mcp`. Set `GIA_DB_PATH` when the MCP process must retain
sessions across restarts.

```bash
MCP_TRANSPORT=streamable-http \
MCP_HOST=127.0.0.1 \
MCP_PORT=8000 \
MCP_ALLOWED_HOSTS=127.0.0.1,localhost \
GIA_DB_PATH=./gia.db \
uv run python -m havoc_server
```

To launch the MCP Inspector against the module entry point:

```bash
uv run mcp dev src/havoc_server/__main__.py
```

`mcp dev` starts the server with the Inspector. The installed SDK does not
provide a separate `mcp inspect` subcommand.

## Capability enforcement

Affordances are server-computed capabilities, not a promise about the model's
output channel. For every mutation, the server recomputes the current
capabilities, validates the requested action and parameters against the
advertised JSON Schema, requires the caller's current revision, and atomically
claims that revision before dispatching domain code. The server rejects an
unavailable action, invalid parameters, missing session, or stale revision with
a typed error; invalid input does not reach mutation code.

A client can still send any string or JSON payload on the wire. “Enforced”
means those non-current capabilities are rejected at the server boundary, not
that a language model is physically unable to produce malformed text.

See `packages/gia-core/docs/GIA-THREAT-MODEL.md` for the full boundary of what
this guarantee does, and does not, cover.

## State and resources

Session state and affordances are mutable and belong on MCP tools. Immutable
domain knowledge is exposed as read-only MCP resources (`gia://rules`,
`gia://characters`, `gia://enemies`, `gia://locations`, and
`gia://ontology`). Every stateful call must carry the session handle returned
by `create_session`.

The supported MCP runtime is SDK v2 over stdio or Streamable HTTP. The local
Inspector can be started with `mcp dev`; SDK v1 clients are not supported.
Immutable resources may be cached independently, but session revisions and
mutation transactions must remain on the authoritative state store.
