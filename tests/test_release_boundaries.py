"""RS-10 ownership and released-dependency metadata checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts/check_release_boundaries.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_release_boundaries", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_released_boundaries_have_owners_ranges_and_ci_gates():
    assert _checker().check_release_boundaries(REPO_ROOT) == []
