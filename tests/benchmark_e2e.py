"""Benchmark: stateful vs stateless LLM-driven game playthroughs.

Run both approaches sequentially and print a comparison table.

Usage:
    python -m pytest tests/benchmark_e2e.py -v -s
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from openai import OpenAI

from .e2e_helpers import (
    MODEL,
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

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "e2e"

# ---------------------------------------------------------------------------
# System prompts (imported from the two test modules)
# ---------------------------------------------------------------------------

from .test_e2e_ollama import PLAYER_SYSTEM_PROMPT as STATEFUL_PROMPT
from .test_e2e_ollama_stateless import PLAYER_SYSTEM_PROMPT as STATELESS_PROMPT
from .test_e2e_ollama_stateless import _build_user_message

MAX_TURNS = 50


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def _run_stateful(client) -> dict:
    """Run the stateful (full-context) agent loop."""
    server = fresh_server()
    tracker = Tracker()
    t0 = time.monotonic()
    stall_count = 0

    messages: list[dict] = [
        {"role": "system", "content": STATEFUL_PROMPT},
        {
            "role": "user",
            "content": (
                "Begin now. Execute Phase 1: select Iryna and Chuck, "
                "then start the mission. After that, fight through the "
                "scene until it's complete, then advance to the next location."
            ),
        },
    ]

    for turn in range(MAX_TURNS):
        response = llm_call(client, messages)
        tracker.record_usage(response)
        message = response.choices[0].message

        msg_dict: dict = {"role": "assistant"}
        if message.content:
            msg_dict["content"] = message.content
        if message.tool_calls:
            msg_dict["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ]
        messages.append(msg_dict)

        if not message.tool_calls:
            print(f"  [stateful][Turn {turn}] LLM (no tools): {(message.content or '')[:120]}")
            if not tracker.mission_started and stall_count < 3:
                stall_count += 1
                messages.append({"role": "user", "content": "Select characters and start the mission."})
                continue
            if not tracker.scene_completed and tracker.mission_started and stall_count < 3:
                stall_count += 1
                messages.append({"role": "user", "content": "Engage a threat, build_dice_pool, allocate_dice. Repeat."})
                continue
            if tracker.scene_completed and not tracker.location_advanced and stall_count < 3:
                stall_count += 1
                messages.append({"role": "user", "content": "Scene complete. Use choose_next_location."})
                continue
            break

        stall_count = 0
        for tc in message.tool_calls:
            result_str = execute_tool(server, tc)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": trim_response(result_str)})
            tracker.process_tool_result(tc, result_str, turn)

    elapsed = time.monotonic() - t0
    summary = tracker.summary(turns=turn + 1, elapsed=elapsed, label="stateful")
    write_log(messages, summary, label="bench_stateful")
    return summary


def _run_stateless(client) -> dict:
    """Run the stateless (fresh-context) agent loop."""
    server = fresh_server()
    tracker = Tracker()
    t0 = time.monotonic()
    stall_count = 0

    initial_state = trim_response(server.get(resource_type="session"))

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
    all_messages: list[dict] = []

    for turn in range(MAX_TURNS):
        user_msg = _build_user_message(ctx)
        messages = [
            {"role": "system", "content": STATELESS_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        response = llm_call(client, messages)
        tracker.record_usage(response)
        message = response.choices[0].message

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
            print(f"  [stateless][Turn {turn}] LLM (no tools): {(message.content or '')[:120]}")
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
            ctx["last_tool_response"] = trimmed

            try:
                result = json.loads(result_str)
            except json.JSONDecodeError:
                continue

            if "error" in result:
                ctx["last_error"] = result["error"]

            tracker.process_tool_result(tc, result_str, turn)

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
                else:
                    ctx["phase"] = "exploration"
            elif action == "engage_threat":
                ctx["phase"] = "engagement_pre_roll"
            elif action == "next_turn":
                ctx["active_character"] = data.get("active_character")
            elif action == "choose_next_location":
                ctx["phase"] = "exploration"
                ctx["scene_completed"] = False
                ctx["scene_status"] = None

        if tracker.location_advanced:
            break

    elapsed = time.monotonic() - t0
    summary = tracker.summary(turns=turn + 1, elapsed=elapsed, label="stateless")
    write_log(all_messages, summary, label="bench_stateless")
    return summary


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------

@pytest.mark.timeout(1200)
def test_benchmark():
    """Run stateful and stateless playthroughs, then compare."""
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama", timeout=180.0)

    print("\n" + "=" * 70)
    print("STATEFUL RUN")
    print("=" * 70)
    stateful = _run_stateful(client)

    print("\n" + "=" * 70)
    print("STATELESS RUN")
    print("=" * 70)
    stateless = _run_stateless(client)

    # --- Comparison table ---
    print("\n" + "=" * 70)
    print("BENCHMARK COMPARISON")
    print("=" * 70)
    header = f"{'Metric':<25} {'Stateful':>12} {'Stateless':>12} {'Delta':>12}"
    print(header)
    print("-" * len(header))

    rows = [
        ("Passed", stateful["passed"], stateless["passed"], ""),
        ("Turns", stateful["turns"], stateless["turns"],
         f"{stateless['turns'] - stateful['turns']:+d}"),
        ("Combat rounds", stateful["combat_rounds"], stateless["combat_rounds"],
         f"{stateless['combat_rounds'] - stateful['combat_rounds']:+d}"),
        ("Scene completed", stateful["scene_completed"], stateless["scene_completed"], ""),
        ("Location advanced", stateful["location_advanced"], stateless["location_advanced"], ""),
        ("Elapsed (s)", stateful["elapsed_seconds"], stateless["elapsed_seconds"],
         f"{stateless['elapsed_seconds'] - stateful['elapsed_seconds']:+.1f}"),
        ("Prompt tokens", stateful["prompt_tokens"], stateless["prompt_tokens"],
         f"{stateless['prompt_tokens'] - stateful['prompt_tokens']:+d}"),
        ("Completion tokens", stateful["completion_tokens"], stateless["completion_tokens"],
         f"{stateless['completion_tokens'] - stateful['completion_tokens']:+d}"),
        ("Total tokens", stateful["total_tokens"], stateless["total_tokens"],
         f"{stateless['total_tokens'] - stateful['total_tokens']:+d}"),
        ("Errors", len(stateful["errors"]), len(stateless["errors"]),
         f"{len(stateless['errors']) - len(stateful['errors']):+d}"),
    ]

    for label, sf, sl, delta in rows:
        print(f"{label:<25} {str(sf):>12} {str(sl):>12} {delta:>12}")

    # Write combined benchmark log
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bench_path = LOG_DIR / f"{ts}_benchmark.json"
    bench_path.write_text(json.dumps({"stateful": stateful, "stateless": stateless}, indent=2))
    print(f"\nBenchmark log: {bench_path}")

    # Both should have made meaningful progress
    assert stateful["combat_rounds"] >= 2 or stateless["combat_rounds"] >= 2, \
        "At least one approach should complete 2+ combat rounds"
