"""Shared utilities for e2e Ollama tests."""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from openai import InternalServerError

from havoc_server.runtime import GameRuntime
from gia_core.errors import DomainError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "qwen3.5:9b"
LLM_RETRIES = 3
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "e2e"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get",
            "description": "Retrieve a resource by type and ID. Returns data + available affordances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "enum": ["session", "character", "character_template", "location", "scene", "enemy", "rules"],
                        "description": "Type of resource to retrieve",
                    },
                    "id": {
                        "type": "string",
                        "description": "Resource ID",
                    },
                },
                "required": ["resource_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search/browse resources. Returns results + available affordances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "enum": ["characters", "locations", "enemies", "ubermenschen"],
                        "description": "Type to search",
                    },
                    "filters": {
                        "type": "string",
                        "description": 'JSON string of filters, e.g. {"sector": 3}',
                    },
                },
                "required": ["resource_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": "Execute an action from affordances. Returns result + next affordances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action name from affordances",
                    },
                    "params": {
                        "type": "string",
                        "description": "JSON string of action parameters",
                    },
                },
                "required": ["action"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Ollama check
# ---------------------------------------------------------------------------

def ollama_reachable(host: str = "localhost", port: int = 11434, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

class _JsonToolAdapter:
    """JSON-string tool-calling surface for the local-model e2e harness.

    Ollama-class small models are driven through flat, JSON-string-typed
    tool arguments (see ``TOOLS`` above) rather than GAS 2.0's typed,
    capability-id-based ``act`` — a deliberate simplification for small
    models, not migration debt (unlike the deleted ``compat.py``, which
    this replaces, nothing else depends on this class).
    """

    def __init__(self, runtime: GameRuntime):
        self.runtime = runtime

    def create_session(self) -> str:
        return json.dumps(self.runtime.create_session().model_dump(mode="json", by_alias=True))

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        try:
            result = self.runtime.get(resource_type, id, session_id)
        except DomainError as error:
            return json.dumps({"error": str(error)})
        return json.dumps(result.model_dump(mode="json", by_alias=True))

    def search(self, resource_type: str, filters: str = "{}", session_id: str = "") -> str:
        try:
            parsed_filters: Mapping = json.loads(filters) if filters else {}
        except json.JSONDecodeError:
            parsed_filters = {}
        try:
            result = self.runtime.search(resource_type, parsed_filters, session_id)
        except DomainError as error:
            return json.dumps({"error": str(error)})
        return json.dumps(result.model_dump(mode="json", by_alias=True))

    def act(self, action: str, params: str = "{}", session_id: str = "") -> str:
        try:
            parsed_params = json.loads(params) if params else {}
        except json.JSONDecodeError:
            parsed_params = {}
        try:
            revision = self.runtime.get("session", session_id=session_id).state_revision
            result = self.runtime.act(action, parsed_params, session_id, revision)
        except DomainError as error:
            return json.dumps({"error": str(error)})
        return json.dumps(result.model_dump(mode="json", by_alias=True))


def fresh_server():
    """Create a fresh runtime and explicitly provision its test session."""
    runtime = GameRuntime()
    bootstrap = _JsonToolAdapter(runtime)
    session_id = json.loads(bootstrap.create_session())["data"]["id"]
    return bootstrap, session_id


def execute_tool(server, tool_call, session_id: str) -> str:
    """Run a tool call against the server module."""
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        args = {}

    try:
        if name == "get":
            return server.get(
                resource_type=args.get("resource_type", ""),
                id=args.get("id", ""),
                session_id=session_id,
            )
        elif name == "search":
            return server.search(
                resource_type=args.get("resource_type", "characters"),
                filters=args.get("filters", "{}"),
                session_id=session_id,
            )
        elif name == "act":
            return server.act(
                action=args.get("action", ""),
                params=args.get("params", "{}"),
                session_id=session_id,
            )
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except (KeyError, TypeError) as e:
        return json.dumps({"error": f"Missing or invalid parameter: {e}"})


def trim_response(result_str: str, max_len: int = 2000) -> str:
    """Trim large tool responses to keep context manageable for the LLM."""
    if len(result_str) <= max_len:
        return result_str
    try:
        result = json.loads(result_str)
        if "affordances" in result and len(result["affordances"]) > 3:
            result["affordances"] = result["affordances"][:3]
            result["affordances"].append({
                "action": "...",
                "description": "More actions available — call get(resource_type='session') to see all",
            })
        trimmed = json.dumps(result, indent=2)
        if len(trimmed) > max_len:
            return trimmed[:max_len] + "\n... (truncated)"
        return trimmed
    except json.JSONDecodeError:
        return result_str[:max_len] + "\n... (truncated)"


def llm_call(client, messages, retries=LLM_RETRIES):
    """Call Ollama with retries on transient 500 errors."""
    for attempt in range(retries):
        try:
            return client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                extra_body={"options": {"num_ctx": 8192}},
            )
        except InternalServerError:
            if attempt == retries - 1:
                raise
            print(f"  Ollama 500, retrying ({attempt + 1}/{retries})...")
            time.sleep(2)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def write_log(messages: list[dict], summary: dict, label: str = "") -> Path:
    """Write the full conversation transcript + summary to a timestamped log file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    status = "pass" if summary.get("passed") else "fail"
    tag = f"_{label}" if label else ""
    log_path = LOG_DIR / f"{ts}{tag}_{status}.json"
    log_path.write_text(json.dumps({"summary": summary, "messages": messages}, indent=2))
    print(f"\nLog written to {log_path}")
    return log_path


# ---------------------------------------------------------------------------
# Tracking helpers
# ---------------------------------------------------------------------------

class Tracker:
    """Tracks game progress milestones and token usage."""

    def __init__(self):
        self.characters_selected: list[str] = []
        self.mission_started = False
        self.combat_rounds = 0
        self.scene_completed = False
        self.location_advanced = False
        self.characters_switched = 0
        self.errors: list[str] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def record_usage(self, response):
        """Accumulate token counts from an OpenAI response."""
        usage = getattr(response, "usage", None)
        if usage:
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.total_tokens += getattr(usage, "total_tokens", 0) or 0

    def process_tool_result(self, tool_call, result_str: str, turn: int):
        """Parse a tool result and update tracking state. Returns True if logged."""
        try:
            result = json.loads(result_str)
        except json.JSONDecodeError:
            return

        if "error" in result:
            self.errors.append(f"Turn {turn}, {tool_call.function.name}: {result['error']}")
            print(f"[Turn {turn}] ERROR {tool_call.function.name}: {result['error']}")
            return

        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            args = {}

        action = args.get("action", "")
        fn_name = tool_call.function.name
        data = result.get("data", result)

        if fn_name != "act":
            print(f"[Turn {turn}] {fn_name}({args.get('resource_type', '')})")
            return

        if action == "select_character":
            char_name = data.get("message", "")
            self.characters_selected.append(char_name)
            print(f"[Turn {turn}] Character selected: {char_name}")

        elif action == "start_mission":
            self.mission_started = True
            threats = data.get("threats", [])
            print(f"[Turn {turn}] Mission started at {data.get('location', '?')} "
                  f"— {len(threats)} threat(s), objective rating {data.get('objective_rating', '?')}")

        elif action == "engage_threat":
            threat = data.get("threat", data)
            print(f"[Turn {turn}] Engaged: {threat.get('name', '?')} "
                  f"(rating {threat.get('rating', '?')})")

        elif action == "build_dice_pool":
            self.combat_rounds += 1
            print(f"[Turn {turn}] Combat round {self.combat_rounds}: "
                  f"{data.get('message', '')} — kept {data.get('player_kept', [])}, "
                  f"GM kept {data.get('gm_kept', [])}")

        elif action == "allocate_dice":
            completed = data.get("scene_completed", False)
            scene_status = data.get("scene_status", {})
            remaining_gm = data.get("remaining_gm_dice", 0)
            objectives = scene_status.get("objectives", [])
            threats = scene_status.get("threats", [])
            obj_str = ", ".join(f"{o['name']}({o['rating']})" for o in objectives) if objectives else ""
            thr_str = ", ".join(
                f"{t['name']}({t['rating']}{'✓' if t.get('defeated') else ''})" for t in threats
            ) if threats else ""
            print(f"[Turn {turn}] Allocated — GM injuries: {remaining_gm} | "
                  f"Obj: [{obj_str}] Threats: [{thr_str}]"
                  f"{' | SCENE COMPLETE!' if completed else ''}")
            if completed:
                self.scene_completed = True

        elif action == "next_turn":
            self.characters_switched += 1
            print(f"[Turn {turn}] Switched to: {data.get('active_character', '?')}")

        elif action == "choose_next_location":
            self.location_advanced = True
            threats = data.get("threats", [])
            print(f"[Turn {turn}] Advanced to {data.get('location', '?')} "
                  f"— {len(threats)} threat(s), objective: {data.get('objective', '?')}")

        elif action == "heal":
            print(f"[Turn {turn}] Healed: {data.get('message', '')}")

        elif action == "share_blood":
            print(f"[Turn {turn}] Blood shared: {data.get('message', '')}")

        else:
            print(f"[Turn {turn}] act:{action}")

    def summary(self, *, turns: int, elapsed: float, label: str = "") -> dict:
        fatal_errors = [e for e in self.errors if "Unknown tool" in e]
        passed = (
            len(self.characters_selected) >= 1
            and self.mission_started
            and self.combat_rounds >= 2
            and not fatal_errors
        )
        return {
            "label": label,
            "passed": passed,
            "turns": turns,
            "elapsed_seconds": round(elapsed, 1),
            "characters_selected": self.characters_selected,
            "mission_started": self.mission_started,
            "combat_rounds": self.combat_rounds,
            "scene_completed": self.scene_completed,
            "location_advanced": self.location_advanced,
            "characters_switched": self.characters_switched,
            "errors": self.errors,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": MODEL,
        }

    def print_results(self, *, turns: int, elapsed: float):
        print(f"\n--- Results ---")
        print(f"Characters selected: {self.characters_selected}")
        print(f"Mission started:     {self.mission_started}")
        print(f"Combat rounds:       {self.combat_rounds}")
        print(f"Scene completed:     {self.scene_completed}")
        print(f"Location advanced:   {self.location_advanced}")
        print(f"Characters switched: {self.characters_switched}")
        print(f"Errors:              {self.errors}")
        print(f"Total turns:         {turns}")
        print(f"Elapsed:             {elapsed:.1f}s")
        print(f"Tokens (prompt):     {self.prompt_tokens}")
        print(f"Tokens (completion): {self.completion_tokens}")
        print(f"Tokens (total):      {self.total_tokens}")
