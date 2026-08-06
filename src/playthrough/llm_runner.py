"""LLM Game Runner — an LLM plays as both Game Runner and PCs.

The LLM reads affordances each turn, decides what action to take (as the PCs),
narrates what happens (as the Game Runner), and the loop continues until the
game completes. This is a pure affordance consumer — the LLM can only do
what the backend says is valid.

Usage:
    python -m playthrough.runner --llm-play --characters iryna chuck
"""

from __future__ import annotations

import json
import re
import time

from openai import APITimeoutError, InternalServerError, OpenAI

from src.gia.compat import JsonGameRuntimeAdapter

from .config import NarrativeBeat

RETRIES = 3

ACTION_DELIMITER = "---ACTION---"


def _get_alive_character_ids(runtime: JsonGameRuntimeAdapter, session_id: str) -> list[str]:
    """Return IDs of alive (not dead) characters in the session."""
    characters = runtime.ctx.db.get_session_characters(session_id)
    return [c.id for c in characters if not c.is_dead]


def _build_system_prompt(character_descriptions: list[dict]) -> str:
    """Build the system prompt with character info baked in."""
    char_blocks = []
    for ch in character_descriptions:
        hooks = "; ".join(ch.get("hooks", []))
        best_stat = max(ch["stats"], key=ch["stats"].get)
        char_blocks.append(
            f"{ch['name']}: {ch['description'][:150]}\n"
            f"  Voice: {hooks}\n"
            f"  Best stat: {best_stat} ({ch['stats'][best_stat]})"
        )
    chars_text = "\n\n".join(char_blocks)

    return f"""\
You narrate EAT THE REICH. Vampire commandos fight through Nazi Paris to kill Hitler.
You are both the Game Runner (narration) and the Players (decisions, dialogue).
Write ONLY in English.

CHARACTERS:
{chars_text}

DECISION RULES (follow strictly):
1. If threats exist at your location, IMMEDIATELY engage_threat. Never switch characters or move first.
2. After EACH combat round resolves, switch to the other character using next_turn before the next engagement.
3. Use each character's BEST stat when building dice pools.
4. When allocating dice: put 2/3 toward objective, rest toward threat. Always put at least 1 die in defense if ENEMY DICE exist.
5. Between scenes: heal injured characters FIRST if blood >= 3, then choose_next_location.
6. Push toward lower sectors: Sector 3 → 2 → 1 → Hitler's broadcast suite.

RESPONSE FORMAT:
Write 2 short paragraphs of narration with character dialogue, then:

{ACTION_DELIMITER}
{{"action": "action_name", "params": {{...}}}}

Copy action names and const param values EXACTLY from the ACTIONS list.

ALLOCATION EXAMPLE (distribute YOUR DICE values):
{ACTION_DELIMITER}
{{"action": "allocate_dice", "params": {{"allocations": {{"objective": [6, 5], "threat": [4], "defense": [4]}}}}}}

The {ACTION_DELIMITER} block is MANDATORY every response.\
"""


def _build_turn_message(
    runtime: JsonGameRuntimeAdapter,
    session_id: str,
    last_result: dict | None = None,
) -> str:
    """Build the per-turn user message with game state + affordances."""
    session = runtime.ctx.get_session(session_id)
    if not session:
        return "Game session not found."

    parts = []
    parts.append(f"PHASE: {session.phase.value}")

    # Active character
    if session.active_character_id:
        char = runtime.ctx.db.get_character(session.active_character_id)
        if char:
            sheet = runtime.ctx.get_character_sheet(char.id)
            parts.append(f"ACTIVE: {char.name}")
            if sheet:
                state = sheet.get("state", {})
                parts.append(f"  Blood: {state.get('blood', 0)}, Stats: {sheet.get('effective_stats', {})}")

    # Scene
    scene = runtime.ctx.get_active_scene(session_id)
    if scene:
        loc = runtime.ctx.get_location_template(session.current_location_id) if session.current_location_id else None
        if loc:
            parts.append(f"LOCATION: {loc.name} — {loc.description[:120]}")
        for obj in scene.active_objectives:
            status = "COMPLETE" if obj.is_completed else f"rating {obj.current_rating}"
            parts.append(f"OBJECTIVE: {obj.name} [{status}]")
        for t in scene.active_threats:
            if not t.is_defeated:
                parts.append(f"THREAT: {t.name} (rating {t.current_rating}, attack {t.current_attack})")

    # Last result
    if last_result:
        data = last_result.get("data", last_result)
        msg = data.get("message", "")
        if msg:
            parts.append(f"RESULT: {msg}")
        for ev in last_result.get("events", []):
            etype = ev.get("type", "")
            edata = ev.get("data", {})
            if etype == "InjuryMarked":
                parts.append(f"EVENT: {edata.get('character')} injured — {edata.get('injury', '')}")
            elif etype == "CharacterDowned":
                parts.append(f"EVENT: {edata.get('character')} DOWNED")
            elif etype == "CharacterDead":
                parts.append(f"EVENT: {edata.get('character')} DEAD")
            elif etype == "ThreatDefeated":
                parts.append(f"EVENT: {edata.get('threat')} defeated!")

        if data.get("player_kept"):
            parts.append(f"YOUR DICE: {data['player_kept']}")
        if data.get("gm_kept"):
            parts.append(f"ENEMY DICE: {data['gm_kept']}")

    # Affordances — filter view actions
    affs_str = runtime.get("session", session_id=session_id)
    affs_data = json.loads(affs_str)
    all_affordances = affs_data.get("affordances", [])
    affordances = [a for a in all_affordances if not a["action"].startswith("view_") and a["action"] != "check_inventory"]

    # Filter out move/location actions when threats are active
    has_threats = scene and any(not t.is_defeated for t in scene.active_threats)
    if has_threats:
        affordances = [a for a in affordances if a["action"] not in ("move_to_location", "choose_next_location")]

    # Phase-specific directive
    phase = session.phase.value
    if phase == "engagement_post_roll":
        parts.append("\n⚠ You MUST allocate_dice now. Distribute YOUR DICE values across objective/threat/defense/feed.")
    elif phase == "exploration" and has_threats:
        parts.append("\n⚠ ENGAGE NOW — threats are active! Use engage_threat immediately. Do NOT switch characters first.")
    elif phase == "engagement_pre_roll":
        parts.append("\n⚠ Build a dice pool now using the active character's BEST stat.")
    elif phase == "between_scenes":
        # Check if any character needs healing
        injured = []
        for cid in _get_alive_character_ids(runtime, session_id):
            sheet = runtime.ctx.get_character_sheet(cid)
            if sheet:
                state = sheet.get("state", {})
                blood = state.get("blood", 0)
                injuries = state.get("injuries", [])
                if injuries and blood >= 3:
                    c = runtime.ctx.db.get_character(cid)
                    if c:
                        injured.append(c.name)
        if injured:
            parts.append(f"\n⚠ Scene complete. HEAL first: {', '.join(injured)} can heal (blood >= 3). Then choose_next_location.")
        else:
            parts.append("\n⚠ Scene complete. choose_next_location to advance.")

    # Character rotation hint — only suggest AFTER a combat round, not before first engagement
    action_names = [a["action"] for a in affordances]
    if (session.active_character_id
            and phase == "exploration"
            and not has_threats
            and "next_turn" in action_names):
        alive_chars = []
        for cid in _get_alive_character_ids(runtime, session_id):
            c = runtime.ctx.db.get_character(cid)
            if c:
                alive_chars.append((cid, c.name))
        if len(alive_chars) > 1:
            other_names = [name for cid, name in alive_chars if cid != session.active_character_id]
            if other_names:
                parts.append(f"\nROTATION: Consider switching to {' or '.join(other_names)} via next_turn.")

    parts.append(f"\nACTIONS:")
    for aff in affordances:
        action = aff["action"]
        desc = aff["description"]
        schema = aff.get("schema", {})
        param_hints = []
        for param, spec in schema.items():
            if isinstance(spec, dict):
                if "const" in spec:
                    param_hints.append(f'{param}="{spec["const"]}"')
                elif "enum" in spec:
                    param_hints.append(f'{param} from {spec["enum"]}')
        hint = f" [{', '.join(param_hints)}]" if param_hints else ""
        parts.append(f"  - {action}{hint}: {desc}")

    return "\n".join(parts)


def _fuzzy_match_action(action: str, valid_actions: list[str]) -> str:
    """Try to match a mangled action name to a valid one."""
    if action in valid_actions:
        return action
    # Try lowercase match
    lower_map = {a.lower().replace("_", ""): a for a in valid_actions}
    normalized = action.lower().replace("_", "").replace("-", "").replace(" ", "")
    if normalized in lower_map:
        return lower_map[normalized]
    # Substring match
    for valid in valid_actions:
        if valid in action or action in valid:
            return valid
    return action


def _parse_action(response_text: str, valid_actions: list[str]) -> tuple[str, str, dict]:
    """Parse narration and action from LLM response.

    Returns (narration, action_name, params).
    """
    action_json = ""
    narration = response_text.strip()

    if ACTION_DELIMITER in response_text:
        parts = response_text.split(ACTION_DELIMITER, 1)
        narration = parts[0].strip()
        action_json = parts[1].strip()
    else:
        # Try to find JSON with "action" key anywhere
        match = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', response_text)
        if not match:
            # Try multiline JSON
            match = re.search(r'\{[^}]*"action"\s*:', response_text, re.DOTALL)
        if match:
            action_json = response_text[match.start():]
            narration = response_text[:match.start()].strip()
        else:
            return narration, "", {}

    # Clean up
    action_json = action_json.strip()
    if action_json.startswith("```"):
        action_json = re.sub(r"^```\w*\n?", "", action_json)
        action_json = re.sub(r"\n?```\s*$", "", action_json)
        action_json = action_json.strip()

    # Try to extract JSON object
    try:
        data = json.loads(action_json)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', action_json, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return narration, "", {}
        else:
            return narration, "", {}

    action = data.get("action", "")
    params = data.get("params", {})

    # Fuzzy match action name
    action = _fuzzy_match_action(action, valid_actions)

    return narration, action, params


class LLMGameRunner:
    """Runs a full game with an LLM as both Game Runner and PCs."""

    def __init__(
        self,
        runtime: JsonGameRuntimeAdapter,
        client: OpenAI,
        characters: list[str],
        model: str = "qwen3.5:9b",
        timeout: float = 300.0,
        ollama: bool = False,
    ):
        self.runtime = runtime
        self.client = client
        self.model = model
        self.timeout = timeout
        self.ollama = ollama
        self.characters = characters
        self.session_id = runtime.default_session_id
        self.beats: list[NarrativeBeat] = []
        self._messages: list[dict] = []
        self._max_turns = 200

    def run(self) -> list[NarrativeBeat]:
        """Run the full game. Returns narrative beats."""
        self._setup()

        # Build system prompt
        char_descriptions = []
        for cid in self.characters:
            template = self.runtime.ctx.get_character_template(cid)
            if template:
                char_descriptions.append(template.model_dump())
        system_prompt = _build_system_prompt(char_descriptions)
        self._messages = [{"role": "system", "content": system_prompt}]

        # Game loop
        last_result = None
        turn = 0
        consecutive_failures = 0
        while turn < self._max_turns:
            turn += 1
            phase = self._get_phase()

            if phase == "mission_complete":
                self._narrate_epilogue()
                break

            # Get valid actions for fuzzy matching
            valid_actions = self._get_valid_actions()

            # Build turn context
            user_msg = _build_turn_message(self.runtime, self.session_id, last_result)
            self._messages.append({"role": "user", "content": user_msg})

            # Get LLM response
            print(f"  [Turn {turn}] Phase: {phase} — requesting LLM...")
            t0 = time.monotonic()
            response_text = self._call_llm()
            elapsed = time.monotonic() - t0
            self._messages.append({"role": "assistant", "content": response_text})

            # Parse narration + action
            narration, action, params = _parse_action(response_text, valid_actions)

            if not action:
                print(f"  [Turn {turn}] No action parsed — nudging...")
                # Give it the exact list and a concrete example
                first_action = valid_actions[0] if valid_actions else "engage_threat"
                nudge = (
                    f"Pick one of these actions: {', '.join(valid_actions)}\n\n"
                    f"{ACTION_DELIMITER}\n"
                    f'{{"action": "{first_action}", "params": {{}}}}'
                    f"\n\nReplace with your chosen action."
                )
                self._messages.append({"role": "user", "content": nudge})
                response_text = self._call_llm()
                self._messages.append({"role": "assistant", "content": response_text})
                extra_narration, action, params = _parse_action(response_text, valid_actions)
                if extra_narration and narration:
                    narration = f"{narration}\n\n{extra_narration}"
                elif extra_narration:
                    narration = extra_narration

            if not action:
                consecutive_failures += 1
                print(f"  [Turn {turn}] Still no action (failure {consecutive_failures}/5)")
                if consecutive_failures >= 5:
                    print("  Too many failures — aborting")
                    break
                continue

            consecutive_failures = 0

            # Execute the action
            is_view = action.startswith("view_")
            try:
                result_str = self.runtime.act(action, json.dumps(params), self.session_id)
                last_result = json.loads(result_str)
                if "error" in last_result and not last_result.get("data"):
                    err = last_result["error"]
                    print(f"  [Turn {turn}] {action} ERROR: {err[:80]} ({elapsed:.1f}s)")
                    last_result = {"data": {"message": f"ERROR: {err}. Pick a different action."}}
                    continue
                result_msg = last_result.get("data", last_result).get("message", "")
                print(f"  [Turn {turn}] {action} → {result_msg[:80]} ({elapsed:.1f}s)")
            except Exception as e:
                print(f"  [Turn {turn}] EXCEPTION: {action} — {e}")
                last_result = {"data": {"message": f"ERROR: {e}. Pick a different action."}}
                continue

            # Attach LLM reasoning to the decision record
            self.runtime.ctx.db.update_last_decision_llm_context(
                self.session_id,
                narration=narration,
                turn_context=user_msg,
            )

            # Record beat
            if narration and not is_view:
                beat_type = self._classify_beat(action, last_result)
                self.beats.append(NarrativeBeat(
                    type=beat_type,
                    data=last_result.get("data", last_result),
                    events=last_result.get("events", []),
                    narration=narration,
                ))

        return self.beats

    def _setup(self):
        """Programmatic setup — select characters and start mission."""
        for cid in self.characters:
            self.runtime.act("select_character", json.dumps({"template_id": cid}), self.session_id)
        result_str = self.runtime.act("start_mission", "{}", self.session_id)
        result = json.loads(result_str)
        self.beats.append(NarrativeBeat(
            type="scene_arrival",
            data=result.get("data", result),
        ))

    def _narrate_epilogue(self):
        """Final narration for game end."""
        result_str = self.runtime.act("view_epilogue", "{}", self.session_id)
        result = json.loads(result_str)
        data = result.get("data", result)

        survivors = ", ".join(data.get("survivors", [])) or "None"
        fallen = ", ".join(data.get("fallen", [])) or "None"
        user_msg = (
            f"MISSION OVER. Survivors: {survivors}. Fallen: {fallen}.\n"
            "Write the epilogue — honor the fallen, close the story."
        )
        self._messages.append({"role": "user", "content": user_msg})
        response_text = self._call_llm()
        narration = response_text.split(ACTION_DELIMITER)[0].strip() if ACTION_DELIMITER in response_text else response_text.strip()

        self.beats.append(NarrativeBeat(type="epilogue", data=data, narration=narration))
        print(f"  [Epilogue] Survivors: {survivors}")

    def _get_valid_actions(self) -> list[str]:
        """Get list of valid action names for current state."""
        affs_str = self.runtime.get("session", session_id=self.session_id)
        affs_data = json.loads(affs_str)
        return list({a["action"] for a in affs_data.get("affordances", [])})

    def _trim_history(self):
        """Keep conversation history manageable."""
        max_exchanges = 8
        if len(self._messages) <= 1 + max_exchanges * 2:
            return
        self._messages = [self._messages[0]] + self._messages[-(max_exchanges * 2):]

    def _call_llm(self) -> str:
        """Call the LLM with retry logic."""
        self._trim_history()
        for attempt in range(RETRIES):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": self._messages,
                    "timeout": self.timeout,
                }
                if self.ollama:
                    kwargs["extra_body"] = {"options": {"num_ctx": 8192}}
                else:
                    kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                response = self.client.chat.completions.create(**kwargs)
                text = response.choices[0].message.content or ""
                # Strip thinking blocks (Qwen3, DeepSeek-R1, etc.)
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
                # Strip non-ASCII characters (Chinese char leaks from Qwen)
                text = re.sub(r"[^\x00-\x7F]+", "", text).strip()
                return text
            except (InternalServerError, APITimeoutError):
                if attempt == RETRIES - 1:
                    raise
                print(f"    Retry ({attempt + 1}/{RETRIES})...")
                time.sleep(2)
        return ""

    def _get_phase(self) -> str:
        session = self.runtime.ctx.get_session(self.session_id)
        return session.phase.value if session else "mission_complete"

    def _classify_beat(self, action: str, result: dict) -> str:
        """Map action + events to beat type."""
        events = result.get("events", [])
        for ev in events:
            if ev.get("type") == "CharacterDead":
                return "death"
            if ev.get("type") in ("CharacterDowned", "InjuryMarked"):
                return "injury"
        data = result.get("data", result)
        if data.get("scene_completed"):
            return "scene_complete"
        if action in ("choose_next_location", "move_to_location"):
            return "advance"
        if action == "start_mission":
            return "scene_arrival"
        if action == "trigger_last_stand":
            return "death"
        if action == "view_epilogue":
            return "epilogue"
        return "combat_round"
