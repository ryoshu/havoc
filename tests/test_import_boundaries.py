"""PR 13: import-boundary enforcement (docs/gia2/DEPENDENCY-BOUNDARIES.md).

Loads scripts/check_import_boundaries.py by path (it is a standalone CLI
script, not a package under src/) so both `pytest` and
`uv run python scripts/check_import_boundaries.py` exercise the same
checker logic.
"""

from __future__ import annotations

import ast
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


def test_extracted_gia_core_tree_has_no_boundary_violations():
    gia_core_root = REPO_ROOT / "packages" / "gia-core" / "gia_core"
    assert gia_core_root.is_dir()
    assert not gia_core_root.is_symlink(), "RS-05 must own real source files"
    violations = checker.check_boundaries(gia_core_root)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_extracted_gas_protocol_tree_has_no_boundary_violations():
    gas_protocol_root = REPO_ROOT / "packages" / "gas-protocol" / "gas_protocol"
    assert gas_protocol_root.is_dir()
    assert not gas_protocol_root.is_symlink(), "RS-06 must own real source files"
    violations = checker.check_boundaries(gas_protocol_root)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_extracted_gia_gas_adapter_tree_has_no_boundary_violations():
    adapter_root = REPO_ROOT / "packages" / "gia-gas-adapter" / "gia_gas_adapter"
    assert adapter_root.is_dir()
    assert not adapter_root.is_symlink(), "RS-07 must own real source files"
    violations = checker.check_boundaries(adapter_root)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_extracted_gas_mcp_tree_has_no_boundary_violations():
    mcp_root = REPO_ROOT / "packages" / "gas-mcp" / "gas_mcp"
    assert mcp_root.is_dir()
    assert not mcp_root.is_symlink(), "RS-08 must own real source files"
    violations = checker.check_boundaries(mcp_root)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_default_checker_covers_extracted_workspace_trees():
    assert checker.check_repository_boundaries() == []


def test_bucket_for_matches_longest_prefix():
    assert checker.bucket_for("src.gia_core.capabilities.models") == "gia_core"
    assert checker.bucket_for("mcp.server") == "mcp_transport"
    assert checker.bucket_for("src.gia.server") == "composition_root"
    # PR 18 moved the concrete Havoc implementation into `havoc_domain`,
    # leaving thin `src.gia.*` re-export shims at the old paths; PR 19
    # deleted every one of those shims once first-party callers had
    # migrated, so only `src.havoc_domain`/`havoc_domain` remain bucketed.
    assert checker.bucket_for("src.havoc_domain.context") == "havoc_domain"
    assert checker.bucket_for("src.havoc_domain.models") == "havoc_domain"
    assert checker.bucket_for("src.havoc_domain.commands.kernel") == "havoc_domain"
    assert checker.bucket_for("havoc_domain.engine") == "havoc_domain"
    assert checker.bucket_for("havoc_domain.application") == "havoc_domain"
    assert checker.bucket_for("havoc_domain.runtime") == "havoc_domain"
    # `gia_core.approval_workflow` (PR 18's second, Havoc-free domain) is
    # ordinary `gia_core` content — no special-casing needed.
    assert checker.bucket_for("src.gia_core.approval_workflow") == "gia_core"
    assert checker.bucket_for("gia_core.approval_workflow") == "gia_core"
    assert checker.bucket_for("src.agent.loop") is None


def test_bucket_for_also_matches_installed_package_names():
    """The six target namespaces must be recognized both as `src.<name>`
    (today, run from the repo root) and bare `<name>` (once any of them is
    consumed as an installed package) — see BUCKET_PREFIXES' module note."""
    assert checker.bucket_for("gia_core.models") == "gia_core"
    assert checker.bucket_for("gas_protocol.contracts") == "gas_protocol"
    # `gia_gas_adapter` got its own bucket in PR 16 — unlike gas_protocol,
    # it's allowed to depend on gia_core (see BUCKET_PREFIXES' PR 16 note).
    assert checker.bucket_for("gia_gas_adapter.mapping") == "gia_gas_adapter"
    assert checker.bucket_for("gas_mcp.install") == "mcp_transport"
    assert checker.bucket_for("havoc_domain.engine") == "havoc_domain"
    assert checker.bucket_for("havoc_server.main") == "composition_root"


def test_bare_legacy_submodule_imports_are_not_silently_unbucketed():
    """Regression test (found in review after PR 18 first shipped): the
    bare/prefixed duality applies one level down too, to every individual
    `src.gia.<submodule>` path, not just the six top-level names.

    `gia` is bare-importable *today*, not only once packaged/installed (see
    BUCKET_PREFIXES' module note). A bucket entry for only the `src.gia.X`
    prefixed form of one of these submodules means `bucket_for()` returns
    `None` for the bare form, and `check_boundaries()` silently skips any
    import whose target bucket is `None` — so a forbidden edge written with
    a bare import sails through undetected. This first surfaced as
    `gia_core`'s bucket listing only `src.gia.{capabilities,policy,
    provenance}`, not their bare `gia.*` equivalents. RS-02
    (docs/GIA-REPOSITORY-SPLIT-PLAN.md) later moved those three packages to
    `src/gia_core/` outright with no shim left at the old `gia.*` path (see
    BUCKET_PREFIXES' RS-02 note), and RS-03 moved the MCP-dependent
    `gia.renderers.native_mcp` to `havoc_server.native_mcp` the same way, so
    this test now covers the one path that still lives under `src/gia/`:
    `gia.server`, plus `havoc_domain`'s own bare form."""
    assert checker.bucket_for("gia_core.capabilities.models") == "gia_core"
    assert checker.bucket_for("gia_core.policy") == "gia_core"
    assert checker.bucket_for("gia_core.provenance") == "gia_core"
    assert checker.bucket_for("havoc_domain.context") == "havoc_domain"
    assert checker.bucket_for("havoc_domain.commands.kernel") == "havoc_domain"
    assert checker.bucket_for("gia.server") == "composition_root"
    assert checker.bucket_for("havoc_server.native_mcp") == "composition_root"


def test_forbidden_edge_via_bare_legacy_import_is_detected(tmp_path):
    """The exact regression this reports: a `gas_protocol -> gia_core` edge
    written as a bare `from gia_core.capabilities import ...` (rather than
    `from src.gia_core.capabilities import ...`) must be caught, not
    silently pass because the bare form wasn't in the bucket map."""
    src_root = tmp_path / "src" / "gas_protocol"
    src_root.mkdir(parents=True)
    (src_root / "forbidden.py").write_text("from gia_core.capabilities import CapabilitySet\n")

    violations = checker.check_boundaries(tmp_path / "src")

    assert len(violations) == 1
    assert violations[0].target_bucket == "gia_core"
    assert (violations[0].source_bucket, violations[0].target_bucket) in checker.FORBIDDEN_EDGES


@pytest.mark.parametrize(
    ("source_module", "source_code", "expected_target_bucket"),
    [
        # GIA-to-GAS: forbidden per the PR 13 exit criteria, tightened in
        # PR 15 to the real `gas_protocol` namespace (`src.gia.gas`, the
        # deprecated compatibility path rather than the target GAS
        # namespace, was removed entirely in PR 19).
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
            "src.gas_protocol.forbidden",
            "from src.havoc_domain.context import GameContext\n",
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
        # adapter-to-game: forbidden per PR 16's dependency-rules table
        # ("gia-gas-adapter | gia-core, gas-protocol | MCP, Havoc
        # implementations, ..."). `gia_gas_adapter` got its own bucket in
        # PR 16 specifically so this edge (which gas_protocol also
        # forbids) is still caught after the split.
        (
            "src.gia_gas_adapter.forbidden",
            "from src.havoc_domain.context import GameContext\n",
            "havoc_domain",
        ),
        # adapter-to-MCP: forbidden per the same PR 16 table entry.
        (
            "src.gia_gas_adapter.forbidden_mcp",
            "import mcp\n",
            "mcp_transport",
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
        # GIA-to-game: the literal PR 18 exit criterion ("GIA core has no
        # knowledge of characters, enemies, scenes, game phases, or the
        # Havoc engine").
        (
            "src.gia_core.forbidden_havoc",
            "from havoc_domain.context import GameContext\n",
            "havoc_domain",
        ),
        # game-to-GAS: PR 18's target-state table row ("havoc-domain ...
        # must not depend on GAS and MCP transport code").
        (
            "src.havoc_domain.forbidden_gas",
            "from src.gas_protocol import GasService\n",
            "gas_protocol",
        ),
        # game-to-MCP: same PR 18 table entry, the other half.
        (
            "src.havoc_domain.forbidden_mcp",
            "import mcp\n",
            "mcp_transport",
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


@pytest.mark.parametrize(
    ("source_module", "source_code"),
    [
        # gia_gas_adapter -> gia_core is explicitly allowed by PR 16's
        # dependency-rules table ("gia-gas-adapter | gia-core,
        # gas-protocol | ..."): the adapter's whole job is mapping
        # CapabilityAuthority/ResourceProvider (gia_core.ports) results
        # into gas_protocol shapes, so this is the one gia_core edge that
        # must NOT be caught by the checker, unlike gas_protocol's own
        # forbidden ("gas_protocol", "gia_core") edge from PR 15.
        ("src.gia_gas_adapter.allowed_gia_core", "from src.gia_core.errors import DomainError\n"),
        # gia_gas_adapter -> gas_protocol is allowed by the same table
        # entry — the adapter implements gas_protocol.backend.GasBackend.
        ("src.gia_gas_adapter.allowed_gas_protocol", "from src.gas_protocol import GasService\n"),
        # havoc_domain -> gia_core is explicitly allowed (PR 18's
        # target-state table: "havoc-domain | gia-core, domain
        # infrastructure | ..."). `havoc_domain.application
        # .HavocGiaApplication` implements `gia_core.ports` from the Havoc
        # side — that's the whole point of PR 18, not a violation of it.
        ("src.havoc_domain.allowed_gia_core", "from src.gia_core.errors import DomainError\n"),
    ],
)
def test_deliberately_allowed_import_is_not_flagged(tmp_path, source_module, source_code):
    src_root = tmp_path / "src"
    package_dir = src_root
    for part in source_module.split(".")[1:-1]:
        package_dir = package_dir / part
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / f"{source_module.rsplit('.', 1)[-1]}.py").write_text(source_code)

    violations = checker.check_boundaries(src_root)

    assert violations == [], "\n".join(str(v) for v in violations)


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


# --- PR 18: forbidden game vocabulary in GIA core --------------------------
#
# PR 18's own Tests bullet names this as a distinct requirement, separate
# from the import-boundary edges above: "repository checks for forbidden
# game vocabulary and imports in GIA core." The import-boundary checker
# already catches `gia_core -> havoc_domain` imports structurally; this is
# the complementary lexical check — `gia_core` should never *name* a Havoc
# concept as an identifier, even one reached without an import (e.g. a
# duck-typed parameter called `character_id`).
#
# Scoped to AST identifiers (Name/Attribute/arg/def/import-alias), not raw
# text, deliberately: several existing `gia_core` docstrings *discuss* Havoc
# by name while explaining why the module doesn't depend on it (e.g.
# `gia_core/errors.py`: "none of these ten classes ever referenced a Havoc
# concept (characters, dice, blood, scenes)") — a substring scan over the
# whole file would flag exactly the prose proving the property holds. AST
# parsing naturally excludes comments (never nodes at all) and this walk
# deliberately skips string/docstring `Constant` nodes, so only executable
# identifiers are checked.
FORBIDDEN_GAME_VOCABULARY: tuple[str, ...] = (
    "character",
    "enemy",
    "havoc",
    "vampire",
    "scene",
    "blood",
    "injur",
    "objective",
    "dice",
)


def _identifiers(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.arg):
            yield node.arg
        elif isinstance(node, ast.alias):
            yield node.asname or node.name


def test_gia_core_never_names_a_havoc_concept():
    gia_core_root = REPO_ROOT / "packages" / "gia-core" / "gia_core"
    violations = []
    for py_file in sorted(gia_core_root.rglob("*.py")):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for identifier in _identifiers(tree):
            lowered = identifier.lower()
            for term in FORBIDDEN_GAME_VOCABULARY:
                if term in lowered:
                    violations.append(f"{py_file.relative_to(REPO_ROOT)}: {identifier!r} contains {term!r}")
    assert violations == [], "\n".join(violations)
