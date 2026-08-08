# Havoc

Havoc is the EAT THE REICH application: a stateful, capability-driven
tabletop role-playing game backend and playthrough system. It models vampire
commandos moving through occupied Paris, resolving combat with dice pools,
managing injuries and blood, and progressing through a sequence of scenes.

*Eat the Reich* is published by [Rowan, Rook and Decard](https://rowanrookanddecard.com/);
see the [official game page](https://rowanrookanddecard.com/product/eat-the-reich/).

The application computes the actions available in the current game state and
serves them through a GAS interface. Clients read the current state and
commands, then execute a returned capability with its expected revision. The
runtime rejects unavailable commands, invalid parameters, stale views, and
replayed mutations before changing game state.

## Capabilities

- Stateful sessions with phase-specific actions for setup, exploration,
  engagement, scene transitions, healing, and mission completion.
- Character selection, equipment and blood management, enemy threats,
  objectives, locations, routes, injuries, and rescue/death outcomes.
- Dice-pool construction, rolling, and allocation across objectives, threats,
  defense, feeding, and special effects.
- SQLite persistence for sessions, decisions, rolls, and pending roll state.
- Read-only game knowledge from the rules, character, enemy, location, and RDF
  ontology data files.
- GAS access through `havoc_server.runtime.build_gas_service` and an MCP server
  with the generic `create_session`, `get`, `search`, `act`, and `why_not` tools.
- A native capability renderer, a deterministic Director, an optional LLM
  narrator, an interactive agent CLI, and a cross-domain GAS evaluation
  harness.

## Repository layout

| Path | Purpose |
|---|---|
| `src/havoc_domain/` | Game models, mechanics, commands, persistence, and application boundary |
| `src/havoc_server/` | GAS composition, MCP server, and native capability renderer |
| `src/playthrough/` | Director, context builder, narrator, and transcript output |
| `src/agent/` | Interactive GM/agent CLI |
| `data/` and `ontology/` | Game templates and RDF ontology |
| `eval/` | Controlled GAS versus traditional-tool evaluations |

## Install

Clone Havoc with its reusable package repositories:

```bash
git clone --recurse-submodules https://github.com/ryoshu/havoc.git
cd havoc
```

For an existing checkout, initialize or refresh the pinned package submodules:

```bash
git submodule update --init --recursive
```

The `packages/` entries are Git submodules pinned by this repository. They are
workspace members, so they must be present before dependency resolution.

```bash
uv sync --locked --extra test
```

Install the `mcp` extra when you need the MCP server or MCP tests:

```bash
uv sync --locked --extra mcp
```

Narrated playthroughs and LLM-play mode use an OpenAI-compatible API. Set
`DEEPINFRA_API_KEY` for DeepInfra or point `--api-url` and `--api-key` at a
local Ollama-compatible endpoint. Mechanical runs do not need an API key.

## Run

Run the scripted demo:

```bash
uv run python -m demo.scenario
```

Run a deterministic playthrough without an LLM:

```bash
uv run python -m playthrough.runner --characters iryna chuck --no-narrate
```

Run the interactive agent:

```bash
uv run python -m agent.cli
```

Start the MCP server over stdio:

```bash
uv run python -m havoc_server
```

For Streamable HTTP, see [`docs/OPERATIONS.md`](docs/OPERATIONS.md). The same
document covers database paths, host configuration, and local MCP Inspector
use.

## Development

```bash
uv run pytest -q
```

The evaluation harness has its own usage guide in
[`eval/README.md`](eval/README.md). The complete documentation index, grouped
by audience, is in [`docs/README.md`](docs/README.md).
