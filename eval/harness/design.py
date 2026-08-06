"""PR12 factorial study design, conditions, and reproducibility snapshots."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .controls import DEFAULT_RETRY_POLICY, HistoryPolicyName


STUDY_ID = "gia-gas-2.0-pr12"
STUDY_VERSION = "1.0"
HISTORICAL_ADVISORY_LABEL = "gas-advisory"


@dataclass(frozen=True)
class ConditionSpec:
    """One independently addressable interface condition."""

    id: str
    label: str
    mode: str
    tool_level: int
    interface_shape: str
    enforcement: str
    filtering: str
    advertises_capabilities: bool
    tool_granularity: str


CONDITIONS: dict[str, ConditionSpec] = {
    "static-native": ConditionSpec(
        id="static-native", label="Static native MCP", mode="trad", tool_level=15,
        interface_shape="native-mcp", enforcement="runtime-domain", filtering="static",
        advertises_capabilities=False, tool_granularity="coarse",
    ),
    "state-filtered-native": ConditionSpec(
        id="state-filtered-native", label="State-filtered native MCP", mode="trad", tool_level=15,
        interface_shape="native-mcp", enforcement="runtime-domain", filtering="state",
        advertises_capabilities=False, tool_granularity="coarse",
    ),
    "generic": ConditionSpec(
        id="generic", label="Generic get/search/act", mode="gas-generic", tool_level=3,
        interface_shape="generic-gas", enforcement="advisory-runtime", filtering="none",
        advertises_capabilities=False, tool_granularity="generic",
    ),
    "gas-advisory": ConditionSpec(
        id="gas-advisory", label="GAS advisory", mode="gas-advisory", tool_level=3,
        interface_shape="generic-gas", enforcement="advisory-runtime", filtering="affordance",
        advertises_capabilities=True, tool_granularity="generic",
    ),
    "gas-enforced": ConditionSpec(
        id="gas-enforced", label="GAS enforced", mode="gas-enforced", tool_level=3,
        interface_shape="generic-gas", enforcement="reference-monitor", filtering="affordance",
        advertises_capabilities=True, tool_granularity="generic",
    ),
}


PRIMARY_HYPOTHESES: tuple[dict[str, str], ...] = (
    {
        "id": "H1-enforcement",
        "claim": "gas-enforced reduces invalid state-transition attempts versus gas-advisory without changing the task text or fixtures.",
        "comparison": "gas-enforced vs gas-advisory",
        "primary_metric": "invalid_state_transition_rate",
    },
    {
        "id": "H2-filtering",
        "claim": "state-filtered native MCP reduces invalid action attempts versus static native MCP.",
        "comparison": "state-filtered-native vs static-native",
        "primary_metric": "invalid_action_rate",
    },
    {
        "id": "H3-interface-shape",
        "claim": "advertised GAS affordances reduce invalid action attempts versus generic get/search/act without affordances.",
        "comparison": "gas-advisory vs generic",
        "primary_metric": "invalid_action_rate",
    },
    {
        "id": "H4-completion",
        "claim": "any completion-rate difference is reported separately from modeled-invariant safety.",
        "comparison": "all conditions",
        "primary_metric": "oracle_pass_rate",
    },
)


@dataclass(frozen=True)
class FactorialCell:
    condition: str
    domain: str
    task_tier: int
    tool_level: int
    run_index: int


@dataclass(frozen=True)
class StudySnapshot:
    study_id: str
    study_version: str
    captured_at: str
    code_commit: str
    fixture_digest: str
    harness_digest: str
    python_version: str
    platform: str
    provider_models: dict[str, dict[str, str]]
    task_tiers: dict[str, int]
    history_policy: str
    retry_policy: dict[str, Any]
    conditions: tuple[str, ...]
    hypotheses: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.is_file():
            continue
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _task_files(eval_root: Path, domain: str) -> list[Path]:
    folder = {"pm": "tasks", "cruise": "cruise_tasks", "auto": "auto_tasks"}.get(domain, "tasks")
    return sorted((eval_root / folder / "definitions").glob("tier_*.json"))


def snapshot_design(
    repo_root: str | Path,
    *,
    models: list[ModelConfig] | None = None,
    domains: tuple[str, ...] = ("pm",),
    task_tiers: tuple[int, ...] = (1, 2, 3, 4),
    history_policy: HistoryPolicyName = "compact-affordances",
) -> StudySnapshot:
    """Capture all mutable inputs needed to reproduce a future matrix run."""
    root = Path(repo_root).resolve()
    eval_root = root / "eval"
    fixture_files = [path for domain in domains for path in _task_files(eval_root, domain)]
    fixture_files.extend(sorted((eval_root / "data").glob("*.json")))
    harness_files = sorted((eval_root / "harness").glob("*.py"))
    provider_models = {
        model.name: {
            "provider": model.api_base,
            "model": model.model,
            "provider_version": model.provider_version,
        }
        for model in (models or [])
    }
    tier_counts: dict[str, int] = {}
    for domain in domains:
        for path in _task_files(eval_root, domain):
            tier = path.stem.removeprefix("tier_")
            if int(tier) in task_tiers:
                tier_counts[f"{domain}:tier_{tier}"] = len(json.loads(path.read_text()))
    return StudySnapshot(
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        captured_at=datetime.now(timezone.utc).isoformat(),
        code_commit=_git_revision(root),
        fixture_digest=_digest_paths(fixture_files),
        harness_digest=_digest_paths(harness_files),
        python_version=sys.version,
        platform=platform.platform(),
        provider_models=provider_models,
        task_tiers=tier_counts,
        history_policy=history_policy,
        retry_policy=asdict(DEFAULT_RETRY_POLICY),
        conditions=tuple(CONDITIONS),
        hypotheses=PRIMARY_HYPOTHESES,
    )


def build_cells(
    *,
    domains: list[str],
    conditions: list[str],
    task_tiers: list[int],
    runs_per_cell: int,
) -> list[FactorialCell]:
    """Build and validate the balanced condition × domain × tier matrix."""
    if runs_per_cell < 1:
        raise ValueError("runs_per_cell must be positive")
    unknown = sorted(set(conditions) - set(CONDITIONS))
    if unknown:
        raise ValueError(f"unknown PR12 condition(s): {', '.join(unknown)}")
    return [
        FactorialCell(
            condition=condition, domain=domain, task_tier=tier,
            tool_level=CONDITIONS[condition].tool_level, run_index=run_index,
        )
        for domain in domains
        for tier in task_tiers
        for condition in conditions
        for run_index in range(runs_per_cell)
    ]


def write_snapshot(snapshot: StudySnapshot, path: str | Path) -> None:
    Path(path).write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n")

