"""RS-10 ownership and released-dependency metadata checks.

Standalone CLI script (not a package under src/), loaded by path from
tests/test_release_boundaries.py for the same reason as
scripts/check_import_boundaries.py: `uv run python
scripts/check_release_boundaries.py` and `pytest` must exercise identical
logic.

RS-04..RS-09 turned `gia-core`, `gas-protocol`, `gia-gas-adapter`, and
`gas-mcp` into distributions this repository merely depends on rather than
owns outright. A dependency that crosses a repository boundary needs more
than a version pin to be safe to release against: it needs a declared owner
(who to page when it breaks), a compatibility range narrow enough to catch
an accidental major bump, and a named release gate (so "did we check this
before cutting a release" has an answer other than "someone remembered").
docs/RELEASE-CHECKLIST.md is that gate for this repository — it names all
four released packages in its own opening paragraph and carries the
"**Owner:**" line RS-10 requires every such document to have.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASED_PACKAGES: tuple[str, ...] = (
    "gia-core",
    "gas-protocol",
    "gia-gas-adapter",
    "gas-mcp",
)

# The compatibility range every released package must be pinned to from the
# root pyproject.toml — `0.2.x`, narrow enough that an accidental `0.3.0`
# (a breaking release per the packages' own semver) fails resolution instead
# of installing silently.
_RANGE_RE = re.compile(r">=\s*0\.2(?:\.\d+)?\s*,\s*<\s*0\.3")

_OWNER_RE = re.compile(r"\*\*Owner:\*\*\s*(?P<owner>.+)")


def _dependency_specs(pyproject: dict) -> dict[str, str]:
    project = pyproject.get("project", {})
    specs: dict[str, str] = {}
    for dep in project.get("dependencies", []):
        name = re.split(r"[><=!~\[;\s]", dep, maxsplit=1)[0].strip()
        specs[name] = dep
    for group in project.get("optional-dependencies", {}).values():
        for dep in group:
            name = re.split(r"[><=!~\[;\s]", dep, maxsplit=1)[0].strip()
            specs.setdefault(name, dep)
    return specs


def check_release_boundaries(repo_root: Path) -> list[str]:
    """Return a list of human-readable violations; [] means every released
    cross-repository dependency has a declared owner, a 0.2.x compatibility
    range, and a named CI/release gate."""
    violations: list[str] = []

    root_pyproject_path = repo_root / "pyproject.toml"
    if not root_pyproject_path.is_file():
        return [f"root pyproject.toml not found at {root_pyproject_path}"]
    dep_specs = _dependency_specs(tomllib.loads(root_pyproject_path.read_text()))

    checklist_path = repo_root / "docs" / "RELEASE-CHECKLIST.md"
    checklist_text = checklist_path.read_text() if checklist_path.is_file() else ""
    owner_match = _OWNER_RE.search(checklist_text)
    if not checklist_path.is_file():
        violations.append("docs/RELEASE-CHECKLIST.md is missing — no release gate declared")
    elif not owner_match or not owner_match.group("owner").strip():
        violations.append("docs/RELEASE-CHECKLIST.md has no declared **Owner:**")

    for name in RELEASED_PACKAGES:
        package_root = repo_root / "packages" / name
        if not package_root.is_dir():
            violations.append(f"{name}: packages/{name} is not checked out locally")

        spec = dep_specs.get(name)
        if spec is None:
            violations.append(f"{name}: no declared dependency in root pyproject.toml")
        elif not _RANGE_RE.search(spec):
            violations.append(
                f"{name}: dependency spec {spec!r} is not pinned to a 0.2.x compatibility range"
            )

        if checklist_path.is_file() and name not in checklist_text:
            violations.append(f"{name}: not named in docs/RELEASE-CHECKLIST.md's release gate")

    return violations


def main(argv: list[str]) -> int:
    repo_root = Path(argv[1]) if len(argv) > 1 else REPO_ROOT
    violations = check_release_boundaries(repo_root)
    if violations:
        for violation in violations:
            print(f"- {violation}")
        print(f"{len(violations)} release-boundary violation(s) found")
        return 1
    print("OK: every released dependency has an owner, a 0.2.x range, and a release gate")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
