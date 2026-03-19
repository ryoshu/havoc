# GAS Eval Framework

Compares **GAS** (3 generic tools with affordances) against **traditional tool APIs** (15/30/60 specialized tools) across frontier and open-weight LLMs on identical project-management tasks.

**Core question:** Does constraining an LLM to 3 affordance-driven tools outperform giving it direct access to N domain-specific tools?

**Answer:** Yes. All 6 models reach 85–97% task completion with GAS (3 tools). With 60 traditional tools, only 3 of 6 match that level — GPT-4o drops to 30%, Qwen3 to 57%. Even when pass rates converge, GAS uses 2–2.4x fewer tokens.

## Results at a Glance

1,092 runs across 6 models, 4 modes, 30 tasks (4 tiers).

| Model | GAS (3 tools) | trad-15 | trad-30 | trad-60 |
|-------|:---:|:---:|:---:|:---:|
| Claude Haiku 4.5 | **96.7%** | 53.3% | 56.7% | 90.0% |
| GPT-5.4 | **95.7%** | 62.2% | 57.8% | 93.3% |
| GPT-4o | **90.0%** | 50.0% | 26.7% | 30.0% |
| DeepSeek V3.2 | **90.0%** | 75.0% | 75.0% | 90.0%† |
| Qwen3 32B | **90.0%** | 40.0% | 33.3% | 56.7% |
| GLM-5 | 85.5% | 63.3% | 65.0% | **91.7%** |

*† DeepSeek trad results exclude T2 (process hung on T2 trad tasks).*

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

Invalid actions don't appear. Role constraints, state transitions, and business rules are enforced by the server — the LLM can't attempt them because they aren't in the response.

### The Traditional Approach (15/30/60 tools)

Same domain, same backend, same tasks. But the LLM receives all tools upfront with text descriptions of constraints:

```
Tools: create_issue, get_issue, update_issue, close_issue, assign_issue,
       add_comment, search_issues, get_project, create_sprint, activate_sprint,
       close_sprint, add_label, remove_label, link_issues, lock_issue
```

The LLM must infer valid transitions, role permissions, and entity relationships from tool descriptions alone.

### Controlled Comparison

Both modes share the same:
- **Domain layer** (`backend/`) — Pydantic models, SQLite state, business logic
- **Task definitions** (`tasks/definitions/`) — JSON specs with setup state and oracle checks
- **Agent harness** (`harness/`) — identical agent loop, metrics, and result storage
- **Oracle** (`tasks/oracle.py`) — pass/fail verification against post-conditions

The only variable is how tools are presented to the LLM.

## Architecture

```
eval/
├── backend/           # Domain layer (project management — not the TTRPG)
│   ├── models.py      #   Pydantic types: Issue, Project, Sprint, User, etc.
│   ├── domain.py      #   ProjectEngine: state transitions, validation, business rules
│   ├── db.py          #   SQLite persistence per eval session
│   └── context.py     #   Unified access layer
├── gas_server/        # GAS runtime (3 tools + affordances)
│   ├── server.py      #   EvalRuntime: get / search / act dispatch
│   └── affordances.py #   compute_affordances() — role-aware, state-dependent
├── trad_server/       # Traditional runtime (15/30/60 tools)
│   ├── server.py      #   TradRuntime: N-tool dispatch
│   ├── tools_15.py    #   15 tool definitions
│   ├── tools_30.py    #   30 tool definitions (15 + decomposed variants)
│   └── tools_60.py    #   60 tool definitions (30 + per-field granularity)
├── tasks/             # Task definitions and verification
│   ├── definitions/   #   JSON task specs (tier 1–4)
│   ├── schema.py      #   TaskDefinition model
│   ├── seeder.py      #   Populates eval scenario state
│   └── oracle.py      #   Post-condition checks (pass/fail)
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
├── data/              # Template data (users, projects, labels)
├── results/           # Generated artifacts (DB, charts, summaries)
└── cli.py             # Entry point
```

## Task Tiers

| Tier | Category | Example | Count |
|------|----------|---------|:---:|
| T1 | CRUD | Create issue, close resolved issue, add comment | 8 |
| T2 | Multi-step | Triage 3 issues, move to sprint and start | 10 |
| T3 | Constraints | Close sprint with P1 blockers, role-restricted ops | 8 |
| T4 | Lifecycle | Full project setup → sprint → resolve → close | 4 |

## Setup

```bash
# From the project root
source .venv/bin/activate
pip install -e .

# API keys (set whichever providers you want to test)
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export DEEPINFRA_API_KEY="..."
```

## Usage

```bash
# Run a single model + mode
python -m eval run --mode gas --model gpt-4o --tiers 1 3
python -m eval run --mode trad-15 --model claude-haiku-4.5 --tiers 1

# Run a full matrix
python -m eval matrix --models gpt-4o gpt-5.4 claude-haiku-4.5 \
                      --modes gas trad-15 trad-30 trad-60 \
                      --tiers 1 2 3 4 --runs 1

# Generate outputs
python -m eval summary        # print results table
python -m eval charts         # generate charts to eval/results/charts/

# Inspect
python -m eval list-tasks     # show all tasks by tier
python -m eval list-models    # show available models (based on API keys)
```

Results persist to `eval/results/eval_results.db` (SQLite). Charts and summaries are regenerated from the DB, so you can accumulate runs over time and re-render.

## Key Findings

1. **GAS eliminates the model-capability tax on tool navigation.** All 6 models reach 85–97% with 3 tools. With 60 tools, only 3 of 6 match that level.
2. **The "confused middle" at 15–30 tools.** Most models dip at 15–30 tools where names are polymorphic (`update_issue` covers too many operations). At 60, granular names (`set_issue_priority`) partially recover some models — but not all.
3. **Even when pass rates converge, GAS uses fewer tokens.** DeepSeek ties at 90% but GAS costs 28K tokens vs trad-60's 69K (0.42x). Claude Haiku uses 0.61x.
4. **Convergence is model-dependent.** GPT-5.4, DeepSeek, and GLM-5 can brute-force 60 tools. GPT-4o and Qwen3 cannot. GAS equalizes them.

## Extending

**Add a model:** Add a `ModelCatalogEntry` to `harness/providers.py`. Set the corresponding API key env var. Run.

**Add tasks:** Create a JSON file in `tasks/definitions/` following the existing schema — `setup` (initial state), `oracle` (post-conditions), `max_turns`. The seeder and oracle handle the rest.

**Add tool tiers:** Create a `tools_N.py` in `trad_server/` and wire it into `trad_server/server.py`.
