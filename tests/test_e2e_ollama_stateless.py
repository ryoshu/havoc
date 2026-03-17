"""E2E test (stateless): LLM sees only the system prompt + latest tool result each turn.

Each LLM call is independent — no conversation history. The LLM decides its
next action purely from the affordances in the most recent tool response.
This keeps token cost constant per turn but requires the system prompt to
encode enough strategy for the LLM to make progress without memory.
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
You are a player in EAT THE REICH. You have NO memory of previous turns.

You interact with the game through the `act` tool. The user message tells you EXACTLY what
to do each turn — follow its instruction precisely.

RULES:
- Call EXACTLY ONE tool per turn.
- The tool response contains an "affordances" array with available actions.
- params is always a JSON STRING, not an object.
- Do NOT call `get` or `search` — only use `act`.
- Follow the user's instruction. Do not deviate.\
"""


def _build_user_message(context: dict) -> str:
    """Build a directive user message telling the stateless LLM exactly what to do next.

    For most phases, gives an exact tool call — no tool response needed.
    Only includes data when the LLM must read dynamic values (threat names, dice, location IDs).
    """
    phase = context.get("phase", "setup")
    selected = context.get("characters_selected", [])
    error = context.get("last_error")
    tool_resp = context.get("last_tool_response", "")

    error_line = f"\nPrevious error: {error}" if error else ""

    if phase == "setup":
        if len(selected) == 0:
            return f'Call act with action="select_character" and params={{"template_id": "iryna"}}{error_line}'
        elif len(selected) == 1:
            return f'Call act with action="select_character" and params={{"template_id": "chuck"}}{error_line}'
        else:
            return f'Call act with action="start_mission"{error_line}'

    if phase == "exploration":
        # Need threat name from tool response
        threat_name = context.get("threat_name", "Police Patrol")
        params = json.dumps({"threat_name": threat_name})
        return f'Call act with action="engage_threat" and params={params}{error_line}'

    if phase == "engagement_pre_roll":
        return f'Call act with action="build_dice_pool" and params={{"stat": "brawl"}}{error_line}'

    if phase == "engagement_post_roll":
        player_kept = context.get("player_kept", [])
        gm_kept = context.get("gm_kept", [])

        # Pre-compute allocation so the LLM just copies it
        obj_dice = []
        other_dice = []
        for i, d in enumerate(player_kept):
            if i < len(player_kept) // 2 + 1:
                obj_dice.append(d)
            else:
                other_dice.append(d)

        alloc = {"objective": obj_dice}
        if other_dice:
            alloc["threat"] = other_dice

        params_str = json.dumps({"allocations": alloc})
        return f'Your kept dice: {player_kept}. GM kept: {gm_kept}.\nCall act with action="allocate_dice" and params={params_str}{error_line}'

    if phase == "between_scenes":
        # Need location ID from tool response — extract from affordances
        location_id = context.get("next_location_id")
        if location_id:
            params = json.dumps({"location_id": location_id})
            return f'Call act with action="choose_next_location" and params={params}{error_line}'
        # Fallback: show tool response so LLM can find the location
        return f'Scene complete! Find choose_next_location in affordances and call it.\n\n{tool_resp}{error_line}'

    return f'Call act with the first action from affordances.\n\n{tool_resp}{error_line}'


@pytest.mark.timeout(600)
def test_e2e_stateless():
    """LLM plays through setup → multi-round combat → scene completion (stateless)."""

    server = fresh_server()
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama", timeout=180.0)
    tracker = Tracker()
    t0 = time.monotonic()

    # Seed context with initial session state (gives the LLM affordances on turn 0)
    initial_state = trim_response(server.get(resource_type="session"))

    # Mutable context dict — passed to the LLM each turn as the user message
    ctx: dict = {
        "phase": "setup",
        "characters_selected": [],
        "active_character": None,
        "player_kept": None,
        "gm_kept": None,
        "scene_status": None,
        "scene_completed": False,
        "last_error": None,
        "last_tool_response": initial_state,
    }

    all_messages: list[dict] = []  # for logging only
    stall_count = 0

    for turn in range(MAX_TURNS):
        user_msg = _build_user_message(ctx)
        messages = [
            {"role": "system", "content": PLAYER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        response = llm_call(client, messages)
        tracker.record_usage(response)
        message = response.choices[0].message

        # Log for transcript
        all_messages.append({"role": "user", "content": user_msg})
        if message.content:
            all_messages.append({"role": "assistant", "content": message.content})
        if message.tool_calls:
            all_messages.append({
                "role": "assistant",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in message.tool_calls
                ],
            })

        if not message.tool_calls:
            print(f"[Turn {turn}] LLM (no tools): {(message.content or '')[:200]}")
            stall_count += 1
            ctx["last_error"] = "You must call a tool. Read the affordances and pick an action."
            if stall_count >= 3:
                break
            continue

        stall_count = 0
        ctx["last_error"] = None

        for tc in message.tool_calls:
            result_str = execute_tool(server, tc)
            trimmed = trim_response(result_str)
            all_messages.append({"role": "tool", "tool_call_id": tc.id, "content": trimmed})

            # Update context from result
            ctx["last_tool_response"] = trimmed

            try:
                result = json.loads(result_str)
            except json.JSONDecodeError:
                continue

            if "error" in result:
                ctx["last_error"] = result["error"]

            tracker.process_tool_result(tc, result_str, turn)

            # Extract state for next turn's context
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            action = args.get("action", "")
            data = result.get("data", result)

            if action == "select_character":
                name = data.get("message", "").replace(" joins the mission!", "")
                if name:
                    ctx["characters_selected"].append(name)

            elif action == "start_mission":
                ctx["phase"] = "exploration"
                ctx["active_character"] = data.get("active_character")
                # Extract first threat name for engage_threat
                threats = data.get("threats", [])
                if threats:
                    ctx["threat_name"] = threats[0]["name"]

            elif action == "build_dice_pool":
                ctx["player_kept"] = data.get("player_kept")
                ctx["gm_kept"] = data.get("gm_kept")
                ctx["phase"] = "engagement_post_roll"

            elif action == "allocate_dice":
                ctx["player_kept"] = None
                ctx["gm_kept"] = None
                ctx["scene_status"] = data.get("scene_status")
                if data.get("scene_completed"):
                    ctx["scene_completed"] = True
                    ctx["phase"] = "between_scenes"
                    # Extract next location from affordances
                    affs = result.get("affordances", [])
                    for aff in affs:
                        if aff.get("action") == "choose_next_location":
                            schema = aff.get("schema", {})
                            loc_id = schema.get("location_id", {}).get("const")
                            if loc_id:
                                ctx["next_location_id"] = loc_id
                                break
                else:
                    ctx["phase"] = "exploration"
                    # Update threat name for next engage
                    scene_status = data.get("scene_status", {})
                    for t in scene_status.get("threats", []):
                        if not t.get("defeated"):
                            ctx["threat_name"] = t["name"]
                            break

            elif action == "engage_threat":
                ctx["phase"] = "engagement_pre_roll"

            elif action == "next_turn":
                ctx["active_character"] = data.get("active_character")

            elif action == "choose_next_location":
                ctx["phase"] = "exploration"
                ctx["scene_completed"] = False
                ctx["scene_status"] = None

        # Stop after advancing to next location
        if tracker.location_advanced:
            break

    elapsed = time.monotonic() - t0
    summary = tracker.summary(turns=turn + 1, elapsed=elapsed, label="stateless")
    write_log(all_messages, summary, label="stateless")
    tracker.print_results(turns=turn + 1, elapsed=elapsed)

    assert len(tracker.characters_selected) >= 1, "At least 1 character should have been selected"
    assert tracker.mission_started, "Mission should have been started"
    assert tracker.combat_rounds >= 2, f"Expected >= 2 combat rounds, got {tracker.combat_rounds}"
    fatal = [e for e in tracker.errors if "Unknown tool" in e]
    assert not fatal, f"Fatal errors: {fatal}"
