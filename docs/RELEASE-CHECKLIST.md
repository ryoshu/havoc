# Release checklist

Run this before cutting a release that touches `gia-core`, `gas-protocol`,
`gia-gas-adapter`, `gas-mcp`, `havoc-domain`, `havoc-server`, or any of the
five specifications in `docs/specs/`. Each item names the command or check
that answers it — this is a gate list, not a narrative.

## Code and import boundaries

- [ ] `uv run python scripts/check_import_boundaries.py` passes — no
  forbidden dependency edge (`docs/gia2/DEPENDENCY-BOUNDARIES.md`'s
  target-state table).
- [ ] `uv run pytest tests/ -q --ignore=tests/test_e2e_ollama.py
  --ignore=tests/test_e2e_ollama_stateless.py` is green, modulo already-
  documented pre-existing flakes (currently two ThreadPoolExecutor-based
  concurrency tests, both racing the same class of revision-claim check
  from different callers:
  `test_application_boundary.py::test_concurrent_execute_shares_one_revision_through_boundary`
  and
  `test_runtime_contract.py::test_concurrent_actions_share_one_revision`).
- [ ] `uv run pytest tests/test_gas_conformance.py -v` is green (or skips
  only for the documented idempotency gap, `docs/specs/
  GAS-COMPATIBILITY.md` §2) across all five backends.
- [ ] A clean-venv wheel install (`uv build --wheel` + install into a
  fresh venv) imports the `havoc` application (`havoc_server`,
  `havoc_domain`, `playthrough`, `agent`, `demo`) and the four reusable
  workspace distributions correctly; the reusable cores and
  `havoc_server.runtime` import without the `mcp` extra installed.

## Specification consistency

- [ ] Every specification in `docs/specs/` whose described code changed
  in this release has its `## Version history` section updated (a new
  entry, or a bump per §"Versioning rule" below) — a spec's `Contract
  version` header must never silently drift from its own version-history
  table.
- [ ] `docs/specs/GIA-GAS-INTEGRATION.md` and `docs/specs/
  GAS-COMPATIBILITY.md`'s `Depends on` lines still name the correct
  versions of the specifications they build on.
- [ ] Repository-wide search for "GIA/GAS" outside
  `docs/specs/GIA-GAS-INTEGRATION.md`, ADR-0013, and files narrating past
  states (execution plan, other ADRs) finds no new use of it as a
  stand-in for either specification's own guarantees (ADR-0013,
  `docs/specs/MIGRATION-GUIDE.md` §2).

## Unsupported-claim audit

Search `docs/`, `README*`, and any release notes for each of the
following, and correct or attribute-to-evidence (`docs/specs/
GIA-THREAT-MODEL.md`) every hit that is not already inside `docs/specs/`
itself stating the boundary explicitly:

- [ ] Capability possession implying authorization (`docs/specs/
  GIA-THREAT-MODEL.md` §5 — this is a GAS-does-not-guarantee item).
- [ ] GAS guaranteeing safety (same section).
- [ ] GIA guaranteeing task success or that an actor chose usefully
  (`docs/specs/GIA-THREAT-MODEL.md` §3).
- [ ] "Three tools" or a specific tool count stated as the architecture
  rather than as one renderer's interface choice (ADR-0010,
  `docs/specs/GAS-PROTOCOL.md` §1).
- [ ] Any claim of runtime version negotiation that does not exist yet
  (`docs/specs/GAS-COMPATIBILITY.md` §4).
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
specification's contract version (`docs/specs/GAS-COMPATIBILITY.md` §4) —
do not conflate the two in release notes.

## Sign-off

- [ ] Every checked item above has a name attached (who verified it), not
  just a checked box — this list is itself provenance for the release,
  not a formality.
