"""PR 13: import-boundary enforcement (docs/gia2/DEPENDENCY-BOUNDARIES.md).

Loads scripts/check_import_boundaries.py by path (it is a standalone CLI
script, not a package under src/) so both `pytest` and
`uv run python scripts/check_import_boundaries.py` exercise the same
checker logic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER_PATH = REPO_ROOT / "scripts" / "check_import_boundaries.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_import_boundaries", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_real_src_tree_has_no_boundary_violations():
    violations = checker.check_boundaries(REPO_ROOT / "src")
    assert violations == [], "\n".join(str(v) for v in violations)


def test_bucket_for_matches_longest_prefix():
    assert checker.bucket_for("src.gia.capabilities.models") == "gia_core"
    assert checker.bucket_for("mcp.server") == "mcp_transport"
    assert checker.bucket_for("src.gia.context") == "havoc_domain"
    assert checker.bucket_for("src.gia.server") == "composition_root"
    assert checker.bucket_for("src.gia.domain") == "kernel_transitional"
    # `src.gia.gas` (GasRuntime) joined kernel_transitional in PR 15: it's
    # the deprecated Havoc-coupled GAS compatibility path, not the clean
    # `gas_protocol` namespace — see BUCKET_PREFIXES' module note.
    assert checker.bucket_for("src.gia.gas.runtime") == "kernel_transitional"
    assert checker.bucket_for("src.agent.loop") is None


def test_bucket_for_also_matches_installed_package_names():
    """The six target namespaces must be recognized both as `src.<name>`
    (today, run from the repo root) and bare `<name>` (once any of them is
    consumed as an installed package) — see BUCKET_PREFIXES' module note."""
    assert checker.bucket_for("gia_core.models") == "gia_core"
    assert checker.bucket_for("gas_protocol.contracts") == "gas_protocol"
    assert checker.bucket_for("gia_gas_adapter.mapping") == "gas_protocol"
    assert checker.bucket_for("gas_mcp.install") == "mcp_transport"
    assert checker.bucket_for("havoc_domain.engine") == "havoc_domain"
    assert checker.bucket_for("havoc_server.main") == "composition_root"


@pytest.mark.parametrize(
    ("source_module", "source_code", "expected_target_bucket"),
    [
        # GIA-to-GAS: forbidden per the PR 13 exit criteria, tightened in
        # PR 15 to the real `gas_protocol` namespace (`src.gia.gas` moved
        # into the exempt kernel_transitional bucket in PR 15 — it's the
        # deprecated compatibility path, not the target GAS namespace).
        (
            "src.gia_core.forbidden",
            "from src.gas_protocol import GasService\n",
            "gas_protocol",
        ),
        # GAS-to-MCP: forbidden per the PR 13 exit criteria.
        (
            "src.gas_protocol.forbidden",
            "import mcp\n",
            "mcp_transport",
        ),
        # GAS-to-game: forbidden per the PR 13 exit criteria.
        (
            "src.gia_gas_adapter.forbidden",
            "from src.gia.context import GameContext\n",
            "havoc_domain",
        ),
        # GAS-to-GIA: the new edge PR 15 adds — gas_protocol must not
        # depend on gia_core at all (docs/gia2/DEPENDENCY-BOUNDARIES.md's
        # target-state table), not just avoid MCP/Havoc.
        (
            "src.gas_protocol.forbidden_gia_core",
            "from src.gia_core.errors import DomainError\n",
            "gia_core",
        ),
        # GIA-to-MCP: forbidden per the PR 13 exit criteria. The fourth
        # named edge — GIA-to-GAS, GAS-to-MCP, and GAS-to-game are each
        # covered by a case above.
        (
            "src.gia_core.forbidden_mcp",
            "import mcp\n",
            "mcp_transport",
        ),
        # Same edge as above (GIA-to-GAS), but importing the bare
        # installed-package name instead of the src-tree path — proves the
        # bucket map's installed-name aliases are actually wired into
        # detection, not just declared.
        (
            "src.gia_core.forbidden_installed_name",
            "import gas_protocol\n",
            "gas_protocol",
        ),
    ],
)
def test_deliberately_forbidden_import_is_detected(
    tmp_path, source_module, source_code, expected_target_bucket
):
    """The boundary-test fixture required by PR 13: a forbidden dependency
    must be caught by the checker, not just theoretically enforceable."""
    src_root = tmp_path / "src"
    package_dir = src_root
    for part in source_module.split(".")[1:-1]:
        package_dir = package_dir / part
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / f"{source_module.rsplit('.', 1)[-1]}.py").write_text(source_code)

    violations = checker.check_boundaries(src_root)

    assert len(violations) == 1
    violation = violations[0]
    assert violation.target_bucket == expected_target_bucket
    assert (violation.source_bucket, violation.target_bucket) in checker.FORBIDDEN_EDGES


def test_main_returns_nonzero_on_forbidden_import(tmp_path, capsys):
    src_root = tmp_path / "src" / "gia_core"
    src_root.mkdir(parents=True)
    (src_root / "forbidden.py").write_text("from src.gas_protocol import GasService\n")

    exit_code = checker.main(["check_import_boundaries.py", str(tmp_path / "src")])

    assert exit_code == 1
    assert "forbidden edge" in capsys.readouterr().err


def test_main_returns_zero_on_clean_tree(tmp_path, capsys):
    src_root = tmp_path / "src" / "gia_core"
    src_root.mkdir(parents=True)
    (src_root / "clean.py").write_text("import json\n")

    exit_code = checker.main(["check_import_boundaries.py", str(tmp_path / "src")])

    assert exit_code == 0
    assert "OK" in capsys.readouterr().out
