# GAS Eval Framework

Compares **GAS** (3 generic tools with affordances) against **traditional tool APIs** across frontier and open-weight LLMs in three stateful business domains: project management, cruise booking, and automotive dealership sales. Historical results compare advisory GAS with 15/30/60-tool APIs. The PR12 controlled factorial additionally separates `gas-advisory`, `gas-enforced`, static native MCP, state-filtered native MCP, and generic `get/search/act` without advertised capabilities; see [PR12-CONTROLLED-EVALUATION.md](PR12-CONTROLLED-EVALUATION.md).

**Core question:** Does constraining an LLM to 3 affordance-driven tools outperform giving it direct access to N domain-specific tools?

**Historical cross-domain result:** Recorded advisory-era GAS runs reached 90–100% task completion for every tested model/domain pair. Traditional APIs could converge on simpler domains, but were less consistent when many similar operations competed in the same catalog. GAS also used fewer tokens when accuracy converged. These descriptive results are not pooled with the new factorial cells.

## Results at a Glance

The historical dataset contains 2,750+ clean, deduplicated runs across 6 models, 3 domains, 4 modes, and 30 tasks per domain.

| Model | PM GAS | Cruise GAS | Auto GAS | Cross-domain average |
|-------|:---:|:---:|:---:|:---:|
| GLM-5 | 93.3% | 96.7% | **100%** | **96.7%** |
| DeepSeek V3.2 | 90.0% | **100%** | 96.7% | **95.6%** |
| Claude Haiku 4.5 | **96.7%** | 93.3% | 96.7% | **95.6%** |
| GPT-4o | 90.0% | **100%** | 96.7% | **95.6%** |
| Qwen3 32B | 90.0% | 93.3% | 96.7% | **93.3%** |
| GPT-5.4 | **96.7%** | — | — | 96.7%* |

*GPT-5.4 has been evaluated on project management only. GLM-5 traditional modes on automotive are pending. See [`results/eval_summary.md`](results/eval_summary.md) for complete tables and caveats.*

## Controlled factorial study (PR12)

Historical `gas` rows are canonicalized to `gas-advisory` and are not pooled
with new cells. New matrices use the same task text, fixtures, command
registry, policy engine, model settings, history policy, retry budget, and
error accounting across these interface conditions:

| Condition | Interface projection | Capability advertisement | Enforcement |
|---|---|---|---|
| `static-native` | 15 native tools | static | domain runtime |
| `state-filtered-native` | 15 native tools | current-state filtered | domain runtime |
| `generic` | `get/search/act` | none | advisory runtime |
| `gas-advisory` | `get/search/act` | affordances | advisory runtime |
| `gas-enforced` | `get/search/act` | affordances | typed reference monitor |

Capture the code/fixture/harness/provider snapshot before collecting runs:

```bash
uv run python -m eval snapshot --output eval/designs/pr12-snapshot.json
```

Run the preregistered conditions with `--conditions`; this takes precedence
over the legacy `--modes` option:

```bash
uv run python -m eval matrix --conditions static-native state-filtered-native generic gas-advisory gas-enforced --models gpt-4o --tiers 1 2 3 4 --runs 3 --experiment-id gia-gas-2.0-pr12-v1
```

Raw transcripts and structured traces are stored with each run. Reports must
separate invalid requests from invalid state transitions, include failed runs,
and report effect sizes/confidence intervals for preregistered comparisons.

## How It Works

### The GAS Approach (3 tools)

Every response includes an `affordances` array — the set of actions valid for the current state. The LLM picks from what's offered rather than guessing from a tool catalog.

```
Tools: get, search, act

Response from `get(resource="issues", id="iss-42")`:
{
  "data": { "id": "iss-42", "title": "Login timeout", "status": "open", ... },
  "affordances": [
    { "action": "transition_issue", "params": { "issue_id": "iss-42", "new_status": "in_progress" }},
    { "action": "assign_issue", "params": { "issue_id": "iss-42", "assignee_id": ["user-dev-1", "user-dev-2"] }},
    { "action": "change_priority", "params": { "issue_id": "iss-42", "new_priority": ["p1", "p3", "p4"] }},
    ...
  ]
}
```

Invalid actions don't appear. Role constraints, state transitions, and business rules are enforced by the server: if a client sends an action that is not a current affordance, the server rejects it before mutation. The model is not physically prevented from emitting an arbitrary payload.

### The Traditional Approach (15/30/60 tools)

Within each domain, the traditional mode uses the same backend, seeded state, tasks, and oracle as GAS. The difference is that the LLM receives all tools upfront with text descriptions of constraints:

```
Tools: create_issue, get_issue, update_issue, close_issue, assign_issue,
       add_comment, search_issues, get_project, create_sprint, activate_sprint,
       close_sprint, add_label, remove_label, link_issues, lock_issue
```

The LLM must infer valid transitions, role permissions, and entity relationships from tool descriptions alone.

### Controlled Comparison

Within a domain, both modes share the same:
- **Domain layer** (`backend/`, `cruise_backend/`, or `auto_backend/`) — Pydantic models, SQLite state, business logic
- **Task definitions** (`tasks/`, `cruise_tasks/`, or `auto_tasks/`) — JSON specs with setup state and oracle checks
- **Agent harness** (`harness/`) — identical agent loop, metrics, and result storage
- **Oracle** — deterministic pass/fail verification against post-conditions

The only variable is how tools are presented to the LLM.

## Architecture

```
eval/
├── backend/             # Project-management domain
├── gas_server/          # Project-management GAS runtime
├── trad_server/         # Project-management traditional runtimes
├── tasks/               # Project-management tasks, seeder, and oracle
├── cruise_backend/      # Cruise inventory, booking, passenger, and payment rules
├── cruise_gas_server/   # Cruise GAS runtime
├── cruise_trad_server/  # Cruise traditional runtimes
├── cruise_tasks/        # Cruise tasks, seeder, and oracle
├── auto_backend/        # Vehicle, test-drive, deal, offer, trade-in, and credit rules
├── auto_gas_server/     # Automotive GAS runtime
├── auto_trad_server/    # Automotive traditional runtimes
├── auto_tasks/          # Automotive tasks, seeder, and oracle
├── harness/           # Eval execution
│   ├── agent.py       #   LLM agent loop (OpenAI + Anthropic SDKs)
│   ├── runner.py      #   Task orchestration
│   ├── providers.py   #   Model catalog (6 models, auto-detection)
│   ├── metrics.py     #   EvalMetrics, TurnDetail
│   └── results_db.py  #   SQLite results persistence
├── analysis/          # Visualization and stats
│   ├── charts.py      #   Matplotlib/seaborn chart generation
│   ├── extract.py     #   Results DB → pandas DataFrame
│   └── stats.py       #   Statistical summaries
├── data/              # Project-management template data
├── cruise_data/       # Cruise and user templates
├── auto_data/         # Vehicle and user templates
├── results/           # Generated artifacts (DB, charts, summaries)
└── cli.py             # Entry point
```

## Task Tiers

Each domain contains 30 tasks across four tiers. Exact counts vary by domain.

| Tier | Category | Example |
|------|----------|---------|
| T1 | CRUD / happy path | Create an issue, hold a booking, register a customer |
| T2 | Multi-step | Run a sprint workflow, confirm a booking, negotiate an offer |
| T3 | Constraints | Exercise role, inventory, price-floor, and lifecycle restrictions |
| T4 | Lifecycle | Complete an end-to-end project, cruise, or dealership workflow |

## Setup

```bash
# From the project root
uv sync --locked --extra test

# API keys (set whichever providers you want to test)
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export DEEPINFRA_API_KEY="..."
```

## Usage

```bash
# Run a single model + mode
uv run python -m eval run --mode gas-advisory --model gpt-4o --tiers 1 3
uv run python -m eval run --mode gas-enforced --model gpt-4o --tiers 1 3
uv run python -m eval run --mode trad-15 --model claude-haiku-4.5 --tiers 1

# Select a domain: pm (default), cruise, or auto
uv run python -m eval run --domain cruise --mode gas-enforced --model gpt-4o --tiers 1 2 3 4
uv run python -m eval run --domain auto --mode trad-30 --model deepseek-v3.2 --tiers 1 2 3 4

# Run a full matrix
uv run python -m eval matrix --models gpt-4o gpt-5.4 claude-haiku-4.5 \
                      --modes gas-advisory gas-enforced trad-15 trad-30 trad-60 \
                      --tiers 1 2 3 4 --runs 1

# Generate outputs
uv run python -m eval summary        # print results table
uv run python -m eval charts         # generate charts to eval/results/charts/

# Inspect
uv run python -m eval list-tasks --domain auto  # show automotive tasks by tier
uv run python -m eval list-models    # show available models (based on API keys)
```

Results persist to `eval/results/eval_results.db` (SQLite). Charts and summaries are regenerated from the DB, so you can accumulate runs over time and re-render.

## Key Findings

The following findings describe the historical advisory-era dataset; PR12 factorial results must be reported separately.

1. **GAS generalized across the recorded domains.** Advisory GAS pass rates were 90–100% across project management, cruise booking, and automotive sales.
2. **Intra-domain similarity matters more than raw tool count.** Automotive trad-30 beats trad-60 by roughly 6.7 percentage points for every fully tested model; adding more closely related operations creates confusion.
3. **Distractors are easier than dense semantics.** In project management, some models handle large catalogs of irrelevant cross-domain tools better than smaller catalogs of similar project operations.
4. **GAS equalizes model capability.** Qwen3 reaches 96.7% with GAS in automotive, compared with 70.0% at trad-60.
5. **GAS remains token-efficient.** Even when traditional accuracy converges, the fixed tool surface generally consumes fewer tokens.

Complete historical results and qualifications are in [`results/eval_summary.md`](results/eval_summary.md). The interactive cross-domain dashboard is [`results/cruise_dashboard.html`](results/cruise_dashboard.html), and the automotive state/affordance graph is [`results/auto_domain_graph.html`](results/auto_domain_graph.html). The preregistered controlled design is documented in [`PR12-CONTROLLED-EVALUATION.md`](PR12-CONTROLLED-EVALUATION.md).

## Extending

**Add a model:** Add a `ModelCatalogEntry` to `harness/providers.py`. Set the corresponding API key env var. Run.

**Add tasks:** Create or update a tier file in the selected domain's `*_tasks/definitions/` directory. Each task defines `setup` (initial state), `oracle` (post-conditions), and `max_turns`; update that domain's seeder and oracle when introducing new entity types or assertions.

**Add tool tiers:** Create a `tools_N.py` in the selected domain's traditional server package and wire it into its `server.py`.

**Add a domain:** Implement a backend, GAS server, traditional server, task package, and template data package following the existing `cruise_*` or `auto_*` layout. Register the domain in `harness/config.py`, `harness/runner.py`, `harness/agent.py`, and `cli.py`.
