"""E2E test (stateful): LLM keeps full conversation history across turns.

The LLM accumulates all messages — system prompt, tool calls, tool results —
in a growing context window. This gives it full memory of past actions but
costs more tokens per turn as context grows.
"""

from __future__ import annotations

import json
import time

import pytest
from openai import OpenAI

from .e2e_helpers import (
    TOOLS,
    Tracker,
    execute_tool,
    fresh_server,
    llm_call,
    ollama_reachable,
    trim_response,
    write_log,
)

pytestmark = pytest.mark.skipif(
    not ollama_reachable(),
    reason="Ollama not reachable at localhost:11434",
)

MAX_TURNS = 50

PLAYER_SYSTEM_PROMPT = """\
You are a player in EAT THE REICH. You interact with the game through 3 tools: get, search, act.

RULES:
- Every tool response has an "affordances" array — these are your available actions.
- To perform an action, call the `act` tool with the action name and a JSON params string.
- Do NOT call `get` or `search` unless you need specific information. Prefer `act` to make progress.
- params is always a JSON STRING, not an object.

GAME LOOP — repeat this cycle until told to stop:

Phase 1 — SETUP (do once):
1. act: select_character with params {"template_id": "iryna"}
2. act: select_character with params {"template_id": "chuck"}
3. act: start_mission (no params needed)

Phase 2 — COMBAT (repeat until scene_completed is true):
4. act: engage_threat — pick a threat name from the scene data
5. act: build_dice_pool with params {"stat": "brawl"}
6. act: allocate_dice — read player_kept from the roll, distribute ALL dice across categories:
   {"allocations": {"objective": [6, 5], "threat": [4], "defense": [5]}}
   - ALWAYS put at least half your dice toward "objective" — the scene only completes when the
     objective rating reaches 0, so this is your top priority
   - Put remaining dice toward "threat" and "defense"
   - Only 6s can go to "special"
7. Check the allocate_dice response:
   - If "scene_completed": true → scene is done, move to Phase 3
   - Otherwise → go back to step 4 (engage another threat or the same one)
   - You may switch characters with act: next_turn before re-engaging

Phase 3 — ADVANCE (after scene completes):
8. The affordances will offer choose_next_location. Pick one and call it.
9. Then go back to Phase 2 for the new location.

After completing Phase 3 for one location, say "Done" and stop.

IMPORTANT:
- After allocate_dice, ALWAYS check if scene_completed is true or false before deciding next step.
- Do not explore unnecessarily. Execute actions from affordances directly.
- When switching characters, the affordance for next_turn provides character_id values to use.\
"""


def _nudge_message(tracker: Tracker) -> str | None:
    if not tracker.mission_started:
        return "Continue with the setup steps: select characters and start the mission."
    if not tracker.scene_completed:
        return (
            "The scene is not complete yet. Engage a threat (engage_threat), "
            "then build_dice_pool, then allocate_dice. Repeat until scene_completed is true. "
            "You can also switch characters with next_turn."
        )
    if tracker.scene_completed and not tracker.location_advanced:
        return (
            "The scene is complete! Check the affordances for choose_next_location "
            "and pick a new location to advance to."
        )
    return None


@pytest.mark.timeout(600)
def test_e2e_stateful():
    """LLM plays through setup → multi-round combat → scene completion (stateful)."""

    server = fresh_server()
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama", timeout=180.0)
    tracker = Tracker()
    t0 = time.monotonic()

    messages: list[dict] = [
        {"role": "system", "content": PLAYER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Begin now. Execute Phase 1: select Iryna and Chuck, "
                "then start the mission. After that, fight through the "
                "scene until it's complete, then advance to the next location."
            ),
        },
    ]

    stall_count = 0

    for turn in range(MAX_TURNS):
        response = llm_call(client, messages)
        tracker.record_usage(response)
        message = response.choices[0].message

        # Build assistant message dict
        msg_dict: dict = {"role": "assistant"}
        if message.content:
            msg_dict["content"] = message.content
        if message.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        messages.append(msg_dict)

        if not message.tool_calls:
            print(f"[Turn {turn}] LLM (no tools): {(message.content or '')[:200]}")
            nudge = _nudge_message(tracker)
            if nudge and stall_count < 3:
                stall_count += 1
                messages.append({"role": "user", "content": nudge})
                continue
            break

        stall_count = 0

        for tc in message.tool_calls:
            result_str = execute_tool(server, tc)
            trimmed = trim_response(result_str)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": trimmed})
            tracker.process_tool_result(tc, result_str, turn)

    elapsed = time.monotonic() - t0
    summary = tracker.summary(turns=turn + 1, elapsed=elapsed, label="stateful")
    write_log(messages, summary, label="stateful")
    tracker.print_results(turns=turn + 1, elapsed=elapsed)

    assert len(tracker.characters_selected) >= 1, "At least 1 character should have been selected"
    assert tracker.mission_started, "Mission should have been started"
    assert tracker.combat_rounds >= 2, f"Expected >= 2 combat rounds, got {tracker.combat_rounds}"
    fatal = [e for e in tracker.errors if "Unknown tool" in e]
    assert not fatal, f"Fatal errors: {fatal}"
