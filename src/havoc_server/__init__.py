"""Placeholder namespace for the Havoc application composition root.

Empty on purpose: PR 13 (`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`)
establishes this namespace without moving implementations. It will hold
configuration and selected transports, wiring `havoc_domain`, `gia_core`,
`gia_gas_adapter`, and `gas_mcp` together, replacing `src/gia/server.py`
as the composition root in PR 17 and PR 19.
"""
