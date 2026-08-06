# GIA Operations

## Clean checkout setup

From the repository root, install the locked runtime and test dependencies:

```bash
uv sync --locked --extra test
```

The project targets Python 3.11 or newer and pins MCP Python SDK v2 through
`mcp[cli]>=2.0,<3` in `pyproject.toml` and `uv.lock`.

## Database path

The game runtime accepts a SQLite path through `GameRuntime(db_path=...)`.
The playthrough CLI exposes the same setting as `--db`; use `:memory:` for
ephemeral tests and a file path when a session must survive a process restart.

Every stateful request carries its session handle, while the SQLite database
stores sessions, decisions, completed rolls, and pending roll state. Pending
rolls are therefore recoverable between the roll and allocation requests.

## SQLite deployment boundary

GIA uses SQLite with a process-local connection and serialized transactions.
This is appropriate for a local server or a single worker. A multi-worker
deployment should provide one database connection per worker and coordinate
access through SQLite's locking, or migrate the persistence layer to a shared
transactional database before scaling horizontally.

## MCP transports

The default server entry point uses stdio:

```bash
uv run python -m src.gia.server
```

For a stateless Streamable HTTP endpoint, set `MCP_TRANSPORT=streamable-http`.
`MCP_HOST`, `MCP_PORT`, and `MCP_ALLOWED_HOSTS` control binding and host
validation; the default endpoint is `http://127.0.0.1:8000/mcp`.

```bash
MCP_TRANSPORT=streamable-http \
MCP_HOST=127.0.0.1 \
MCP_PORT=8000 \
MCP_ALLOWED_HOSTS=127.0.0.1,localhost \
uv run python -m src.gia.server
```

To launch the MCP Inspector against the module entry point:

```bash
uv run mcp dev src/gia/server.py
```

`mcp dev` starts the server with the Inspector. The installed SDK does not
provide a separate `mcp inspect` subcommand.

## What affordance enforcement guarantees

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

## State, resources, and compatibility

Session state and affordances are mutable and belong on MCP tools. Immutable
domain knowledge is exposed as read-only MCP resources (`gia://rules`,
`gia://characters`, `gia://enemies`, `gia://locations`, and
`gia://ontology`). Every stateful call must carry the session handle returned
by `create_session`.

| Client/runtime | Protocol | Transport | Status |
|---|---|---|---|
| MCP Python SDK v2 (`MCPServer`) | `2026-07-28` | stdio | Supported and tested |
| MCP Python SDK v2 (`MCPServer`) | `2026-07-28` | Streamable HTTP `/mcp` | Supported and smoke-tested |
| MCP Inspector via `mcp dev` | SDK-negotiated | local child process | Supported for development |
| Legacy JSON Python wrappers | Not an MCP wire protocol | In-process | Compatibility adapter for playthrough/evals |
| MCP SDK v1 clients | Older protocol/API | Any | Not a supported project dependency |

## Local versus shared deployment

The default SQLite database is suitable for a local process or single worker.
For a multi-worker production deployment, give each worker its own connection
and coordinate through SQLite locking, or move session and evaluation results
to a shared transactional database before scaling horizontally. Immutable
resources may be cached independently; session revisions and mutation
transactions must remain on the authoritative state store.
