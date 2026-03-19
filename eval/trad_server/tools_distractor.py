"""Distractor-padded tool sets: real PM tools + cross-domain noise."""

from __future__ import annotations

from .tools_60 import TOOLS_60
from .distractors import make_distractor_set

TOOLS_120D = TOOLS_60 + make_distractor_set(60)
TOOLS_240D = TOOLS_60 + make_distractor_set(180)
TOOLS_480D = TOOLS_60 + make_distractor_set(420)
