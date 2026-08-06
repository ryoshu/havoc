# PR12 controlled factorial evaluation

The historical `gas` rows are retained under the canonical label
`gas-advisory`. New runs use the five conditions in
[`designs/pr12_factorial.json`](designs/pr12_factorial.json):

| Condition | Interface | State filtering | Boundary |
| --- | --- | --- | --- |
| `static-native` | 15 native tools | none | domain runtime |
| `state-filtered-native` | 15 native tools | current-state projection | domain runtime |
| `generic` | `get/search/act` | no advertised capabilities | advisory runtime |
| `gas-advisory` | `get/search/act` | affordances | advisory runtime |
| `gas-enforced` | `get/search/act` | affordances | typed reference monitor |

The same task JSON, command registry, policy engine, model settings, history
policy, retry budget, and error accounting are used for every cell. The
condition changes only the interface projection and the enforcement boundary.
`EvalMetrics` and the results database retain the condition, experiment ID,
seed, structured turn trace, and raw transcript.

Capture a reproducibility snapshot before collecting a matrix:

```bash
uv run python -m eval snapshot --output eval/designs/pr12-snapshot.json
```

Run a preregistered matrix (API-backed runs are intentionally not part of the
offline test suite):

```bash
uv run python -m eval matrix \
  --conditions static-native state-filtered-native generic gas-advisory gas-enforced \
  --models gpt-4o --tiers 1 2 3 4 --runs 3 \
  --experiment-id gia-gas-2.0-pr12-v1 --batch pr12-v1
```

The historical result tables in `eval/README.md` remain descriptive only;
they are not pooled with the new factorial cells.
