# Evaluation framework

This directory measures how language models use different interfaces for
stateful business workflows. It holds the domains, seeded fixtures, task
definitions, servers, agent harness, oracle checks, result database, and chart
generation needed to compare GAS with traditional tool APIs.

## What it compares

Each task runs against the same domain state, task text, business rules, model
settings, retry policy, and deterministic oracle. The interface projection is
the experimental variable:

| Condition | Interface | Capability view | Enforcement |
|---|---|---|---|
| `static-native` | 15 native tools | static | domain runtime |
| `state-filtered-native` | 15 native tools | current-state filtered | domain runtime |
| `generic` | `get`, `search`, `act` | none | advisory runtime |
| `gas-advisory` | `get`, `search`, `act` | advertised affordances | advisory runtime |
| `gas-enforced` | `get`, `search`, `act` | advertised affordances | typed reference monitor |

The historical `gas` mode is accepted as a compatibility alias for
`gas-advisory`; new controlled runs should use the explicit names above.

## Domains and tasks

The suite contains four tiers of tasks in each domain:

- Project management: issues, projects, sprints, roles, labels, and approvals.
- Cruise booking: inventory, passengers, bookings, payments, and embarkation.
- Automotive sales: vehicles, test drives, deals, offers, trade-ins, and credit
  decisions.

Tasks define setup data and post-conditions. The oracle checks the resulting
state rather than trusting the model's response text.

## Run the harness

Install the full Havoc test environment from the repository root, then set the
provider keys for the models you want to run:

```bash
uv sync --locked --extra test
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export DEEPINFRA_API_KEY="..."
```

Capture the reproducibility inputs for a controlled study:

```bash
uv run python -m eval snapshot --output eval/designs/pr12-snapshot.json
```

Run one configuration:

```bash
uv run python -m eval run --domain pm --mode gas-enforced \
  --model gpt-4o --tiers 1 2 3 4
```

Run a matrix:

```bash
uv run python -m eval matrix \
  --conditions static-native state-filtered-native generic gas-advisory gas-enforced \
  --models gpt-4o --tiers 1 2 3 4 --runs 3 \
  --experiment-id gia-gas-pr12
```

Inspect tasks, models, results, and charts with:

```bash
uv run python -m eval list-tasks --domain auto
uv run python -m eval list-models
uv run python -m eval summary
uv run python -m eval charts
```

Runs are stored in a SQLite database under `eval/results/` by default. Raw
transcripts and structured traces remain attached to each run so invalid
requests, state-transition failures, and oracle failures can be reported
separately.

## Layout

| Path | Purpose |
|---|---|
| `backend/`, `cruise_backend/`, `auto_backend/` | Domain state and business rules |
| `*_gas_server/` and `*_trad_server/` | GAS and traditional interface projections |
| `tasks/`, `cruise_tasks/`, `auto_tasks/` | Task definitions, seeders, and oracles |
| `harness/` | Model adapters, runner, metrics, and result persistence |
| `analysis/` | Result extraction, statistics, and charts |

The controlled design and reporting rules are documented in
[`PR12-CONTROLLED-EVALUATION.md`](PR12-CONTROLLED-EVALUATION.md).

## Extending the suite

- Add a model in `harness/providers.py`.
- Add or revise tier definitions in the selected domain's `*_tasks/` package.
- Add a traditional tool count in the selected domain's `*_trad_server/`.
- Add a domain by following the existing backend, server, tasks, seed-data,
  and harness registration pattern.
