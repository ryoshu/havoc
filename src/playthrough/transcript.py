"""TranscriptWriter — assembles beats into markdown and JSON output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import NarrativeBeat

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "playthroughs"


class TranscriptWriter:
    """Writes playthrough transcripts in markdown and JSON formats."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or LOG_DIR

    def write(self, beats: list[NarrativeBeat], characters: list[str]) -> tuple[Path, Path]:
        """Write markdown, JSON, and combined log. Returns (md_path, json_path)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        md_path = self.output_dir / f"{ts}_playthrough.md"
        json_path = self.output_dir / f"{ts}_playthrough.json"
        log_path = self.output_dir / f"{ts}_log.md"

        self._write_markdown(beats, characters, md_path)
        self._write_json(beats, characters, json_path)
        self._write_log(beats, characters, log_path)

        return md_path, json_path

    def _write_markdown(self, beats: list[NarrativeBeat], characters: list[str], path: Path):
        lines = []
        lines.append("# EAT THE REICH — Playthrough")
        lines.append("")
        lines.append(f"**Squad:** {', '.join(characters)}")
        lines.append(f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        scene_num = 0
        for beat in beats:
            if beat.type == "scene_arrival":
                scene_num += 1
                loc = beat.data.get("location", "Unknown")
                lines.append(f"## Scene {scene_num}: {loc}")
                lines.append("")
            elif beat.type == "advance":
                scene_num += 1
                loc = beat.data.get("location", "Unknown")
                lines.append(f"## Scene {scene_num}: {loc}")
                lines.append("")
            elif beat.type == "epilogue":
                lines.append("## Epilogue")
                lines.append("")

            if beat.narration:
                lines.append(beat.narration)
                lines.append("")
            else:
                # Mechanical summary when no narration
                lines.append(f"*[{beat.type}]*")
                lines.append("")
                if beat.type == "combat_round" or beat.type == "injury":
                    result = beat.data.get("result", {})
                    lines.append(f"> {result.get('message', '')}")
                elif beat.type == "scene_complete":
                    lines.append(f"> {beat.data.get('message', '')}")
                elif beat.type == "death":
                    lines.append(f"> {beat.data.get('message', '')}")
                elif beat.type == "epilogue":
                    lines.append(f"> {beat.data.get('message', '')}")
                    survivors = beat.data.get("survivors", [])
                    fallen = beat.data.get("fallen", [])
                    if survivors:
                        lines.append(f"> Survivors: {', '.join(survivors)}")
                    if fallen:
                        lines.append(f"> Fallen: {', '.join(fallen)}")
                lines.append("")

        lines.append("---")
        lines.append(f"*{len(beats)} narrative beats recorded.*")
        path.write_text("\n".join(lines))

    def _write_log(self, beats: list[NarrativeBeat], characters: list[str], path: Path):
        """Combined narrative + mechanics log — the full picture."""
        lines = []
        lines.append("# EAT THE REICH — Playthrough Log")
        lines.append("")
        lines.append(f"**Squad:** {', '.join(characters)}")
        lines.append(f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        scene_num = 0
        for i, beat in enumerate(beats):
            data = beat.data

            # Scene headers
            if beat.type in ("scene_arrival", "advance"):
                scene_num += 1
                loc = data.get("location", "Unknown")
                lines.append("---")
                lines.append("")
                lines.append(f"## Scene {scene_num}: {loc}")
                lines.append("")
                if beat.type == "scene_arrival":
                    desc = data.get("location_description", "")
                    obj = data.get("objective", "")
                    rating = data.get("objective_rating", "")
                    threats = data.get("threats", [])
                    if desc:
                        lines.append(f"*{desc}*")
                        lines.append("")
                    if obj:
                        lines.append(f"**Objective:** {obj} (rating {rating})")
                    if threats:
                        threat_strs = [f"{t['name']} (rating {t.get('rating', '?')}, attack {t.get('attack', '?')})" for t in threats]
                        lines.append(f"**Threats:** {', '.join(threat_strs)}")
                    lines.append("")
                if beat.narration:
                    lines.append(beat.narration)
                    lines.append("")
                continue

            if beat.type == "epilogue":
                lines.append("---")
                lines.append("")
                lines.append("## Epilogue")
                lines.append("")
                survivors = data.get("survivors", [])
                fallen = data.get("fallen", [])
                lines.append(f"**Survivors:** {', '.join(survivors) or 'None'}")
                lines.append(f"**Fallen:** {', '.join(fallen) or 'None'}")
                lines.append("")
                if beat.narration:
                    lines.append(beat.narration)
                    lines.append("")
                continue

            # All other beats: narration first, then mechanics block
            if beat.narration:
                lines.append(beat.narration)
                lines.append("")

            # Mechanics
            mechanics = self._format_mechanics(beat)
            if mechanics:
                lines.append(mechanics)
                lines.append("")

        lines.append("---")
        lines.append(f"*{len(beats)} beats recorded.*")
        path.write_text("\n".join(lines))

    def _format_mechanics(self, beat: NarrativeBeat) -> str:
        """Format the mechanical summary for a beat as a blockquote."""
        data = beat.data
        parts = []

        msg = data.get("message", "")
        if msg:
            parts.append(msg)

        # Dice kept (only show if present — the message already says the stat/pool)
        player_kept = data.get("player_kept", [])
        gm_kept = data.get("gm_kept", [])
        if player_kept or gm_kept:
            dice_str = f"Kept {player_kept}"
            if gm_kept:
                dice_str += f" vs enemy {gm_kept}"
            parts.append(dice_str)

        # Pool breakdown extras (only if equipment/ability/bonus contributed)
        pool = data.get("pool_breakdown", {})
        if pool:
            extras = []
            if pool.get("equipment"):
                extras.append(f"equipment +{pool['equipment']}")
            if pool.get("ability"):
                extras.append(f"ability +{pool['ability']}")
            if pool.get("bonus"):
                extras.append(f"bonus +{pool['bonus']}")
            if extras:
                parts.append(f"Pool: {', '.join(extras)}")

        # Threat info on engagement start
        threat = data.get("threat", "")
        if threat and not data.get("stat"):
            if isinstance(threat, dict):
                parts.append(f"vs {threat['name']} (rating {threat.get('rating', '?')}, attack {threat.get('attack', '?')})")
            else:
                parts.append(f"vs {threat}")

        # Scene status
        scene_status = data.get("scene_status", {})
        if scene_status:
            obj_done = scene_status.get("objective_complete", False)
            threats_left = scene_status.get("threats_remaining", 0)
            if obj_done:
                parts.append("Objective complete!")
            if threats_left is not None:
                parts.append(f"Threats remaining: {threats_left}")

        # Events
        for ev in beat.events:
            etype = ev.get("type", "")
            edata = ev.get("data", {})
            if etype == "InjuryMarked":
                parts.append(f"INJURY: {edata.get('character', '?')} — {edata.get('injury', '?')} ({edata.get('severity', '')})")
            elif etype == "CharacterDowned":
                parts.append(f"DOWNED: {edata.get('character', '?')}")
            elif etype == "CharacterDead":
                parts.append(f"DEAD: {edata.get('character', '?')}")
            elif etype == "ThreatDefeated":
                parts.append(f"DEFEATED: {edata.get('threat', '?')}")
            elif etype == "ObjectiveCompleted":
                parts.append(f"OBJECTIVE COMPLETE: {edata.get('objective', '?')}")

        if not parts:
            return ""

        return "> " + "  \n> ".join(parts)

    def _write_json(self, beats: list[NarrativeBeat], characters: list[str], path: Path):
        data = {
            "characters": characters,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "beats": [
                {
                    "type": b.type,
                    "data": b.data,
                    "events": b.events,
                    "context": b.context,
                    "narration": b.narration,
                }
                for b in beats
            ],
        }
        path.write_text(json.dumps(data, indent=2))
