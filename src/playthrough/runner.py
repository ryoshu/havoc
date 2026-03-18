"""Runner — orchestrates Director, ContextBuilder, Narrator, and TranscriptWriter.

Usage:
    python -m playthrough.runner --characters iryna chuck
    python -m playthrough.runner --characters iryna chuck astrid --no-narrate
    python -m playthrough.runner --characters iryna chuck --stateful
    python -m playthrough.runner --characters iryna chuck --stat brawl
    python -m playthrough.runner --characters iryna chuck --llm-play
"""

from __future__ import annotations

import argparse
import os
import time

from openai import OpenAI

from src.gia.server import GameRuntime

from .config import PlaythroughStrategy
from .context_builder import ContextBuilder
from .director import Director
from .narrator import Narrator
from .transcript import TranscriptWriter


def main():
    parser = argparse.ArgumentParser(description="Run an automated EAT THE REICH playthrough")
    parser.add_argument("--characters", nargs="+", default=["iryna", "chuck"],
                        help="Character template IDs to select")
    parser.add_argument("--stat", default="best",
                        help="Stat preference: 'best' or a specific stat name")
    parser.add_argument("--allocation", default="objective_first",
                        choices=["objective_first", "balanced"],
                        help="Dice allocation strategy")
    parser.add_argument("--llm-play", action="store_true",
                        help="LLM plays as both Game Runner and PCs (full agent mode)")
    parser.add_argument("--no-narrate", action="store_true",
                        help="Skip LLM narration (mechanical playthrough only)")
    parser.add_argument("--stateful", action="store_true",
                        help="Use stateful narrator (accumulates prior narration for continuity)")
    parser.add_argument("--model", default="qwen3.5:9b",
                        help="LLM model for narration")
    deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")
    default_url = "https://api.deepinfra.com/v1/openai" if deepinfra_key else "http://localhost:11434/v1"
    default_key = deepinfra_key or "ollama"
    parser.add_argument("--api-url", default=default_url,
                        help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", default=default_key,
                        help="API key (env: DEEPINFRA_API_KEY, default: 'ollama' for local)")
    parser.add_argument("--db", default=":memory:",
                        help="SQLite database path (default: in-memory)")
    parser.add_argument("--max-beats", type=int, default=0,
                        help="Max beats to narrate (0=all, useful for testing)")
    args = parser.parse_args()

    # --- LLM Play mode: LLM is both Game Runner and PCs ---
    if args.llm_play:
        from datetime import datetime, timezone
        from pathlib import Path

        from .llm_runner import LLMGameRunner

        # Default to file-based DB so decision traces persist
        db_path = args.db
        if db_path == ":memory:":
            log_dir = Path("logs/playthroughs")
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            db_path = str(log_dir / f"{ts}_decisions.db")

        print(f"Squad: {', '.join(args.characters)}")
        print(f"Mode: LLM Play (agent drives decisions + narration)")
        print(f"Decision DB: {db_path}")
        print()

        t0 = time.monotonic()
        runtime = GameRuntime(db_path=db_path)
        client = OpenAI(base_url=args.api_url, api_key=args.api_key, timeout=300.0)

        is_ollama = "localhost" in args.api_url or "127.0.0.1" in args.api_url
        runner = LLMGameRunner(
            runtime=runtime,
            client=client,
            characters=args.characters,
            model=args.model,
            ollama=is_ollama,
        )
        beats = runner.run()

        writer = TranscriptWriter()
        md_path, json_path = writer.write(beats, args.characters)

        n_decisions = len(runtime.ctx.db.get_session_decisions(runtime.default_session_id))
        print(f"\nTotal: {time.monotonic() - t0:.1f}s ({len(beats)} beats, {n_decisions} decisions)")
        print(f"Markdown: {md_path}")
        print(f"JSON:     {json_path}")
        print(f"Decisions: {db_path}")
        return

    # --- Director + Narrator mode ---
    strategy = PlaythroughStrategy(
        characters=args.characters,
        stat_preference=args.stat,
        allocation_strategy=args.allocation,
    )

    print(f"Squad: {', '.join(strategy.characters)}")
    print(f"Strategy: stat={strategy.stat_preference}, allocation={strategy.allocation_strategy}")
    print(f"Narrator: {'stateful' if args.stateful else 'stateless' if not args.no_narrate else 'disabled'}")
    print()

    # --- Phase 1: Director plays the game ---
    t0 = time.monotonic()
    runtime = GameRuntime(db_path=args.db)
    director = Director(runtime, strategy)
    beats = director.run_full_game()
    director_time = time.monotonic() - t0

    print(f"Director: {len(beats)} beats in {director_time:.1f}s")
    for b in beats:
        print(f"  [{b.type}] {_beat_summary(b)}")
    print()

    # --- Phase 2: Enrich with graph context ---
    builder = ContextBuilder(runtime.ctx)
    builder.enrich(beats, session_id=runtime.default_session_id)

    # --- Phase 3: Narrate (optional) ---
    narrator_time = 0.0
    if not args.no_narrate:
        t1 = time.monotonic()
        timeout = 300.0 if args.stateful else 180.0
        client = OpenAI(base_url=args.api_url, api_key=args.api_key, timeout=timeout)
        narrator = Narrator(client, model=args.model, stateful=args.stateful)
        narrator.narrate_all(beats, max_beats=args.max_beats)
        narrator_time = time.monotonic() - t1
        print(f"Narrator: {narrator_time:.1f}s ({'stateful' if args.stateful else 'stateless'})")

    # --- Phase 4: Write transcript ---
    writer = TranscriptWriter()
    md_path, json_path = writer.write(beats, strategy.characters)

    print(f"\nTotal: {time.monotonic() - t0:.1f}s")
    print(f"Markdown: {md_path}")
    print(f"JSON:     {json_path}")


def _beat_summary(beat) -> str:
    data = beat.data
    if beat.type == "scene_arrival":
        return f"{data.get('location', '?')} — {len(data.get('threats', []))} threats"
    if beat.type == "combat_round":
        result = data.get("result", {})
        return f"vs {data.get('threat', '?')} — {result.get('message', '')[:60]}"
    if beat.type == "injury":
        result = data.get("result", {})
        return f"{result.get('message', '')[:60]}"
    if beat.type == "scene_complete":
        return data.get("message", "")[:60]
    if beat.type == "death":
        return data.get("message", "")[:60]
    if beat.type == "advance":
        return f"→ {data.get('location', '?')}"
    if beat.type == "epilogue":
        survivors = data.get("survivors", [])
        fallen = data.get("fallen", [])
        return f"survivors: {len(survivors)}, fallen: {len(fallen)}"
    return ""


if __name__ == "__main__":
    main()
