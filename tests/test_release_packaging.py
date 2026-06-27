"""Regression tests for local release packaging inputs."""

from __future__ import annotations

import re
from pathlib import Path

from foxport import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_no_remote_workflows_ship():
    """Builds and tests run locally; the repo should not ship workflow YAML."""
    assert not (ROOT / ".github" / "workflows").exists()


def test_pyinstaller_spec_bundles_runtime_assets():
    """The Windows package must carry the data files the app loads at runtime."""
    spec = (ROOT / "foxport.spec").read_text(encoding="utf-8")
    for payload in (
        "foxport/data/curated_extension_map.json",
        "foxport/data/glean_metrics.yaml",
        "foxport/data/glean_pings.yaml",
        "assets/icon.ico",
    ):
        assert payload in spec
    assert "foxport/data/foxport_abe.exe" in spec
    assert "CHANGELOG.md" in spec


def test_windows_version_info_matches_package_version():
    """EXE metadata must match ``foxport.__version__`` before packaging."""
    version_info = (ROOT / "assets" / "version_info.txt").read_text(encoding="utf-8")
    expected_tuple = ",".join(__version__.split(".") + ["0"])
    assert f"filevers=({expected_tuple})" in version_info
    assert f"prodvers=({expected_tuple})" in version_info
    for field in ("FileVersion", "ProductVersion"):
        assert f"StringStruct('{field}', '{__version__}')" in version_info


def test_readme_version_badge_matches_package_version():
    """README badges are part of the release surface."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"img\.shields\.io/badge/version-([0-9.]+)-", readme)
    assert match is not None
    assert match.group(1) == __version__
