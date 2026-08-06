"""LLM agent — drives eval tasks via tool calling (GAS or Traditional mode)."""

from __future__ import annotations

import json
import time

from openai import APITimeoutError, DefaultHttpxClient, InternalServerError, OpenAI, RateLimitError

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None

try:
    import anthropic as anthropic_sdk
except ImportError:  # pragma: no cover
    anthropic_sdk = None

from eval.gas_server.server import EvalRuntime
from eval.trad_server.server import TradRuntime

from .config import EvalConfig, DOMAIN_DEFAULT_USER
from .metrics import EvalMetrics, TurnDetail

SYSTEM_PROMPT = """\
You are a project management assistant. You have access to tools for managing \
issues, sprints, and projects. Complete the task described by the user.

Rules:
- Use the tools provided to accomplish the task.
- Read the tool results carefully and use the information to decide your next action.
- If a tool call fails, read the error message and adjust your approach.
- When the task is complete, respond with "TASK COMPLETE" in your message.
- Be efficient: take the most direct path to completing the task.
"""

GAS_SYSTEM_ADDENDUM = """
You have 3 tools: get, search, and act.
- Every response includes an "affordances" array showing valid actions for the current state.
- Use the affordances to discover what actions are available.
- The "act" tool executes actions listed in the affordances.
- Copy action names and parameter values exactly from the affordances.
"""

GAS_ENFORCED_ADDENDUM = """
This is gas-enforced mode. Every stateful response includes state_revision.
Pass that exact revision as expected_revision on every act call, and send
params as an object. The server rejects unavailable actions, invalid
parameters, and stale revisions; treat those errors as measurements, not as
successful tool calls.
"""

TRAD_SYSTEM_ADDENDUM = """
You have multiple specialized tools for different operations.
- Read the tool descriptions carefully to understand what each tool does.
- Pay attention to constraints mentioned in tool descriptions.
- Some operations require certain preconditions (e.g., issue must be in specific status).
"""

# --- Cruise domain prompts ---

CRUISE_SYSTEM_PROMPT = """\
You are a cruise booking assistant. You have access to tools for managing \
cruise bookings, passengers, and payments. Complete the task described by the user.

Rules:
- Use the tools provided to accomplish the task.
- Read the tool results carefully and use the information to decide your next action.
- If a tool call fails, read the error message and adjust your approach.
- When the task is complete, respond with "TASK COMPLETE" in your message.
- Be efficient: take the most direct path to completing the task.
- Bookings go through: held → confirmed → paid → embarked.
- Payments go through: pending → authorized → captured (then optionally refunded).
- A booking must have at least one passenger before it can be confirmed.
- A booking must have a captured payment before it can be marked as paid.
"""

CRUISE_GAS_ADDENDUM = """
You have 3 tools: get, search, and act.
- Every response includes an "affordances" array showing valid actions for the current state.
- Use the affordances to discover what actions are available.
- The "act" tool executes actions listed in the affordances.
- Copy action names and parameter values exactly from the affordances.
"""

CRUISE_TRAD_ADDENDUM = """
You have multiple specialized tools for different operations.
- Read the tool descriptions carefully to understand what each tool does.
- Pay attention to constraints mentioned in tool descriptions.
- Bookings, payments, and cruise status have specific lifecycle constraints.
"""


# --- Auto domain prompts ---

AUTO_SYSTEM_PROMPT = """\
You are an automotive dealership assistant. You have access to tools for managing \
vehicle inventory, customer records, test drives, deals, offers, trade-ins, and \
credit applications. Complete the task described by the user.

Rules:
- Use the tools provided to accomplish the task.
- Read the tool results carefully and use the information to decide your next action.
- If a tool call fails, read the error message and adjust your approach.
- When the task is complete, respond with "TASK COMPLETE" in your message.
- Be efficient: take the most direct path to completing the task.
- Deals go through: pending → negotiating → finalized → delivered (or cancelled).
- Offers go through: pending → accepted/rejected/countered/expired.
- Trade-ins go through: pending → appraised → accepted/rejected.
- Credit apps go through: pending → approved/denied.
- A deal needs an accepted offer before it can be finalized.
- Offer price cannot go below the vehicle's invoice price (price floor).
"""

AUTO_GAS_ADDENDUM = """
You have 3 tools: get, search, and act.
- Every response includes an "affordances" array showing valid actions for the current state.
- Use the affordances to discover what actions are available.
- The "act" tool executes actions listed in the affordances.
- Copy action names and parameter values exactly from the affordances.
"""

AUTO_TRAD_ADDENDUM = """
You have multiple specialized tools for different operations.
- Read the tool descriptions carefully to understand what each tool does.
- Pay attention to constraints mentioned in tool descriptions.
- Deals, offers, trade-ins, and credit applications have specific lifecycle constraints.
"""


class EvalAgent:
    """LLM agent that drives eval tasks via structured tool calling."""

    def __init__(
        self,
        config: EvalConfig,
        gas_runtime: EvalRuntime | None = None,
        trad_runtime: TradRuntime | None = None,
    ):
        self.config = config
        self.gas_runtime = gas_runtime
        self.trad_runtime = trad_runtime
        self.is_anthropic = config.model.is_anthropic
        self.is_gas = config.mode in {"gas-advisory", "gas-enforced"}
        self.is_gas_enforced = config.mode == "gas-enforced"

        if self.is_anthropic:
            if anthropic_sdk is None:
                raise ImportError("anthropic package required for Anthropic models: pip install anthropic")
            kwargs = {"api_key": config.model.api_key, "timeout": config.timeout_seconds}
            if certifi is not None:
                import httpx
                kwargs["http_client"] = httpx.Client(verify=certifi.where())
            self.anthropic_client = anthropic_sdk.Anthropic(**kwargs)
            self.client = None
        else:
            http_client = None
            if certifi is not None:
                http_client = DefaultHttpxClient(verify=certifi.where())
            self.client = OpenAI(
                base_url=config.model.api_base,
                api_key=config.model.api_key,
                timeout=config.timeout_seconds,
                http_client=http_client,
            )
            self.anthropic_client = None

    def _get_tools(self) -> list[dict]:
        """Get tool definitions for the agent."""
        if self.is_gas:
            domain = self.config.domain
            if domain == "cruise":
                get_types = ["cruise", "booking", "passenger", "payment", "user", "session"]
                search_types = ["cruises", "bookings", "passengers", "payments", "users"]
                get_desc = "Retrieve a resource by type and ID. Returns data + available affordances. resource_type: cruise, booking, passenger, payment, user, session."
                search_desc = "Search resources. Returns results + affordances. resource_type: cruises, bookings, passengers, payments, users. filters: JSON string."
            elif domain == "auto":
                get_types = ["vehicle", "customer", "test_drive", "deal", "offer", "trade_in", "user", "session"]
                search_types = ["vehicles", "customers", "test_drives", "deals", "offers", "trade_ins", "users"]
                get_desc = "Retrieve a resource by type and ID. Returns data + available affordances. resource_type: vehicle, customer, test_drive, deal, offer, trade_in, user, session."
                search_desc = "Search resources. Returns results + affordances. resource_type: vehicles, customers, test_drives, deals, offers, trade_ins, users. filters: JSON string."
            else:
                get_types = ["issue", "project", "sprint", "user", "comment", "session"]
                search_types = ["issues", "projects", "sprints", "users", "comments"]
                get_desc = "Retrieve a resource by type and ID. Returns data + available affordances. resource_type: issue, project, sprint, user, comment, session."
                search_desc = "Search resources. Returns results + affordances. resource_type: issues, projects, sprints, users, comments. filters: JSON string."
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "get",
                        "description": get_desc,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "resource_type": {"type": "string", "enum": get_types},
                                "id": {"type": "string", "description": "Resource ID"},
                            },
                            "required": ["resource_type"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": search_desc,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "resource_type": {"type": "string", "enum": search_types},
                                "filters": {"type": "string", "description": "JSON filter string"},
                            },
                            "required": ["resource_type"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "act",
                        "description": "Execute an action from the affordances list. Returns result + next affordances.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "description": "Action name from affordances"},
                                "params": {"type": "string", "description": "JSON params string"},
                            },
                            "required": ["action"],
                        },
                    },
                },
            ]
            if self.is_gas_enforced:
                # Enforced mode sends typed mappings and an optimistic
                # concurrency revision instead of JSON strings.
                for tool in tools:
                    function = tool["function"]
                    if function["name"] == "search":
                        props = function["parameters"]["properties"]
                        props["filters"] = {"type": "object", "additionalProperties": True}
                    elif function["name"] == "act":
                        props = function["parameters"]["properties"]
                        props["params"] = {"type": "object", "additionalProperties": True}
                        props["expected_revision"] = {"type": "integer", "minimum": 0}
                        function["parameters"]["required"] = ["action", "expected_revision"]
            return tools
        else:
            return self.trad_runtime.get_tool_definitions()

    def _execute_tool(self, tool_name: str, args: dict, session_id: str) -> str:
        """Execute a tool call against the appropriate runtime."""
        if self.is_gas:
            if tool_name == "get":
                if self.is_gas_enforced:
                    result = self.gas_runtime.get_enforced(
                        args.get("resource_type", ""), args.get("id", ""), session_id=session_id
                    )
                    return json.dumps(result.model_dump(mode="json", by_alias=True))
                return self.gas_runtime.get(
                    args.get("resource_type", ""),
                    args.get("id", ""),
                    session_id,
                )
            elif tool_name == "search":
                if self.is_gas_enforced:
                    result = self.gas_runtime.search_enforced(
                        args.get("resource_type", ""), args.get("filters", {}), session_id=session_id
                    )
                    return json.dumps(result.model_dump(mode="json", by_alias=True))
                return self.gas_runtime.search(
                    args.get("resource_type", ""),
                    args.get("filters", "{}"),
                    session_id,
                )
            elif tool_name == "act":
                if self.is_gas_enforced:
                    raw_params = args.get("params", {})
                    if isinstance(raw_params, str):
                        try:
                            raw_params = json.loads(raw_params)
                        except json.JSONDecodeError:
                            raw_params = {}
                    result = self.gas_runtime.act_enforced(
                        args.get("action", ""),
                        raw_params,
                        session_id=session_id,
                        expected_revision=args.get("expected_revision"),
                    )
                    return json.dumps(result.model_dump(mode="json", by_alias=True))
                return self.gas_runtime.act(
                    args.get("action", ""),
                    args.get("params", "{}"),
                    session_id,
                )
            else:
                return json.dumps({"error": f"Unknown GAS tool: {tool_name}"})
        else:
            return self.trad_runtime.call_tool(tool_name, args, session_id)

    def _is_information_tool(self, tool_name: str) -> bool:
        """Return True if the tool is read-only/information gathering."""
        if self.is_gas:
            return tool_name in {"get", "search"}
        # Resolve poly names to canonical before checking prefixes
        resolved = tool_name
        if self.trad_runtime and self.trad_runtime.name_map:
            resolved = self.trad_runtime.name_map.get(tool_name, tool_name)
        return (
            resolved.startswith("get_")
            or resolved.startswith("search_")
            or resolved.startswith("list_")
        )

    @staticmethod
    def _prune_prior_affordances(messages: list[dict]) -> None:
        """Remove affordance arrays from prior tool responses in message history.

        Replaces the full affordances array with a short note so the LLM
        only sees affordances from the most recent tool response.  This
        reduces context growth from O(turns²) to O(turns).
        """
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if '"affordances"' not in content:
                continue
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "affordances" in data:
                data["affordances"] = "[see latest response]"
                msg["content"] = json.dumps(data)

    @staticmethod
    def _extract_afforded_actions(result_data: dict | None) -> set[str] | None:
        """Extract action names from a GAS response affordances array."""
        if not isinstance(result_data, dict):
            return None
        affordances = result_data.get("affordances")
        if not isinstance(affordances, list):
            return None
        actions = set()
        for affordance in affordances:
            if isinstance(affordance, dict):
                action = affordance.get("action")
                if isinstance(action, str) and action:
                    actions.add(action)
        return actions

    def run(self, task_description: str, session_id: str, max_turns: int = 50) -> EvalMetrics:
        """Run the agent on a task. Returns collected metrics."""
        metrics = EvalMetrics(
            mode=self.config.mode if self.is_gas else f"trad-{self.config.tool_level}",
            model_name=self.config.model.name,
        )

        domain = self.config.domain
        if domain == "cruise":
            system = CRUISE_SYSTEM_PROMPT
            system += CRUISE_GAS_ADDENDUM if self.is_gas else CRUISE_TRAD_ADDENDUM
        elif domain == "auto":
            system = AUTO_SYSTEM_PROMPT
            system += AUTO_GAS_ADDENDUM if self.is_gas else AUTO_TRAD_ADDENDUM
        else:
            system = SYSTEM_PROMPT
            system += GAS_SYSTEM_ADDENDUM if self.is_gas else TRAD_SYSTEM_ADDENDUM
        if self.is_gas_enforced:
            system += GAS_ENFORCED_ADDENDUM

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task_description},
        ]

        tools = self._get_tools()
        t0 = time.monotonic()
        turn = 0
        consecutive_errors = 0
        pending_error_turn: int | None = None
        last_afforded_actions: set[str] | None = None
        gas_act_calls = 0
        gas_in_affordance_calls = 0

        while turn < max_turns:
            turn += 1
            turn_detail = TurnDetail(turn_number=turn)
            t_turn = time.monotonic()

            try:
                extra_kwargs = {}
                if self.config.model.is_ollama:
                    extra_kwargs["extra_body"] = {"num_ctx": 16384}

                response = self._call_with_retry(messages, tools, extra_kwargs)
            except Exception as e:
                turn_detail.error_message = str(e)
                turn_detail.was_valid = False
                metrics.turns.append(turn_detail)
                metrics.invalid_action_count += 1
                break

            turn_detail.latency_ms = (time.monotonic() - t_turn) * 1000

            # Extract usage
            if hasattr(response, "usage") and response.usage:
                turn_detail.tokens_in = response.usage.prompt_tokens or 0
                turn_detail.tokens_out = response.usage.completion_tokens or 0
                metrics.total_tokens_in += turn_detail.tokens_in
                metrics.total_tokens_out += turn_detail.tokens_out

            choice = response.choices[0]
            assistant_msg = choice.message

            # Check for completion
            if assistant_msg.content and "TASK COMPLETE" in assistant_msg.content.upper():
                messages.append({"role": "assistant", "content": assistant_msg.content})
                metrics.task_completed = True
                metrics.turns.append(turn_detail)
                break

            # Handle tool calls
            if assistant_msg.tool_calls:
                # Add assistant message with tool calls
                messages.append(assistant_msg.model_dump())

                for tc in assistant_msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    if turn_detail.action:
                        turn_detail.action = f"{turn_detail.action},{fn_name}"
                    else:
                        turn_detail.action = fn_name
                    if not turn_detail.params:
                        turn_detail.params = fn_args

                    if self.is_gas and fn_name == "act":
                        gas_act_calls += 1
                        chosen_action = str(fn_args.get("action", ""))
                        if last_afforded_actions is not None and chosen_action in last_afforded_actions:
                            gas_in_affordance_calls += 1

                    result = self._execute_tool(fn_name, fn_args, session_id)

                    result_data = None
                    try:
                        result_data = json.loads(result)
                    except json.JSONDecodeError:
                        result_data = None

                    if self.is_gas:
                        afforded_actions = self._extract_afforded_actions(result_data)
                        if afforded_actions is not None:
                            last_afforded_actions = afforded_actions

                    if isinstance(result_data, dict) and "error" in result_data:
                        turn_detail.was_valid = False
                        if not turn_detail.error_message:
                            turn_detail.error_message = str(result_data["error"])
                        metrics.invalid_action_count += 1
                        consecutive_errors += 1
                        if pending_error_turn is None:
                            pending_error_turn = turn
                    else:
                        metrics.valid_action_count += 1
                        consecutive_errors = 0

                        # State-changing actions emit events in both runtimes.
                        events = result_data.get("events", []) if isinstance(result_data, dict) else []
                        state_changed = isinstance(events, list) and len(events) > 0
                        turn_detail.state_changed = turn_detail.state_changed or state_changed

                        # Secondary metric: first backend-accepted state-changing action.
                        if state_changed and metrics.time_to_first_valid_action == 0:
                            metrics.time_to_first_valid_action = turn

                        # Secondary metric: count non-read calls that were valid but made no change.
                        if (not self._is_information_tool(fn_name)) and (not state_changed):
                            metrics.redundant_calls += 1

                        # Primary metric: turns needed to recover after an error.
                        if pending_error_turn is not None and state_changed:
                            metrics.error_recovery_turns += max(0, turn - pending_error_turn)
                            pending_error_turn = None

                    # Strip affordances from prior tool responses to avoid O(n²) context growth.
                    # Only the latest tool response needs the full affordance array.
                    if self.is_gas:
                        self._prune_prior_affordances(messages)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            elif assistant_msg.content:
                messages.append({"role": "assistant", "content": assistant_msg.content})
            else:
                # No tool calls and no content — stuck
                break

            metrics.turns.append(turn_detail)

            # Safety: abort if too many consecutive errors
            if consecutive_errors >= 5:
                break

        if self.is_gas and gas_act_calls > 0:
            metrics.affordance_utilization = gas_in_affordance_calls / gas_act_calls

        metrics.total_turns = turn
        metrics.elapsed_seconds = time.monotonic() - t0
        return metrics

    # -- Anthropic format conversion helpers --

    @staticmethod
    def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
        """Convert OpenAI function-calling tool defs to Anthropic tool format."""
        result = []
        for t in tools:
            fn = t["function"]
            result.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    @staticmethod
    def _openai_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
        """Convert OpenAI messages to Anthropic (system, messages) format.

        Returns (system_prompt, anthropic_messages).
        """
        system = ""
        anthropic_msgs = []
        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                system = msg.get("content", "")
            elif role == "user":
                anthropic_msgs.append({"role": "user", "content": msg.get("content", "")})
            elif role == "assistant":
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", tc.get("function", {}))
                    try:
                        inp = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        inp = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": inp,
                    })
                if content_blocks:
                    anthropic_msgs.append({"role": "assistant", "content": content_blocks})
            elif role == "tool":
                anthropic_msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
        return system, anthropic_msgs

    @staticmethod
    def _anthropic_response_to_openai(response):
        """Convert an Anthropic Message to an OpenAI-like response object.

        Returns a lightweight namespace that matches the fields used in run().
        """
        class _Usage:
            def __init__(self, inp, out):
                self.prompt_tokens = inp
                self.completion_tokens = out

        class _Function:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments

        class _ToolCall:
            def __init__(self, tc_id, function):
                self.id = tc_id
                self.function = function

        class _Message:
            def __init__(self):
                self.content = None
                self.tool_calls = None

            def model_dump(self):
                result = {"role": "assistant"}
                parts = []
                if self.content:
                    result["content"] = self.content
                    parts.append({"type": "text", "text": self.content})
                tool_calls_list = []
                if self.tool_calls:
                    for tc in self.tool_calls:
                        tool_calls_list.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })
                if tool_calls_list:
                    result["tool_calls"] = tool_calls_list
                return result

        class _Choice:
            def __init__(self, message):
                self.message = message

        class _Response:
            def __init__(self, choice, usage):
                self.choices = [choice]
                self.usage = usage

        msg = _Message()
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(_ToolCall(
                    tc_id=block.id,
                    function=_Function(
                        name=block.name,
                        arguments=json.dumps(block.input),
                    ),
                ))

        if text_parts:
            msg.content = "\n".join(text_parts)
        if tool_calls:
            msg.tool_calls = tool_calls

        usage = _Usage(
            inp=response.usage.input_tokens,
            out=response.usage.output_tokens,
        )

        return _Response(_Choice(msg), usage)

    @staticmethod
    def _parse_retry_after(exc) -> float | None:
        """Extract retry-after hint from a rate-limit error message."""
        msg = str(exc)
        # OpenAI: "Please try again in 432ms" or "in 1.3s"
        import re
        m = re.search(r"try again in ([\d.]+)(ms|s)", msg)
        if m:
            val = float(m.group(1))
            return val / 1000 if m.group(2) == "ms" else val
        return None

    def _call_with_retry(self, messages, tools, extra_kwargs):
        """Call LLM with retry logic. Respects rate-limit Retry-After hints."""
        max_attempts = max(1, self.config.max_retries) + 3  # extra headroom for 429s
        for attempt in range(max_attempts):
            try:
                if self.is_anthropic:
                    return self._call_anthropic(messages, tools)
                return self.client.chat.completions.create(
                    model=self.config.model.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    **extra_kwargs,
                )
            except RateLimitError as e:
                if attempt == max_attempts - 1:
                    raise
                wait = self._parse_retry_after(e) or (2 ** attempt)
                wait = max(wait, 1.0) + 0.5  # pad slightly
                time.sleep(wait)
            except (APITimeoutError, InternalServerError) as e:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(2 ** attempt)
            except Exception as e:
                if self.is_anthropic and attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def _call_anthropic(self, messages, tools):
        """Call Anthropic API and return an OpenAI-compatible response object."""
        system, anthropic_msgs = self._openai_messages_to_anthropic(messages)
        anthropic_tools = self._openai_tools_to_anthropic(tools)

        response = self.anthropic_client.messages.create(
            model=self.config.model.model,
            max_tokens=4096,
            system=system,
            messages=anthropic_msgs,
            tools=anthropic_tools,
            tool_choice={"type": "auto"},
        )
        return self._anthropic_response_to_openai(response)
