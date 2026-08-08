# Release checklist

> Maintainers only. This is a release gate for the Havoc workspace and its
> pinned package repositories; it is not required for using the application.

**Owner:** `havoc` application integration

Run this before cutting a release that touches `gia-core`, `gas-protocol`,
`gia-gas-adapter`, `gas-mcp`, `havoc-domain`, `havoc-server`, or any of the
five specifications under `packages/*/docs/`. The specifications are
`packages/gia-core/docs/GIA-ARCHITECTURE.md`,
`packages/gas-protocol/docs/GAS-PROTOCOL.md`,
`packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md`,
`packages/gia-core/docs/GIA-THREAT-MODEL.md`, and
`packages/gas-protocol/docs/GAS-COMPATIBILITY.md`. Each item names the
command or check that answers it — this is a gate list, not a narrative.

## Workspace dependencies

- [ ] `git submodule status` reports the four pinned package repositories and
  `git submodule update --init --recursive` succeeds from a clean checkout.
- [ ] Any package submodule pointer changed intentionally and points to a
  published commit on the corresponding package repository.
- [ ] `uv sync --locked --extra test` succeeds with the checked-out submodules;
  update `uv.lock` when the resolved dependency graph changes.

## Code and import boundaries

- [ ] `uv run python scripts/check_import_boundaries.py` passes — no
  forbidden dependency edge in the checker’s target-state table.
- [ ] `uv run python scripts/check_release_boundaries.py` passes — every
  released cross-repository dependency has a declared owner, `0.2.x`
  compatibility range, and CI gate.
- [ ] `uv run pytest tests/ -q --ignore=tests/test_e2e_ollama.py
  --ignore=tests/test_e2e_ollama_stateless.py` is green.
- [ ] `uv run pytest tests/test_gas_conformance.py -v` is green (or skips
  only for the documented idempotency gap,
  `packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §2) across all five
  backends.
- [ ] Downstream conformance cases use the published
  `gas_protocol.conformance.GasConformanceHarness`; eval adapters remain
  Havoc-owned and are not imported by `gas_protocol`.
- [ ] A clean-venv wheel install (`uv build --wheel` + install into a
  fresh venv) imports the `havoc` application (`havoc_server`,
  `havoc_domain`, `playthrough`, `agent`, `demo`) and the four reusable
  workspace distributions correctly; the reusable cores and
  `havoc_server.runtime` import without the `mcp` extra installed.

## Specification consistency

- [ ] Every specification under `packages/*/docs/` whose described code changed
  in this release has its `## Version history` section updated (a new
  entry, or a bump per §"Versioning rule" below) — a spec's `Contract
  version` header must never silently drift from its own version-history
  table.
- [ ] `packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md` and
  `packages/gas-protocol/docs/GAS-COMPATIBILITY.md`'s `Depends on` lines
  still name the correct versions of the specifications they build on.
- [ ] Repository-wide search for "GIA/GAS" outside
  `packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md`, ADR-0013, and files narrating past
  states (execution plan, other ADRs) finds no new use of it as a
  stand-in for either specification's own guarantees (ADR-0013,
  `docs/gia2/GAS-MIGRATION.md`).

## Unsupported-claim audit

Search `docs/`, `README*`, and any release notes for each of the
following, and correct or attribute-to-evidence
(`packages/gia-core/docs/GIA-THREAT-MODEL.md`) every hit that is not
already inside the specification itself stating the boundary explicitly:

- [ ] Capability possession implying authorization
  (`packages/gia-core/docs/GIA-THREAT-MODEL.md` §5 — this is a
  GAS-does-not-guarantee item).
- [ ] GAS guaranteeing safety (same section).
- [ ] GIA guaranteeing task success or that an actor chose usefully
  (`packages/gia-core/docs/GIA-THREAT-MODEL.md` §3).
- [ ] "Three tools" or a specific tool count stated as the architecture
  rather than as one renderer's interface choice (ADR-0010,
  `packages/gas-protocol/docs/GAS-PROTOCOL.md` §1).
- [ ] Any claim of runtime version negotiation that does not exist yet
  (`packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §4).
- [ ] Any `eval/` result described without its mode (advisory / GIA-
  enforced / state-filtered native MCP / static native MCP) — the
  execution plan requires these four to stay distinguishable, never
  pooled into one undifferentiated "GAS" number.

## Versioning rule

Bump a specification's `Contract version` (semver) when:

- **Major** — a change that breaks an existing conformant implementation
  (e.g. a new required `GasBackend` method, a changed error-precedence
  rule).
- **Minor** — a new, backward-compatible capability (e.g. a new optional
  field, a new documented conformance case).
- **Patch** — a clarification, correction, or restated-without-behavior-
  change edit.

The single package version (`pyproject.toml`, currently `0.2.0`) tracks
this repository's own release cadence and is independent of every
specification's contract version
(`packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §4) —
do not conflate the two in release notes.

## Sign-off

- [ ] Every checked item above has a name attached (who verified it), not
  just a checked box — this list is itself provenance for the release,
  not a formality.
