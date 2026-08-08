# Migrating to the separated GIA/GAS specifications

**Owner:** `havoc` application integration

**Applies to:** readers and callers oriented around the pre-PR-20
documentation set (including the historical `docs/SUMMARY.md`) or pre-PR-19 code
(`JsonGameRuntimeAdapter`, `GasRuntime`, the `src/gia/*` shims). If you are
starting fresh, read `packages/gia-core/docs/GIA-ARCHITECTURE.md`,
`packages/gas-protocol/docs/GAS-PROTOCOL.md`,
`packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md`, and
`packages/gia-core/docs/GIA-THREAT-MODEL.md` directly and skip this document.

## 1. If you're migrating code

The RS-10 documentation and packaging pass does not change application
runtime behavior.
The code-level migration — replacing `JsonGameRuntimeAdapter`/`GasRuntime`
with `havoc_server.runtime.build_gas_service` — was already completed in PR 19
and the RS-09 application cutover — and
is documented at the call-site level in `docs/gia2/GAS-MIGRATION.md`. If
you still have a caller importing `src.gia.compat`, `src.gia.gas`, or any
of the PR 18 `src/gia/*` re-export shims, those were deleted in PR 19; see
`docs/gia2/GAS-MIGRATION.md`'s "Building a GAS surface" section for the
direct replacement.

## 2. If you're migrating a mental model or a talking point

The pre-PR-20 documents described "GIA" and "GAS" as one undifferentiated
thing, usually named together as "GIA/GAS" or "the architecture." That
framing is retired. Use the table below to find where a claim you
remember now lives, and check it against
`packages/gia-core/docs/GIA-THREAT-MODEL.md` before repeating it — several claims
below were true only in the narrower sense the threat model states.

| Old claim (pre-PR-20) | Now stated in | Notes |
|---|---|---|
| "Three generic tools (`get`/`search`/`act`) replace N domain tools" | `packages/gas-protocol/docs/GAS-PROTOCOL.md` §1 | Reframed per ADR-0010: an interface choice of one renderer, not the architectural claim. A filtered native-tool renderer provides the same enforcement guarantee at a different tool count. |
| "The server rejects invalid actions" | `packages/gia-core/docs/GIA-ARCHITECTURE.md` §4 | This is a GIA guarantee (capability revalidation at execution), not a GAS one — GAS renders and forwards (ADR-0012) and makes no authorization claim on its own (`packages/gia-core/docs/GIA-THREAT-MODEL.md` §5). |
| "Decision provenance, not hidden reasoning" | `packages/gia-core/docs/GIA-ARCHITECTURE.md` §6 | Unchanged in substance; now stated as a GIA responsibility rather than a feature of "the architecture" generically. |
| "GAS Eval: GAS beats traditional tool APIs" | `eval/README.md` and `eval/PR12-CONTROLLED-EVALUATION.md` | This was always, and remains, an evaluation-harness claim about task performance and interface shape, never a GIA or GAS specification claim (ADR-0010, ADR-0011). |
| "GIA/GAS" as a single name for the whole system | `packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md` | Retained only for the integration or shared implementation history (ADR-0013) — never as a stand-in for either specification's own guarantees. Using it to mean "the architecture" generically is exactly the overclaim ADR-0013 exists to prevent. |
| [`docs/SUMMARY.md`](SUMMARY.md)'s 1.x architecture description | `packages/gia-core/docs/GIA-ARCHITECTURE.md` | `docs/SUMMARY.md` predates the PR 13–19 separation and names deleted paths (`src/gia/server.py`'s module-level functions, `src/gia/domain.py`); treat it as a historical record of the 1.x implementation, not current guidance. |

## 3. If you're evaluating whether to adopt GIA, GAS, or both independently

You can adopt GAS (`packages/gas-protocol/docs/GAS-PROTOCOL.md`) without GIA: implement
`GasBackend` directly against your own store, exactly as
`gas_protocol.fake_backend.InMemoryGasBackend` does, and you get the
protocol-level guarantees in `packages/gia-core/docs/GIA-THREAT-MODEL.md` §4 with none
of the GIA-specific ones in §2.

You can adopt GIA (`packages/gia-core/docs/GIA-ARCHITECTURE.md`) without GAS: implement
`ResourceProvider`/`CapabilityAuthority` and drive them from your own
transport or renderer — a debug/CLI view, a different wire protocol,
whatever fits — exactly as `gia_core.approval_workflow` does not require
any transport at all in this repository's own test suite.

Adopting both, via `GiaGasAdapter`
(`packages/gia-gas-adapter/docs/GIA-GAS-INTEGRATION.md`),
gets you the union of both guarantee sets and none beyond it
(`packages/gia-core/docs/GIA-THREAT-MODEL.md` §6).

## 4. What did not change

- The root Python distribution is `havoc`, version `0.2.0`; the reusable
  components are separate workspace distributions pinned as Git submodules —
  see `packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §4 for the
  compatibility/versioning stance.
- `eval/`'s runtime code, response shapes, and DB schema are unchanged —
  RS-10 keeps them Havoc-owned (see `packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §1 for
  what the published conformance harness and app-owned adapters exercise,
  without changing `eval/` itself).
- No new version-negotiation mechanism was added; contract version
  numbers are specification-text versions today, not a runtime-checked
  field (`packages/gas-protocol/docs/GAS-COMPATIBILITY.md` §4).
