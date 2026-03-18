"""Narrator — LLM prose generation at narrative beats.

Supports two modes:
- stateless: each beat narrated independently (constant token cost)
- stateful: accumulates prior narration for continuity (growing context)
"""

from __future__ import annotations

import time

from openai import APITimeoutError, InternalServerError, OpenAI

from .config import NarrativeBeat

RETRIES = 3

NARRATOR_SYSTEM = """\
You are narrating EAT THE REICH — ultraviolent pulp-action horror.
WWII vampire commandos parachute into occupied Paris to assassinate Hitler.

STYLE:
- Present tense. Short, punchy sentences. Noir tone. Dark humor.
- Never mention dice, ratings, numbers, or game mechanics.
- Translate mechanical events into visceral fiction.

DIALOGUE IS MANDATORY:
- Every beat MUST include at least 2-3 lines of spoken dialogue between characters.
- Characters banter, argue, joke, and taunt mid-combat. They are not silent professionals.
- Each character has a distinct voice based on their personality (provided in context).
- Use dialogue to reveal character dynamics: who leads, who cracks jokes, who broods.
- Dialogue should feel natural and in-character — quips during violence, dark humor about death.

Do not editorialize or break the fourth wall.\
"""

BEAT_TYPE_PROMPTS = {
    "scene_arrival": "The vampires arrive at a new location. Set the scene — atmosphere, danger, what they see.",
    "combat_round": "A round of brutal combat. Describe the action — who fights, how, what happens.",
    "injury": "A vampire takes a serious hit. Show the pain, the damage, the resilience.",
    "scene_complete": "The objective is achieved. Show the aftermath — exhaustion, triumph, cost.",
    "death": "A vampire falls for the last time. Their last stand. Make it memorable.",
    "advance": "The squad pushes deeper into Paris. Transition — what they leave behind, what awaits.",
    "epilogue": "The mission ends. Survivors reflect. The fallen are honored. The war goes on.",
}


class Narrator:
    """Generates prose for narrative beats using an LLM."""

    def __init__(
        self,
        client: OpenAI,
        model: str = "qwen3.5:9b",
        stateful: bool = False,
    ):
        self.client = client
        self.model = model
        self.stateful = stateful
        self._history: list[str] = []  # accumulated narration for stateful mode

    def narrate_all(self, beats: list[NarrativeBeat], max_beats: int = 0) -> None:
        """Generate narration for beats in place. max_beats=0 means all."""
        narrated = 0
        for beat in beats:
            if not beat.context:
                continue
            if max_beats and narrated >= max_beats:
                break
            beat.narration = self._narrate_one(beat)
            narrated += 1
            if self.stateful:
                self._history.append(beat.narration)

    def _narrate_one(self, beat: NarrativeBeat) -> str:
        beat_prompt = BEAT_TYPE_PROMPTS.get(beat.type, "Narrate this moment.")
        user_content = f"{beat_prompt}\n\n{beat.context}"

        if self.stateful and self._history:
            # Include summary of prior narration for continuity
            prior = "\n\n---\n\n".join(self._history[-3:])  # last 3 beats max
            user_content = f"STORY SO FAR:\n{prior}\n\n---\n\nNEW BEAT:\n{user_content}"

        messages = [
            {"role": "system", "content": NARRATOR_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        for attempt in range(RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    extra_body={"options": {"num_ctx": 8192}},
                )
                return response.choices[0].message.content or ""
            except (InternalServerError, APITimeoutError):
                if attempt == RETRIES - 1:
                    raise
                print(f"  Narrator retry ({attempt + 1}/{RETRIES})...")
                time.sleep(2)
        return ""
