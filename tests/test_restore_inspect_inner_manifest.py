"""The RestoreInspectDialog helpers surface the inner per-run manifest.

A v1.3+ migration drops a `manifest.json` next to README.txt inside its
output folder; the snapshot bundle includes that file verbatim. The
inspect dialog now reads it and surfaces direction, items, network use,
warnings, and per-artifact sensitivity so the user sees what's about to
land BEFORE clicking Restore.

These tests pin the two helpers headlessly so the GUI never spins up.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

# Skip the whole module on Linux runners without an X server. The GUI
# never paints — we only construct QLabel instances — but Qt insists on
# a QApplication being available.
pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication  # noqa: E402  (after importorskip)


@pytest.fixture(scope="session")
def _qapp():
    """Reuse one offscreen QApplication for every test in this module."""
    app = QApplication.instance() or QApplication([])
    return app


def _build_zip(files: dict[str, bytes]) -> zipfile.ZipFile:
    """Build an in-memory ZipFile loaded with ``files``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in files.items():
            zf.writestr(name, payload)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


def test_try_read_inner_run_manifest_returns_v13_payload(_qapp):
    from foxport.gui.dialogs import _try_read_inner_run_manifest

    outer = json.dumps({
        "foxport_version": "1.3.0",
        "files": [{"path": "run/manifest.json", "size": 5, "sha256": "deadbeef"}],
    }).encode("utf-8")
    inner_run = json.dumps({
        "schema_version": 1,
        "foxport_version": "1.3.0",
        "direction": "forward",
        "items_requested": ["passwords", "bookmarks"],
        "network": {"addons.mozilla.org": "enabled"},
        "artifacts": [
            {"key": "passwords", "path": "run/passwords.csv",
             "sensitivity": "sensitive"},
        ],
        "warnings": [],
    }).encode("utf-8")

    with _build_zip({
        "manifest.json": outer,
        "run/manifest.json": inner_run,
        "run/passwords.csv": b"a,b,c\n",
    }) as zf:
        found = _try_read_inner_run_manifest(zf)

    assert found is not None
    assert found["schema_version"] == 1
    assert found["direction"] == "forward"


def test_try_read_inner_run_manifest_returns_none_for_legacy_bundle(_qapp):
    """Pre-v1.3 bundles only have the outer snapshot manifest — no inner one.
    The helper must return None so the dialog skips the Run details block.
    """
    from foxport.gui.dialogs import _try_read_inner_run_manifest

    outer = json.dumps({"foxport_version": "1.2.1", "files": []}).encode("utf-8")
    with _build_zip({
        "manifest.json": outer,
        "passwords.csv": b"x,y,z\n",
    }) as zf:
        assert _try_read_inner_run_manifest(zf) is None


def test_try_read_inner_run_manifest_ignores_non_schemaed_inner(_qapp):
    """A nested file named manifest.json that doesn't look like a RunManifest
    (no schema_version) must NOT be misidentified — otherwise an unrelated
    tool's manifest could spoof the Run details panel.
    """
    from foxport.gui.dialogs import _try_read_inner_run_manifest

    outer = json.dumps({"foxport_version": "1.3.0", "files": []}).encode("utf-8")
    spoof = json.dumps({"name": "not-a-foxport-run"}).encode("utf-8")
    with _build_zip({
        "manifest.json": outer,
        "subdir/manifest.json": spoof,
    }) as zf:
        assert _try_read_inner_run_manifest(zf) is None


def test_build_run_details_widget_html_escapes_untrusted_fields(_qapp):
    """The bundle is untrusted; the manifest came out of a possibly-tampered
    archive. Every value we surface must be HTML-escaped so a crafted
    label can't inject markup into the QLabel.
    """
    from foxport.gui.dialogs import _build_run_details_widget

    label = _build_run_details_widget({
        "direction": "<script>alert(1)</script>",
        "items_requested": ["<img src=x>"],
        "network": {"addons.mozilla.org": "<bad>"},
        "artifacts": [
            {"key": "<script>", "sensitivity": "sensitive"},
        ],
        "warnings": ["<warn>"],
    })

    rendered = label.text()
    assert "<script>" not in rendered or "&lt;script&gt;" in rendered
    assert "<img src=x>" not in rendered
    assert "&lt;" in rendered  # something got escaped
