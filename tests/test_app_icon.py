"""Tests for the bundled raster icon set + runtime icon resolution."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest


def test_icon_ico_ships_in_assets():
    """Release build expects ``assets/icon.ico`` next to the spec file."""
    repo_root = Path(__file__).resolve().parents[1]
    ico = repo_root / "assets" / "icon.ico"
    assert ico.is_file(), f"expected raster icon at {ico}"


def test_icon_ico_embeds_signed_release_frames():
    """The ICO must embed the multi-resolution frames PyInstaller +
    Explorer use (16/24/32/48/64/128/256).

    ICO header layout: 6-byte ICONDIR, then N * 16-byte ICONDIRENTRY.
    Each entry's first two bytes are width / height (0 means 256).
    """
    repo_root = Path(__file__).resolve().parents[1]
    data = (repo_root / "assets" / "icon.ico").read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00", "not a Windows ICO file"
    count = struct.unpack_from("<H", data, 4)[0]
    sizes: set[int] = set()
    for i in range(count):
        w = data[6 + i * 16]
        h = data[6 + i * 16 + 1]
        # 0 in the ICONDIRENTRY width/height byte means 256 px.
        sizes.add(256 if w == 0 else w)
        assert (256 if h == 0 else h) == (256 if w == 0 else w), \
            "FoxPort icons are square"
    assert {16, 24, 32, 48, 64, 128, 256} <= sizes, (
        f"missing required ICO frames; got {sorted(sizes)}"
    )


def test_icon_png_favicons_present():
    """PNG favicons ship alongside the ICO so sites with `<link rel="icon">`
    can point at the same artwork without re-rendering."""
    repo_root = Path(__file__).resolve().parents[1]
    for name in ("icon-16.png", "icon-32.png", "icon-256.png"):
        path = repo_root / "assets" / name
        assert path.is_file(), f"expected {path}"
        # Minimal sanity check: PNG magic.
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"


def test_resolve_app_icon_path_finds_repo_asset():
    """Dev runs (``python -m foxport``) must resolve the source-tree icon."""
    from foxport.app import resolve_app_icon_path

    repo_root = Path(__file__).resolve().parents[1]
    expected = repo_root / "assets" / "icon.ico"
    resolved = resolve_app_icon_path()
    assert resolved is not None
    assert resolved.resolve() == expected.resolve()


def test_resolve_app_icon_path_prefers_meipass(monkeypatch, tmp_path):
    """Inside a PyInstaller bundle ``sys._MEIPASS`` wins over source layout."""
    from foxport import app as app_mod

    fake_meipass = tmp_path / "meipass"
    (fake_meipass / "assets").mkdir(parents=True)
    fake_icon = fake_meipass / "assets" / "icon.ico"
    fake_icon.write_bytes(b"fake-ico")

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    resolved = app_mod.resolve_app_icon_path()
    assert resolved is not None
    assert resolved == fake_icon


def test_resolve_app_icon_path_returns_none_when_missing(monkeypatch, tmp_path):
    """When no icon ships, callers fall back to the OS default cleanly."""
    from foxport import app as app_mod

    # Point _MEIPASS at an empty dir + monkeypatch the package_dir
    # lookups so nothing matches.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(empty), raising=False)
    monkeypatch.setattr(
        app_mod, "__file__", str(empty / "foxport" / "app.py"), raising=False
    )
    assert app_mod.resolve_app_icon_path() is None


def test_generate_icon_regenerates_assets(tmp_path, monkeypatch):
    """``scripts/generate_icon.py`` must produce a deterministic asset set."""
    # Importing the module-level OUT path and overriding via monkeypatch
    # avoids re-running the generator against the repo's checked-in
    # assets (which would race with parallel test runs).
    pytest.importorskip("PIL")
    from scripts import generate_icon as gen

    out = tmp_path / "assets"
    monkeypatch.setattr(gen, "OUT", out)
    rc = gen.main()
    assert rc == 0
    for name in ("icon.ico", "icon-16.png", "icon-32.png", "icon-256.png"):
        assert (out / name).is_file(), f"generator did not write {name}"
