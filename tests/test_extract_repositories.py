"""Safety and manifest coverage for the repository extractor."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/extract_repositories.py"


def _extractor():
    spec = importlib.util.spec_from_file_location("extract_repositories", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_package_manifests_retain_final_and_historical_paths():
    extractor = _extractor()
    for name in ("gia-core", "gas-protocol", "gia-gas-adapter", "gas-mcp"):
        spec = extractor.REPOSITORIES[name]
        sources = {rule.source for rule in spec.paths}
        assert any(path.startswith("packages/") for path in sources)
        assert any(path.startswith("src/") for path in sources)
        assert "pyproject.toml" in spec.required_paths

    core_sources = {rule.source for rule in extractor.REPOSITORIES["gia-core"].paths}
    assert "src/gia/capabilities" in core_sources
    assert "src/gia/policy" in core_sources
    assert "src/gia/provenance" in core_sources


def test_havoc_manifest_retains_the_application_and_historical_gia_tree():
    extractor = _extractor()
    spec = extractor.REPOSITORIES["havoc"]
    sources = {rule.source for rule in spec.paths}
    assert "src/havoc_server" in sources
    assert "src/havoc_domain" in sources
    assert "src/gia" in sources
    assert "eval" in sources


def test_filter_args_rename_both_package_generations():
    extractor = _extractor()
    args = extractor.REPOSITORIES["gas-protocol"].filter_args()
    assert args[args.index("--path") + 1] == "packages/gas-protocol/gas_protocol"
    assert "src/gas_protocol:gas_protocol" in args
    assert "packages/gas-protocol/gas_protocol:gas_protocol" in args


def test_sibling_output_root_is_allowed_but_nested_output_is_rejected(tmp_path):
    extractor = _extractor()
    source = tmp_path / "gia"
    (source / ".git").mkdir(parents=True)
    spec = extractor.REPOSITORIES["gia-core"]

    extractor._validate_destinations(source, tmp_path, [spec])

    try:
        extractor._validate_destinations(source, source / "out", [spec])
    except RuntimeError as exc:
        assert "inside the source checkout" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("nested output root should be rejected")
