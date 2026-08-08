"""Agent loop — GM agent using Ollama (local) via OpenAI-compatible API."""

from __future__ import annotations

import json
from openai import OpenAI

from havoc_server.runtime import GameRuntime
from gia_core.errors import DomainError

SYSTEM_PROMPT = """\
You are the Gamesmaster (GM) for EAT THE REICH, a tabletop RPG about vampire commandos \
in WWII Paris on a mission to kill Hitler.

You interact with the game backend through 3 tools: `get`, `search`, and `act`.

IMPORTANT — Affordance-driven interaction:
- Every tool response includes an `affordances` array listing what actions are available NOW
- Use ONLY the actions listed in affordances — do not guess or invent actions
- Each affordance has: action name, description, schema, and constraints
- To execute an affordance, use `act` with the action name and parameters

Your role as GM:
1. NARRATE scenes in vivid, over-the-top pulp action style — ultraviolent, joyous, celebratory
2. CONTROL enemies and describe their actions during combat
3. MANAGE turn order — you choose which player character acts next
4. EXPLAIN mechanics when needed — dice pools, allocation, injuries, blood
5. GUIDE players through character selection, then through the mission

Game flow:
- Setup: Help players choose from 6 pre-gen vampire characters (Iryna, Nicole, Cosgrave, Chuck, Astrid, Flint)
- Coffinfall: Drop coffins crash into Paris — dramatic entrances for each character
- Exploration: Move between connected locations in Paris (Sector 3 → 2 → 1)
- Engagement: Build dice pools (stat + equipment + abilities), roll, allocate dice to objectives/threats/defense/feed/special
- Between scenes: Heal injuries (3 Blood), share blood, choose next location

Combat turn:
1. Player chooses stat + equipment + abilities → dice pool built
2. Both sides roll, discard 1-3 (failures)
3. Player allocates kept dice: 4-5 = 1 success, 6 = critical (2 successes or SPECIAL)
   - Objective: reduce rating → Threat: reduce rating → Defense: remove GM dice → Feed: gain Blood → Special: crit only
4. Remaining GM dice = injuries (1-2 dice: roll category + mark. 3+: Downed)
5. End of round: Reinforcements (defeated non-Solo threats return with d6 rating)

Tone: ultraviolent, imprecise, over-the-top. These are vampires tearing nazis apart. \
Describe everything like an action movie. Don't hold back.\
"""

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


class AgentLoop:
    """Stateless agent loop — all game state lives in the backend."""

    def __init__(self, runtime: GameRuntime, session_id: str):
        self.runtime = runtime
        self.session_id = session_id
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )
        self.model = "qwen3.5:9b"
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

    def chat(self, user_message: str) -> str:
        """Process a user message and return the GM's response."""
        self.messages.append({"role": "user", "content": user_message})

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            message = response.choices[0].message
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
            self.messages.append(msg_dict)

            if not message.tool_calls:
                return message.content or ""

            for tool_call in message.tool_calls:
                result = self._execute_tool(tool_call)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

    def _execute_tool(self, tool_call) -> str:
        """Execute a tool call against the runtime directly."""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            args = {}

        try:
            if name == "get":
                result = self.runtime.get(
                    resource_type=args.get("resource_type", ""),
                    id=args.get("id", ""),
                    session_id=self.session_id,
                )
            elif name == "search":
                try:
                    filters = json.loads(args.get("filters", "{}"))
                except json.JSONDecodeError:
                    filters = {}
                result = self.runtime.search(
                    resource_type=args.get("resource_type", "characters"),
                    filters=filters,
                    session_id=self.session_id,
                )
            elif name == "act":
                try:
                    params = json.loads(args.get("params", "{}"))
                except json.JSONDecodeError:
                    params = {}
                # `GameRuntime.act` requires an explicit `expected_revision`
                # for action-name dispatch — the deleted JSON compat path
                # used to resolve this automatically.
                revision = self.runtime.get("session", session_id=self.session_id).state_revision
                result = self.runtime.act(
                    action=args.get("action", ""),
                    params=params,
                    session_id=self.session_id,
                    expected_revision=revision,
                )
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        except DomainError as error:
            return json.dumps({"error": str(error)})

        return json.dumps(result.model_dump(mode="json", by_alias=True))
