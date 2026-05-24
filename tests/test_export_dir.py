"""Tests for ``make_export_dir`` path-traversal hardening."""

import pytest

from foxport.browsers.firefox import _safe_slug, make_export_dir


def test_safe_slug_strips_traversal():
    assert _safe_slug("..") == "profile"
    assert _safe_slug("../etc/passwd") == "etc_passwd"
    assert _safe_slug("/abs/path") == "abs_path"


def test_safe_slug_preserves_clean_text():
    assert _safe_slug("Brave-Default") == "Brave-Default"
    assert _safe_slug("Microsoft Edge Beta") == "Microsoft_Edge_Beta"


def test_safe_slug_strips_nuls_and_unicode_whitespace():
    assert "\x00" not in _safe_slug("evil\x00null")
    # U+2028 LINE SEPARATOR collapses to underscore.
    assert _safe_slug("a b") == "a_b"


def test_safe_slug_caps_length():
    long = "x" * 500
    out = _safe_slug(long)
    assert len(out) == 120


def test_make_export_dir_creates_path(tmp_path):
    out = make_export_dir(tmp_path, "Brave/Default", "Firefox/default-release")
    assert out.exists() and out.is_dir()
    assert out.parent == tmp_path
    # Slashes flattened to underscores.
    assert "Brave_Default" in out.name


def test_make_export_dir_rejects_traversal(tmp_path):
    """Even with poisoned labels, the result lives under tmp_path."""
    out = make_export_dir(tmp_path, "../../evil", "Firefox")
    out_resolved = out.resolve()
    parent_resolved = tmp_path.resolve()
    # Must be inside the parent we passed.
    assert str(out_resolved).startswith(str(parent_resolved))
