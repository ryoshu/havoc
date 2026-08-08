"""Import-boundary checker for the separated repositories.

Standalone CLI script (not a package under src/) so both `pytest` and
`uv run python scripts/check_import_boundaries.py [path ...]` exercise the
same checker logic — see tests/test_import_boundaries.py, which loads this
file by path rather than importing it as a module.

The checker buckets every `.py` file under a scanned root into one of six
target namespaces by its own module path, walks its `import`/`from ... import`
statements, buckets each import target the same way, and flags any
(source_bucket, target_bucket) pair that appears in FORBIDDEN_EDGES.

RS-04..RS-09 physically extracted
`gia_core`, `gas_protocol`, `gia_gas_adapter`, and `gas_mcp` out of this
repository's `src/` tree into standalone `packages/*` distributions; this
script now also has to bucket bare, uninstalled-adjacent imports (a package
importing `gas_protocol` rather than `src.gas_protocol`) the same way it
buckets the pre-split repo-root-relative form, so the boundary it enforces
does not silently go blind the moment any of the four is consumed as an
installed dependency instead of a sibling source directory.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Each of the six target namespaces is bucketed under both its repo-root-
# relative `src.<name>` form (today, run from the repo root or scanned as
# `src/<name>/...`) and its bare `<name>` form (once consumed as an
# installed package, or when a workspace member's own tree is scanned
# directly). `mcp` (the SDK) and `gas_mcp` (this repo's transport package)
# share the `mcp_transport` bucket: anything that reaches either one has
# reached the MCP transport layer.
BUCKET_PREFIXES: dict[str, str] = {
    "src.gia_core": "gia_core",
    "gia_core": "gia_core",
    "src.gas_protocol": "gas_protocol",
    "gas_protocol": "gas_protocol",
    "src.gia_gas_adapter": "gia_gas_adapter",
    "gia_gas_adapter": "gia_gas_adapter",
    "src.gas_mcp": "mcp_transport",
    "gas_mcp": "mcp_transport",
    "mcp": "mcp_transport",
    "src.havoc_domain": "havoc_domain",
    "havoc_domain": "havoc_domain",
    "src.havoc_server": "composition_root",
    "havoc_server": "composition_root",
}

# Sorted longest-prefix-first so e.g. "src.havoc_server" is checked before
# any shorter prefix that might otherwise shadow it.
_ORDERED_PREFIXES = sorted(BUCKET_PREFIXES, key=len, reverse=True)

# The PR 13 exit criteria's four named forbidden edges (GIA-to-GAS,
# GAS-to-MCP, GAS-to-game, GIA-to-MCP), PR 15's new GAS-to-GIA edge
# (gas_protocol must not depend on gia_core at all, not just avoid MCP/
# Havoc), PR 16's adapter-to-game and adapter-to-MCP edges (the adapter may
# depend on gia_core and gas_protocol — that's its whole job — but nothing
# else), PR 18's GIA-to-game and game-to-GAS/MCP edges. `composition_root`
# (havoc_server) is the wiring root and is deliberately unconstrained here:
# it is expected to depend on every reusable core to build the runtime.
FORBIDDEN_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("gia_core", "gas_protocol"),
        ("gia_core", "mcp_transport"),
        ("gia_core", "havoc_domain"),
        ("gas_protocol", "gia_core"),
        ("gas_protocol", "mcp_transport"),
        ("gas_protocol", "havoc_domain"),
        ("gia_gas_adapter", "havoc_domain"),
        ("gia_gas_adapter", "mcp_transport"),
        ("havoc_domain", "gas_protocol"),
        ("havoc_domain", "mcp_transport"),
    }
)


def bucket_for(module_path: str | None) -> str | None:
    """Return the target namespace `module_path` belongs to, or None."""
    if not module_path:
        return None
    for prefix in _ORDERED_PREFIXES:
        if module_path == prefix or module_path.startswith(prefix + "."):
            return BUCKET_PREFIXES[prefix]
    return None


@dataclass(frozen=True)
class Violation:
    file: Path
    lineno: int
    source_bucket: str
    target_bucket: str
    imported: str

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.lineno}: forbidden edge "
            f"{self.source_bucket} -> {self.target_bucket} (imports {self.imported!r})"
        )


def _module_path_for_file(py_file: Path, scan_root: Path) -> str:
    relative = py_file.relative_to(scan_root.parent).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_targets(tree: ast.Module) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                continue  # `from . import x` / `from .. import x`: intra-package
            if node.module:
                targets.append((node.lineno, node.module))
    return targets


def check_boundaries(root: Path) -> list[Violation]:
    """Scan every `.py` file under `root` for forbidden cross-bucket imports."""
    violations: list[Violation] = []
    if not root.is_dir():
        return violations
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        source_bucket = bucket_for(_module_path_for_file(py_file, root))
        if source_bucket is None:
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for lineno, imported in _imported_targets(tree):
            target_bucket = bucket_for(imported)
            if target_bucket is None:
                continue
            if (source_bucket, target_bucket) in FORBIDDEN_EDGES:
                violations.append(
                    Violation(py_file, lineno, source_bucket, target_bucket, imported)
                )
    return violations


def check_repository_boundaries(repo_root: Path | None = None) -> list[Violation]:
    """The default checker: `src/` plus every extracted `packages/*` tree."""
    repo_root = repo_root or REPO_ROOT
    roots = [
        repo_root / "src",
        repo_root / "packages" / "gia-core" / "gia_core",
        repo_root / "packages" / "gas-protocol" / "gas_protocol",
        repo_root / "packages" / "gia-gas-adapter" / "gia_gas_adapter",
        repo_root / "packages" / "gas-mcp" / "gas_mcp",
    ]
    violations: list[Violation] = []
    for root in roots:
        violations.extend(check_boundaries(root))
    return violations


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]] or [REPO_ROOT / "src"]
    violations: list[Violation] = []
    for path in paths:
        violations.extend(check_boundaries(path))

    if violations:
        for violation in violations:
            print(str(violation), file=sys.stderr)
        print(f"{len(violations)} forbidden edge(s) found", file=sys.stderr)
        return 1

    print("OK: no forbidden import-boundary edges found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
