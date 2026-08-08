"""Director — deterministic state machine that plays the game without an LLM.

The Director is a first-party GAS 2.0 consumer: it reads contextual
capabilities, selects a capability ID, and sends only ``capability_id`` plus
typed input to ``act``, via a ``gas_protocol.service.GasService`` built over
``GameRuntime`` (``havoc_server.runtime.build_gas_service``). It also keeps a direct
handle on the ``GameRuntime`` itself for phase/character bookkeeping reads
(``.ctx``) that are legitimately Havoc-specific and outside the
domain-neutral GAS surface.
"""

from __future__ import annotations

from havoc_server.runtime import GameRuntime, build_gas_service

from .config import NarrativeBeat, PlaythroughStrategy


class Director:
    """Plays a full game mechanically, collecting narrative beats."""

    def __init__(self, runtime: GameRuntime, session_id: str, strategy: PlaythroughStrategy):
        self.runtime = runtime
        self.service = build_gas_service(runtime)
        self.strategy = strategy
        self.session_id = session_id
        self.beats: list[NarrativeBeat] = []
        self._char_index = 0  # for rotating characters
        self._visited_locations: set[str] = set()
        self._locations_advanced = 0
        self._idempotency_counter = 0

    def run_full_game(self) -> list[NarrativeBeat]:
        """Run setup, then scenes until mission_complete or TPK."""
        self._setup()
        while True:
            phase = self._get_phase()
            if phase == "mission_complete":
                self._epilogue()
                break
            if phase == "between_scenes":
                if not self._between_scenes():
                    break  # no more locations
            elif phase in ("exploration", "engagement_pre_roll", "engagement_post_roll"):
                self._play_scene()
            elif phase == "last_stand":
                self._handle_last_stand()
            else:
                break  # unexpected phase
        return self.beats

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self):
        for template_id in self.strategy.characters:
            self._act("select_character", {"template_id": template_id})
        result = self._act("start_mission")
        data = result.get("data", result)
        self.beats.append(NarrativeBeat(
            type="scene_arrival",
            data=data,
        ))
        # Track starting location
        session = self.runtime.ctx.get_session(self.session_id)
        if session and session.current_location_id:
            self._visited_locations.add(session.current_location_id)

    # ------------------------------------------------------------------
    # Scene loop
    # ------------------------------------------------------------------

    def _play_scene(self):
        max_rounds = 100
        for _ in range(max_rounds):
            phase = self._get_phase()
            if phase == "between_scenes" or phase == "mission_complete":
                return
            if phase == "last_stand":
                self._handle_last_stand()
                if self._all_dead():
                    return
                continue

            # Rotate characters if multiple alive
            self._maybe_switch_character()

            # Engage → roll → allocate
            threat_name = self._pick_threat()
            if not threat_name:
                return  # no threats and objective not complete — shouldn't happen
            self._act("engage_threat", {"threat_name": threat_name})

            stat = self._pick_best_stat()
            roll_result = self._act("build_dice_pool", {"stat": stat})
            roll_data = roll_result.get("data", roll_result)
            player_kept = roll_data.get("player_kept", [])
            gm_kept = roll_data.get("gm_kept", [])

            allocations = self._compute_allocations(player_kept, gm_kept)
            alloc_result = self._act("allocate_dice", {"allocations": allocations})
            alloc_data = alloc_result.get("data", alloc_result)
            events = alloc_result.get("events", [])

            beat = NarrativeBeat(
                type="combat_round",
                data={
                    "threat": threat_name,
                    "stat": stat,
                    "player_kept": player_kept,
                    "gm_kept": gm_kept,
                    "allocations": allocations,
                    "result": alloc_data,
                },
                events=events,
            )

            # Check for injuries/death in events
            for ev in events:
                if ev.get("type") in ("InjuryMarked", "CharacterDowned"):
                    beat.type = "injury"
                if ev.get("type") == "CharacterDead":
                    beat.type = "death"

            self.beats.append(beat)

            if alloc_data.get("scene_completed"):
                self.beats.append(NarrativeBeat(
                    type="scene_complete",
                    data=alloc_data,
                    events=events,
                ))
                return

    # ------------------------------------------------------------------
    # Between scenes
    # ------------------------------------------------------------------

    def _between_scenes(self) -> bool:
        """Heal if possible, then advance. Returns False if no next location."""
        self._heal_if_possible()
        location_id = self._pick_next_location()
        if not location_id:
            self._epilogue()
            return False
        self._visited_locations.add(location_id)
        self._locations_advanced += 1
        result = self._act("choose_next_location", {"location_id": location_id})
        self.beats.append(NarrativeBeat(
            type="advance",
            data=result.get("data", result),
        ))
        return True

    def _heal_if_possible(self):
        """Spend blood to heal injured characters between scenes."""
        commands = self._get_commands()
        for command in commands:
            if command["command"] == "heal":
                schema = self._schema_properties(command.get("input_schema", {}))
                char_id = schema.get("character_id", {}).get("const")
                cats = schema.get("category", {}).get("enum", [])
                if char_id and cats:
                    self._act("heal", {"character_id": char_id, "category": cats[0]})

    # ------------------------------------------------------------------
    # Last stand
    # ------------------------------------------------------------------

    def _handle_last_stand(self):
        result = self._act("trigger_last_stand")
        self.beats.append(NarrativeBeat(
            type="death",
            data=result.get("data", result),
        ))

    # ------------------------------------------------------------------
    # Epilogue
    # ------------------------------------------------------------------

    def _epilogue(self):
        result = self._act("view_epilogue")
        self.beats.append(NarrativeBeat(
            type="epilogue",
            data=result.get("data", result),
        ))

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    def _pick_threat(self) -> str | None:
        """Pick the highest-attack active threat from affordances."""
        commands = self._get_commands()
        threats = [a for a in commands if a["command"] == "engage_threat"]
        if not threats:
            return None
        # Pick highest rating from schema const
        schema = self._schema_properties(threats[0].get("input_schema", {}))
        return schema.get("threat_name", {}).get("const", "")

    def _pick_best_stat(self) -> str:
        """Pick the character's best stat, or the configured preference."""
        if self.strategy.stat_preference != "best":
            return self.strategy.stat_preference

        session = self.runtime.ctx.get_session(self.session_id)
        if not session or not session.active_character_id:
            return "brawl"
        char = self.runtime.ctx.db.get_character(session.active_character_id)
        if not char:
            return "brawl"
        template = self.runtime.ctx.get_character_template(char.template_id)
        if not template:
            return "brawl"

        sheet = self.runtime.ctx.get_character_sheet(char.id)
        stats = sheet["effective_stats"] if sheet else template.stats
        return max(stats, key=stats.get)

    def _compute_allocations(self, player_kept: list[int], gm_kept: list[int]) -> dict:
        """Allocate dice using the configured strategy."""
        if not player_kept:
            return {}

        sorted_dice = sorted(player_kept, reverse=True)

        if self.strategy.allocation_strategy == "balanced":
            obj_count = max(1, len(sorted_dice) // 2)
        else:  # objective_first
            obj_count = max(1, (len(sorted_dice) * 2 + 2) // 3)  # ~67% to objective

        alloc: dict[str, list[int]] = {"objective": sorted_dice[:obj_count]}
        remaining = sorted_dice[obj_count:]

        # Defense if GM has kept dice
        if gm_kept and remaining:
            alloc["defense"] = [remaining.pop(0)]

        # Rest to threat
        if remaining:
            alloc["threat"] = remaining

        return alloc

    def _pick_next_location(self) -> str | None:
        """Pick next location from affordances (prefer unvisited, then lower sector)."""
        commands = self._get_commands()
        locations = [a for a in commands if a["command"] == "choose_next_location"]
        if not locations:
            return None

        # Prefer unvisited locations
        for loc in locations:
            schema = self._schema_properties(loc.get("input_schema", {}))
            loc_id = schema.get("location_id", {}).get("const", "")
            if loc_id and loc_id not in self._visited_locations:
                return loc_id

        # All visited — pick first (will loop, but that's the map)
        schema = self._schema_properties(locations[0].get("input_schema", {}))
        return schema.get("location_id", {}).get("const")

    def _maybe_switch_character(self):
        """Rotate to next alive character."""
        session = self.runtime.ctx.get_session(self.session_id)
        if not session:
            return
        chars = self.runtime.ctx.db.get_session_characters(self.session_id)
        alive = [c for c in chars if not c.is_dead and not c.is_downed]
        if len(alive) <= 1:
            return

        self._char_index = (self._char_index + 1) % len(alive)
        target = alive[self._char_index]
        if target.id != session.active_character_id:
            self._act("next_turn", {"character_id": target.id})

    # ------------------------------------------------------------------
    # Runtime helpers
    # ------------------------------------------------------------------

    def _act(self, action: str, params: dict | None = None) -> dict:
        """Select a current capability and execute it through GAS 2.0."""
        state = self.service.get(f"gia://session/{self.session_id}")
        values = params or {}
        candidates = [command for command in state.commands if command.command == action]
        for candidate in candidates:
            if self._schema_accepts(candidate.input_schema, values):
                self._idempotency_counter += 1
                result = self.service.act(
                    candidate.id,
                    state.state_revision,
                    values,
                    f"director-{self._idempotency_counter}",
                    session_id=self.session_id,
                )
                return result.model_dump(mode="json")
        raise RuntimeError(f"No current GAS capability accepts {action} with {values!r}.")

    @staticmethod
    def _schema_accepts(schema: dict, values: dict) -> bool:
        properties = Director._schema_properties(schema)
        for name, value in values.items():
            rule = properties.get(name, {})
            if "const" in rule and rule["const"] != value:
                return False
            if "enum" in rule and value not in rule["enum"]:
                return False
        return True

    @staticmethod
    def _schema_properties(schema: dict) -> dict:
        return schema.get("properties", schema)

    def _get_phase(self) -> str:
        session = self.runtime.ctx.get_session(self.session_id)
        return session.phase.value if session else "mission_complete"

    def _get_commands(self) -> list[dict]:
        result = self.service.get(f"gia://session/{self.session_id}")
        return [command.model_dump(mode="json") for command in result.commands]

    def _all_dead(self) -> bool:
        chars = self.runtime.ctx.db.get_session_characters(self.session_id)
        return all(c.is_dead for c in chars)
