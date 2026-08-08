"""Safe repository extraction: turn `packages/*` workspace members (and, for
`havoc` itself, the application tree) into standalone git checkouts with
their own history, via `git filter-repo`.

This is the tool RS-05..RS-09 (docs/GIA-REPOSITORY-SPLIT-PLAN.md) used to
produce the `gia-core`, `gas-protocol`, `gia-gas-adapter`, and `gas-mcp`
repositories from this monorepo's history, and the tool a future RS-N would
use again if another package needs the same treatment. Each `RepoSpec` in
`REPOSITORIES` names every path a package's content has ever lived at —
including paths superseded by a later restructuring commit — so
`git filter-repo`'s history rewrite keeps that package's full commit
history, not just a squashed snapshot of its current location.

Safety: `git filter-repo` rewrites history in place by default. This script
always runs it against a disposable clone of the source checkout (never the
checkout the caller is standing in), and `_validate_destinations` refuses to
write extraction output back inside the source checkout it was cloned from,
so a mistyped `--output-root` cannot corrupt the monorepo being read.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PathRule:
    """One path a package's content has lived at, historical or current.

    `source` is the path as it appears (or appeared) in the monorepo tree.
    `dest` is where that content lands in the extracted repository — the
    package-relative path, e.g. `gia_core/capabilities` for content that
    used to live at `src/gia/capabilities`.
    """

    source: str
    dest: str


@dataclass(frozen=True)
class RepoSpec:
    name: str
    paths: tuple[PathRule, ...]
    required_paths: tuple[str, ...] = ("pyproject.toml",)

    def filter_args(self) -> list[str]:
        """Build `git filter-repo` arguments: one `--path` per source (so
        history touching any historical location is retained), followed by
        one `--path-rename old:new` per source (so every historical location
        collapses onto the same final package-relative path)."""
        args: list[str] = []
        for rule in self.paths:
            args += ["--path", rule.source]
        for rule in self.paths:
            args += ["--path-rename", f"{rule.source}:{rule.dest}"]
        return args


REPOSITORIES: dict[str, RepoSpec] = {
    "gia-core": RepoSpec(
        name="gia-core",
        paths=(
            # RS-05's current physical location.
            PathRule("packages/gia-core/gia_core", "gia_core"),
            # RS-02 moved gia_core out from under src/gia/* to its own
            # top-level src/gia_core/ package, pre-dating the RS-05 extract.
            PathRule("src/gia_core", "gia_core"),
            # Pre-RS-02 shim locations (docs/gia2/DEPENDENCY-BOUNDARIES.md's
            # history), retained so their commits are not orphaned.
            PathRule("src/gia/capabilities", "gia_core/capabilities"),
            PathRule("src/gia/policy", "gia_core/policy"),
            PathRule("src/gia/provenance", "gia_core/provenance"),
        ),
    ),
    "gas-protocol": RepoSpec(
        name="gas-protocol",
        paths=(
            PathRule("packages/gas-protocol/gas_protocol", "gas_protocol"),
            PathRule("src/gas_protocol", "gas_protocol"),
        ),
    ),
    "gia-gas-adapter": RepoSpec(
        name="gia-gas-adapter",
        paths=(
            PathRule("packages/gia-gas-adapter/gia_gas_adapter", "gia_gas_adapter"),
            PathRule("src/gia_gas_adapter", "gia_gas_adapter"),
        ),
    ),
    "gas-mcp": RepoSpec(
        name="gas-mcp",
        paths=(
            PathRule("packages/gas-mcp/gas_mcp", "gas_mcp"),
            PathRule("src/gas_mcp", "gas_mcp"),
        ),
    ),
    "havoc": RepoSpec(
        name="havoc",
        paths=(
            PathRule("src/havoc_server", "src/havoc_server"),
            PathRule("src/havoc_domain", "src/havoc_domain"),
            PathRule("src/agent", "src/agent"),
            PathRule("src/demo", "src/demo"),
            PathRule("src/playthrough", "src/playthrough"),
            # Historical pre-RS-02/RS-09 tree — kept for provenance even
            # though nothing imports it anymore (docs/MIGRATION-GUIDE.md).
            PathRule("src/gia", "src/gia"),
            PathRule("eval", "eval"),
            PathRule("data", "data"),
            PathRule("ontology", "ontology"),
            PathRule("docs", "docs"),
            PathRule("tests", "tests"),
        ),
    ),
}


def _validate_destinations(source: Path, output_root: Path, specs: list[RepoSpec]) -> None:
    """Refuse to write extraction output back inside the source checkout."""
    resolved_source = source.resolve()
    resolved_output = output_root.resolve()
    try:
        resolved_output.relative_to(resolved_source)
    except ValueError:
        return
    raise RuntimeError(
        f"Output root {resolved_output} is inside the source checkout {resolved_source}; "
        "extracted repositories must be written outside the monorepo being read."
    )


def _extract_one(source: Path, output_root: Path, spec: RepoSpec) -> Path:
    destination = output_root / spec.name
    if destination.exists():
        raise RuntimeError(f"{destination} already exists; refusing to overwrite it")

    with tempfile.TemporaryDirectory(prefix=f"extract-{spec.name}-") as tmp:
        clone = Path(tmp) / spec.name
        subprocess.run(["git", "clone", "--no-local", str(source), str(clone)], check=True)
        subprocess.run(
            ["git", "filter-repo", *spec.filter_args()],
            check=True,
            cwd=clone,
        )
        for required in spec.required_paths:
            if not (clone / required).exists():
                raise RuntimeError(
                    f"{spec.name}: extraction dropped required path {required!r} — "
                    "check the manifest's `dest` values"
                )
        shutil.move(str(clone), str(destination))
    return destination


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REPO_ROOT, help="Monorepo checkout to read from")
    parser.add_argument("--output-root", type=Path, required=True, help="Directory to write extracted repos into")
    parser.add_argument(
        "--repo",
        action="append",
        dest="repos",
        choices=sorted(REPOSITORIES),
        help="Repository to extract (repeatable); default: all",
    )
    args = parser.parse_args(argv[1:])

    names = args.repos or sorted(REPOSITORIES)
    specs = [REPOSITORIES[name] for name in names]

    _validate_destinations(args.source, args.output_root, specs)
    args.output_root.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        destination = _extract_one(args.source, args.output_root, spec)
        print(f"{spec.name}: extracted to {destination}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
