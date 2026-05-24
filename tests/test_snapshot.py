"""Tests for the .fxport snapshot bundle (plain + encrypted)."""

import pytest

from foxport.snapshot import create_snapshot, restore_snapshot


def _populate(input_dir):
    """Drop a small fixture tree into ``input_dir``."""
    (input_dir / "passwords.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    (input_dir / "subdir").mkdir()
    (input_dir / "subdir" / "bookmarks.html").write_text("<!DOCTYPE x>", encoding="utf-8")


def test_plain_snapshot_round_trips(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="Chrome/Default", target_label="Firefox/default")

    restored = tmp_path / "restored"
    manifest = restore_snapshot(bundle, restored)

    assert (restored / "passwords.csv").read_text(encoding="utf-8") == "a,b,c\n1,2,3\n"
    assert (restored / "subdir" / "bookmarks.html").read_text(encoding="utf-8") == "<!DOCTYPE x>"
    assert manifest.source_label == "Chrome/Default"
    assert manifest.target_label == "Firefox/default"
    assert manifest.encrypted is False
    assert len(manifest.files) == 2


def test_encrypted_snapshot_round_trips(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y",
                    passphrase="hunter2")

    restored = tmp_path / "restored"
    manifest = restore_snapshot(bundle, restored, passphrase="hunter2")
    assert (restored / "passwords.csv").exists()
    assert manifest.encrypted is True


def test_encrypted_bundle_requires_passphrase(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y", passphrase="pw")

    with pytest.raises(ValueError, match="requires --passphrase"):
        restore_snapshot(bundle, tmp_path / "restored1")


def test_wrong_passphrase_fails(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y", passphrase="correct")

    with pytest.raises(Exception):
        restore_snapshot(bundle, tmp_path / "restored2", passphrase="wrong")
