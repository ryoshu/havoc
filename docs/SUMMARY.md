# GIA: Grounded Interaction Architecture

> **This document describes the current (1.x) implementation.** GIA/GAS 2.0
> is in progress — see `docs/GIA-GAS-2.0-IMPLEMENTATION-PLAN.md` for the
> target architecture and `docs/adr/` for the architectural decisions being
> held constant across that migration. Some claims below (e.g. "3 tools"
> as the architecture rather than one interface choice, and the reasoning
> traces described as causal) are narrowed or reframed by that plan. This
> file stays as-is until the 2.0 cutover (PR 13) rewrites it; it is not
> being kept in sync with the migration in the meantime.

## The Problem

LLM agents operating in stateful domains — workflows, games, business processes — face a fundamental grounding problem. The standard approach gives the model a bag of tools, a system prompt with rules, and hopes it picks the right one. Invariants are enforced by instruction ("don't call X until Y is done"). This fails gracefully: the LLM tries anyway, the system catches it sometimes, and audit trails are unreliable.

The deeper issue is that prompt-enforced constraints are probabilistic in a domain that requires deterministic guarantees. You can't instruct your way to correctness when the consumer is a language model.

## The Architecture

GIA separates three concerns that are typically collapsed into a single prompt:

```
Ontology (Domain + Logic)     — what types exist, what relationships are valid
Knowledge Graph (Memory)      — facts about the world, queryable via SPARQL
Affordances (State)           — what actions are valid right now, computed per turn
```

Each layer has a different lifecycle, a different owner, and a different rate of change:

| Layer | Changes when | Owner | Storage |
|-------|-------------|-------|---------|
| Ontology | Domain changes (new regulation, new product) | Domain expert | TTL/OWL |
| Knowledge Graph | Facts change (new entity, updated record) | Data pipeline | Oxigraph (SPARQL) |
| Affordances | Every turn — recomputed from the other two | Runtime engine | Ephemeral (never stored) |

The LLM touches none of them directly. It consumes the affordance projection and acts within it.

## How It Works

### Three Generic Tools

Instead of N domain-specific tools (one per action), the system exposes three:

- **`get`** — retrieve a resource by type and ID
- **`search`** — browse/filter resources
- **`act`** — execute an action from the affordance set

Every response includes an `affordances` array listing exactly what the consumer can do next, with parameter schemas. The action space is contextual: during setup, the only actions are character selection and mission start. During combat, the only actions are engage, roll, allocate. If a client sends `allocate_dice` during setup anyway, the server rejects it because it is not a current capability.

This is HATEOAS (Hypermedia as the Engine of Application State) applied to LLM tool use. The server is the authority on what's possible. The client is a consumer of that authority.

### Why This Matters More for LLMs Than for Programs

HATEOAS was designed for REST APIs consumed by deterministic programs. The constraint benefit for programs is modest — a well-written client already knows the valid transitions. For a probabilistic consumer like a language model, the benefit is orders of magnitude higher:

- A program that calls the wrong endpoint gets a 404. It was a bug in the code.
- An LLM that calls the wrong tool was *reasoning correctly from its context* — it just had too many options and picked wrong.

Narrowing the action space per turn doesn't just prevent errors. It makes the LLM's job tractable. Instead of choosing from 50 tools and reasoning about validity, it picks from 3-5 affordances that the server currently advertises and will validate. The LLM's decision quality improves because its decision complexity dropped.

### Invariant Enforcement

The key distinction: **prompt-enforced constraints are advisory** (the LLM may try an invalid action). **Affordance-enforced constraints are authoritative** (the server rejects actions that are not current capabilities).

The error surface shrinks from "any tool called in the wrong order with bad parameters" to "a valid action called with bad parameter values within a valid schema." The server enforces sequencing, phase transitions, access control, and revision checks at the mutation boundary — not as instructions the LLM might ignore. A model can still emit malformed text; the guarantee is rejection before domain mutation.

## Reasoning Traces

Every decision is recorded with:

- **Who** — the actor (character, agent, system)
- **What** — the action taken and its parameters
- **When** — timestamp
- **What was available** — the full affordance snapshot at decision time
- **What was not taken** — the actions the actor chose *not* to do
- **What happened** — result summary and domain events triggered
- **State transition** — phase before and after

This creates causal traces, not just logs. The difference: a log says "the agent called heal." A reasoning trace says "the agent called heal when attack, retreat, and advance were also valid, during the between_scenes phase, which transitioned to exploration, and triggered an InjuryHealed event."

Because decisions are loaded into the knowledge graph, they're queryable via SPARQL:

```sparql
# What decisions caused character deaths?
SELECT ?actor ?action ?result ?ts WHERE {
    ?id etr:rdf_type etr:Decision .
    ?id etr:actorName ?actor .
    ?id etr:actionTaken ?action .
    ?id etr:resultSummary ?result .
    ?id etr:timestamp ?ts .
    ?id etr:triggeredEvent ?ev .
    ?ev etr:eventType "CharacterDead" .
} ORDER BY ?ts

# What did the agent choose NOT to do before each injury?
SELECT ?actor ?action ?alternative ?ts WHERE {
    ?id etr:rdf_type etr:Decision .
    ?id etr:actorName ?actor .
    ?id etr:actionTaken ?action .
    ?id etr:actionNotTaken ?alternative .
    ?id etr:timestamp ?ts .
    ?id etr:triggeredEvent ?ev .
    ?ev etr:eventType "InjuryMarked" .
} ORDER BY ?ts
```

This is what vector stores cannot provide. Similarity search finds *related* content. Graph queries find *causal* relationships — what led to what, what was available but rejected, how state evolved through decisions.

## The Playthrough System

The architecture is validated through EAT THE REICH, a TTRPG where vampire commandos parachute into occupied Paris to assassinate Hitler. The game has phased workflows, resource management, combat mechanics, and character progression — a compact analog for business process automation.

### Director + Narrator

The system separates mechanics from narration:

- **Director** — a deterministic Python state machine that plays the game. Reads affordances, picks optimal actions, allocates resources. No LLM. Completes a full game in <0.1 seconds.
- **Narrator** — an LLM that generates prose at narrative beats. Receives graph-enriched context (character personalities, location descriptions, combat events) and produces fiction. Supports stateless (independent per beat, constant token cost) and stateful (accumulates prior narration for continuity, growing context) modes.

The Director proved that the affordance-driven loop works without any LLM involvement. The Narrator proved that LLM capabilities can be applied precisely where they add value (creative prose) without touching the domain logic.

### Benchmark Results

Comparing LLM-driven gameplay (stateful vs stateless) against the Director:

| Approach | Turns | Time | Tokens | Decision Quality |
|----------|-------|------|--------|-----------------|
| LLM Stateful | 15 | 317s | 55,140 | Wanders, needs nudging |
| LLM Stateless | 13 | 67s | 9,423 | Follows directives |
| Director (no LLM) | 55 decisions | <0.1s | 0 | Optimal within strategy |

The Director is 3,000x faster and makes zero invalid calls. The LLM adds value only at decision boundaries (which threat to engage, how to allocate resources) and in narration — not in sequencing or rule enforcement.

## Generalizing Beyond Games

The pattern maps directly to any domain with phased workflows and enforced invariants:

| Game Concept | Business Analog |
|-------------|----------------|
| Game phase (setup, combat, between_scenes) | Workflow state (intake, review, approval, execution) |
| Affordances per phase | Valid actions per state + role |
| Knowledge graph (characters, enemies, locations) | Domain entities (customers, products, policies) |
| SQLite (session state, character injuries) | Working memory (current case, pending approvals) |
| Director (picks optimal action) | Planner agent |
| Narrator (explains what happened) | Communicator agent |
| Decision records with affordance snapshots | Audit trail with reasoning traces |

The three-layer separation (ontology / knowledge graph / affordances) means:
- **Ontology** can be updated when regulations change without touching the runtime
- **Knowledge graph** can be populated from any data source without touching the logic
- **Affordances** are always consistent because they're computed, not configured

## Components

```
src/gia/
    models.py          — Domain types (Pydantic): phases, characters, scenes, decisions
    domain.py          — Havoc Engine: dice mechanics, combat resolution, injuries
    affordances.py     — compute_affordances(ctx, session_id) — the core projection
    context.py         — Composes SQLite (state) + Oxigraph (knowledge)
    graph.py           — SPARQL queries over the knowledge graph
    db.py              — SQLite persistence: sessions, characters, scenes, decisions
    server.py          — GameRuntime class + MCP tool interface (get/search/act)

playthrough/
    director.py        — Deterministic game-playing state machine
    narrator.py        — LLM prose generation (stateful/stateless)
    context_builder.py — Graph queries → focused narrative context
    transcript.py      — Markdown + JSON output
    runner.py          — CLI entry point

ontology/
    etr.ttl            — OWL/Turtle ontology for the game domain

data/
    characters.json    — Character templates (stats, abilities, equipment, hooks)
    enemies.json       — Enemy templates (threat ratings, special rules)
    locations.json     — Location templates (objectives, connections, loot)
```

## Running

```bash
# Mechanical playthrough (no LLM, instant)
uv run python -m src.playthrough.runner --characters iryna chuck --no-narrate

# Narrated playthrough (stateless narrator)
uv run python -m src.playthrough.runner --characters iryna chuck

# Narrated playthrough (stateful narrator — continuity between beats)
uv run python -m src.playthrough.runner --characters iryna chuck --stateful

# MCP server (stdio; Streamable HTTP is documented in docs/OPERATIONS.md)
uv run python -m src.gia.server

# MCP Inspector
uv run mcp dev src/gia/server.py
```

## The Core Insight

A probabilistic consumer (LLM) benefits more from constrained action spaces than a deterministic one (program). HATEOAS was invented for REST clients that already know the rules. Applied to LLM agents that don't reliably know the rules, the same pattern transforms from a nice-to-have into a correctness guarantee.

The affordance layer is the API surface.
