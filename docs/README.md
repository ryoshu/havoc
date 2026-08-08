# Havoc documentation

Use the documents below by audience. The reusable GIA and GAS contracts live
in the package repositories under `packages/*/docs/`; the documents here
explain how those contracts are used by the Havoc application.

## Users and operators

- [`OPERATIONS.md`](OPERATIONS.md) — installation, MCP transports, database
  paths, and deployment boundaries.
- [`gia2/GAS-MIGRATION.md`](gia2/GAS-MIGRATION.md) — the current GAS request
  shape and how a client reads, searches, and executes capabilities.
- [`gia2/RENDERERS.md`](gia2/RENDERERS.md) — GAS, native MCP, and debug/CLI
  presentations of the same capability set.

## Maintainers and internal material

- [`RELEASE-CHECKLIST.md`](RELEASE-CHECKLIST.md) — release gates for the
  application and its pinned package repositories. This is a maintainer
  document, not an application setup guide.
- [`gia2/command-matrix.json`](gia2/command-matrix.json) — an internal test
  fixture used to characterize command coverage; it is not a public API
  contract.
