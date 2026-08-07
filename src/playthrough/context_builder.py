"""ContextBuilder — queries the graph to build focused narrative context per beat."""

from __future__ import annotations

from havoc_domain.context import GameContext

from .config import NarrativeBeat


class ContextBuilder:
    """Enriches NarrativeBeats with graph-derived context for the narrator."""

    def __init__(self, ctx: GameContext):
        self.ctx = ctx
        self._squad_context: str = ""  # cached character voice descriptions

    def enrich(self, beats: list[NarrativeBeat], session_id: str = "") -> None:
        """Add context strings to each beat in place."""
        if session_id:
            self._squad_context = self._build_squad_context(session_id)
        for beat in beats:
            beat.context = self._build_context(beat)

    def _build_squad_context(self, session_id: str) -> str:
        """Build character voice/personality block from session characters."""
        chars = self.ctx.db.get_session_characters(session_id)
        lines = ["CHARACTER VOICES (use these for dialogue):"]
        for ch in chars:
            template = self.ctx.get_character_template(ch.template_id)
            if not template:
                continue
            hooks = "; ".join(template.hooks) if template.hooks else ""
            lines.append(f"  {template.name}: {template.description[:200]}")
            if hooks:
                lines.append(f"    Voice/personality: {hooks}")
            lines.append(f"    Last stand: {template.last_stand}")
        return "\n".join(lines)

    def _build_context(self, beat: NarrativeBeat) -> str:
        parts = []
        if self._squad_context:
            parts.append(self._squad_context)
            parts.append("")

        if beat.type == "scene_arrival":
            parts.append(self._scene_arrival(beat.data))
        elif beat.type == "combat_round" or beat.type == "injury":
            parts.append(self._combat_round(beat.data, beat.events))
        elif beat.type == "scene_complete":
            parts.append(self._scene_complete(beat.data))
        elif beat.type == "death":
            parts.append(self._death_scene(beat.data))
        elif beat.type == "advance":
            parts.append(self._advance(beat.data))
        elif beat.type == "epilogue":
            parts.append(self._epilogue(beat.data))

        return "\n".join(parts)

    def _scene_arrival(self, data: dict) -> str:
        lines = []
        loc_name = data.get("location", "unknown")
        lines.append(f"LOCATION: {loc_name}")
        lines.append(f"DESCRIPTION: {data.get('location_description', '')}")
        lines.append(f"OBJECTIVE: {data.get('objective', '?')} (rating {data.get('objective_rating', '?')})")

        threats = data.get("threats", [])
        if threats:
            lines.append("THREATS:")
            for t in threats:
                enemy = self.ctx.get_enemy_template(t.get("name", "").lower().replace(" ", "_").replace("-", "_"))
                desc = ""
                if enemy:
                    desc = f" — {enemy.description[:120]}"
                lines.append(f"  - {t['name']} (rating {t.get('rating', '?')}, attack {t.get('attack', '?')}){desc}")

        # Character info
        if data.get("active_character"):
            lines.append(f"ACTIVE CHARACTER: {data['active_character']}")

        return "\n".join(lines)

    def _combat_round(self, data: dict, events: list[dict]) -> str:
        lines = []
        lines.append(f"ENGAGING: {data.get('threat', '?')}")
        lines.append(f"STAT USED: {data.get('stat', '?').upper()}")
        lines.append(f"PLAYER DICE KEPT: {data.get('player_kept', [])}")
        lines.append(f"GM DICE KEPT: {data.get('gm_kept', [])}")

        alloc = data.get("allocations", {})
        if alloc:
            parts = [f"{k}: {v}" for k, v in alloc.items() if v]
            lines.append(f"ALLOCATIONS: {', '.join(parts)}")

        result = data.get("result", {})
        scene_status = result.get("scene_status", {})
        if scene_status:
            objs = scene_status.get("objectives", [])
            for o in objs:
                lines.append(f"OBJECTIVE: {o['name']} — rating {o['rating']}{' COMPLETE' if o.get('completed') else ''}")
            for t in scene_status.get("threats", []):
                lines.append(f"THREAT: {t['name']} — rating {t['rating']}{' DEFEATED' if t.get('defeated') else ''}")

        for ev in events:
            etype = ev.get("type", "")
            edata = ev.get("data", {})
            if etype == "InjuryMarked":
                lines.append(f"INJURY: {edata.get('character')} takes {edata.get('severity')} injury — {edata.get('injury', '')}")
            elif etype == "CharacterDowned":
                lines.append(f"DOWNED: {edata.get('character')} — {edata.get('injury', '')}")
            elif etype == "ThreatDefeated":
                lines.append(f"THREAT DEFEATED: {edata.get('threat')}")
            elif etype == "ObjectiveCompleted":
                lines.append(f"OBJECTIVE COMPLETED: {edata.get('objective')}")

        return "\n".join(lines)

    def _scene_complete(self, data: dict) -> str:
        lines = [f"SCENE COMPLETE: {data.get('message', '')}"]
        scene_status = data.get("scene_status", {})
        if scene_status:
            for t in scene_status.get("threats", []):
                status = "defeated" if t.get("defeated") else f"rating {t['rating']}"
                lines.append(f"  {t['name']}: {status}")
        return "\n".join(lines)

    def _death_scene(self, data: dict) -> str:
        lines = [f"DEATH/LAST STAND: {data.get('message', '')}"]
        if data.get("results"):
            total = data.get("total_successes", 0)
            lines.append(f"Last stand dice: {data['results']} ({total} successes)")
        return "\n".join(lines)

    def _advance(self, data: dict) -> str:
        lines = [f"ADVANCING TO: {data.get('location', '?')}"]
        lines.append(f"DESCRIPTION: {data.get('location_description', '')}")
        lines.append(f"OBJECTIVE: {data.get('objective', '?')} (rating {data.get('objective_rating', '?')})")
        threats = data.get("threats", [])
        for t in threats:
            lines.append(f"NEW THREAT: {t['name']} (rating {t.get('rating', '?')})")
        return "\n".join(lines)

    def _epilogue(self, data: dict) -> str:
        lines = ["EPILOGUE"]
        lines.append(data.get("message", ""))
        survivors = data.get("survivors", [])
        fallen = data.get("fallen", [])
        if survivors:
            lines.append(f"SURVIVORS: {', '.join(survivors)}")
        if fallen:
            lines.append(f"FALLEN: {', '.join(fallen)}")
        return "\n".join(lines)
