"""End-to-end ``--json`` checks for every CLI subcommand that supports it.

The contract is the same on every command: a single JSON object on stdout,
no other lines; ``schema_version`` + ``foxport_version`` at the root;
never any plaintext secrets. Errors still go to stderr.

These tests drive the CLI through its ``main()`` entry point so a
regression in argparse wiring shows up here, not just in the per-command
helpers.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pytest


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    """Invoke ``foxport.cli.main(argv)`` and parse stdout as JSON."""
    from foxport.cli import main

    rc = main(argv)
    captured = capsys.readouterr()
    if not captured.out.strip():
        return rc, {}
    return rc, json.loads(captured.out)


def test_list_json_emits_schema_versioned_payload(capsys, monkeypatch):
    """`list --json` is the precedent for every other command's --json shape."""
    monkeypatch.setattr("foxport.cli.detect_chromium", lambda: [])
    monkeypatch.setattr("foxport.cli.detect_firefox", lambda: [])

    rc, payload = _run(["list", "--json"], capsys)

    assert rc == 0
    assert payload["schema_version"] == 1
    assert "foxport_version" in payload
    assert payload["chromium_sources"] == []
    assert payload["firefox_targets"] == []


def test_snapshot_json_round_trip(capsys, tmp_path: Path):
    """`snapshot --json` produces a payload with the bundle metadata."""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "passwords.csv").write_text("a,b,c\n", encoding="utf-8")
    out_bundle = tmp_path / "out.fxport"

    rc, payload = _run([
        "snapshot",
        "--input-dir", str(in_dir),
        "--out", str(out_bundle),
        "--source-label", "Brave/Default",
        "--target-label", "Firefox/default-release",
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["command"] == "snapshot"
    assert payload["schema_version"] == 1
    assert payload["out_path"] == str(out_bundle)
    assert payload["source"] == "Brave/Default"
    assert payload["target"] == "Firefox/default-release"
    assert payload["encrypted"] is False
    assert payload["files_count"] >= 1
    # No plaintext: the CSV body must not appear anywhere in the JSON
    # serialization. Catches the "we accidentally dumped the manifest's
    # full file content" regression class.
    assert "a,b,c" not in json.dumps(payload)


def test_restore_json_round_trip(capsys, tmp_path: Path):
    """`restore --json` round-trips a snapshot back to disk with a JSON receipt."""
    from foxport.snapshot import create_snapshot

    src = tmp_path / "src"
    src.mkdir()
    (src / "bookmarks.html").write_text("<!DOCTYPE x>", encoding="utf-8")

    bundle = tmp_path / "b.fxport"
    create_snapshot(
        src, bundle,
        source_label="Brave/Default",
        target_label="Firefox/default-release",
    )

    out = tmp_path / "restored"
    rc, payload = _run([
        "restore",
        "--snapshot", str(bundle),
        "--out-dir", str(out),
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["command"] == "restore"
    assert payload["schema_version"] == 1
    assert payload["files_count"] == 1
    assert (out / "bookmarks.html").is_file()
    assert payload["overwrite"] is False


def test_diff_json_payload_shape(capsys, monkeypatch, tmp_path: Path):
    """`diff --json` emits {passwords, bookmarks, extensions} blocks."""
    from foxport.browsers.detect import ChromiumProfile, FirefoxProfile

    source = ChromiumProfile(
        browser="Brave", family="chromium", profile_name="Default",
        profile_dir=tmp_path / "src", local_state=tmp_path / "ls",
        user_data_dir=tmp_path,
    )
    target = FirefoxProfile(
        browser="Firefox", family="firefox", profile_name="default-release",
        profile_dir=tmp_path / "ff", is_default=True,
    )
    monkeypatch.setattr("foxport.cli.detect_chromium", lambda: [source])
    monkeypatch.setattr("foxport.cli.detect_firefox", lambda: [target])

    # Stub diff_profiles so the test doesn't try to crack open a real
    # NSS / Chromium profile.
    from foxport.diff import ProfileDiff
    fake = ProfileDiff()
    fake.passwords_only_in_source = 3
    fake.passwords_in_both = 1
    fake.bookmark_urls_only_in_source = 7
    fake.bookmark_urls_in_both = 2
    fake.extensions_only_in_source = 0
    fake.extensions_in_both = 4
    fake.samples = {
        "passwords": ["https://x.com / alice"],
        "bookmarks": ["https://y.com"],
        "extensions": ["uBlock Origin (cjpalhd...)"],
    }
    monkeypatch.setattr("foxport.diff.diff_profiles", lambda *_a, **_kw: fake)

    rc, payload = _run([
        "diff",
        "--source", "Brave/Default",
        "--target", "Firefox/default-release",
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["command"] == "diff"
    assert payload["schema_version"] == 1
    assert payload["passwords"]["only_in_source"] == 3
    assert payload["bookmarks"]["only_in_source"] == 7
    assert payload["extensions"]["in_both"] == 4
    # Samples are URL + username only — confirm no field smells like a
    # plaintext password.
    blob = json.dumps(payload).lower()
    assert "password" not in blob.replace("passwords", "")


def test_restore_backup_command_round_trips(capsys, tmp_path: Path):
    """``restore-backup`` copies the named backup file over its
    original target. Auto-resolves the target name from the backup
    name convention; --target overrides; --json emits the schema-
    versioned receipt.
    """

    target = tmp_path / "logins.json"
    target.write_text('{"current": true}', encoding="utf-8")
    backup = tmp_path / "logins.foxport-backup-1700000000.json"
    backup.write_text('{"previous": true}', encoding="utf-8")

    rc, payload = _run([
        "restore-backup",
        "--backup", str(backup),
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["command"] == "restore-backup"
    assert payload["schema_version"] == 1
    assert payload["backup"] == str(backup)
    assert payload["target"] == str(target)
    assert payload["explicit_target"] is False
    assert target.read_text(encoding="utf-8") == '{"previous": true}'


def test_restore_backup_command_with_explicit_target(capsys, tmp_path: Path):
    """``--target`` overrides the auto-resolved path so a user can
    restore into a renamed / relocated file."""

    backup = tmp_path / "logins.foxport-backup-1.json"
    backup.write_text("payload", encoding="utf-8")
    explicit = tmp_path / "different.json"

    rc, payload = _run([
        "restore-backup",
        "--backup", str(backup),
        "--target", str(explicit),
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["target"] == str(explicit)
    assert payload["explicit_target"] is True
    assert explicit.read_text(encoding="utf-8") == "payload"


def test_restore_backup_command_rejects_missing_backup(capsys, tmp_path: Path):
    rc, _payload = _run([
        "restore-backup",
        "--backup", str(tmp_path / "does-not-exist.foxport-backup-1.json"),
        "--json",
    ], capsys)
    # Exit 2 — the CLI's standard "user error" code (matches every
    # other subcommand's missing-file behavior).
    assert rc == 2


def test_import_bookmarks_json_payload(capsys, tmp_path: Path):
    """`import-bookmarks --json` mirrors every other action subcommand's
    JSON contract: a single object on stdout, command name + schema
    version at the root, no secrets in the payload.
    """

    # Minimal Netscape Bookmark fixture — the parser is regex-based and
    # accepts any properly-tagged anchor under the well-known DOCTYPE.
    src = tmp_path / "bookmarks.html"
    src.write_text(
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
        "<DL><p>"
        '<DT><A HREF="https://example.com/x" ADD_DATE="1700000000">Example</A>'
        "</DL><p>\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.firefox.html"

    rc, payload = _run([
        "import-bookmarks",
        "--input", str(src),
        "--out", str(out),
        "--json",
    ], capsys)

    assert rc == 0
    assert payload["command"] == "import-bookmarks"
    assert payload["schema_version"] == 1
    assert payload["input_format"] == "netscape-html"
    assert payload["parsed_count"] == 1
    assert payload["out_path"] == str(out)
    assert out.is_file()


def test_schema_versions_constants_export(capsys):
    """`_JSON_SCHEMA_VERSIONS` defines every command's schema version
    so a stray bump shows up in a single place.
    """
    from foxport.cli import _JSON_SCHEMA_VERSIONS

    # Every supported command appears in the dict.
    assert set(_JSON_SCHEMA_VERSIONS.keys()) >= {
        "list", "migrate", "migrate-reverse", "diff",
        "snapshot", "restore", "import-bookmarks",
        "restore-backup",
    }
    # And all currently sit at v1.
    for cmd, version in _JSON_SCHEMA_VERSIONS.items():
        assert isinstance(version, int)
        assert version >= 1
