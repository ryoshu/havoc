# GIA Operations

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
