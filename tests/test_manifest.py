"""Unit tests for the run manifest writer."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from foxport.manifest import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    RunArtifact,
    RunManifest,
    build_artifact,
    load_manifest,
    write_manifest,
)


def test_build_artifact_records_path_size_and_digest(tmp_path: Path):
    f = tmp_path / "passwords.csv"
    payload = b"url,username,password\nhttps://example.com,me,hunter2\n"
    f.write_bytes(payload)

    artifact = build_artifact("passwords", f, tmp_path)

    assert artifact.key == "passwords"
    assert artifact.path == "passwords.csv"
    assert artifact.size_bytes == len(payload)
    assert artifact.sha256 == sha256(payload).hexdigest()
    # passwords carry plaintext — sensitivity label must reflect that for
    # the Done UI / generated README to surface cleanup copy.
    assert artifact.sensitivity == "sensitive"
    assert artifact.action_kind == "open"
    assert artifact.direct_write is False
    assert artifact.backup_path is None


def test_build_artifact_uses_reveal_for_sqlite_categories(tmp_path: Path):
    f = tmp_path / "places.sqlite"
    f.write_bytes(b"SQLite format 3\x00")
    a = build_artifact("history", f, tmp_path)
    assert a.action_kind == "reveal"
    assert a.sensitivity == "sensitive"


def test_build_artifact_records_direct_write_backup(tmp_path: Path):
    f = tmp_path / "places.sqlite"
    f.write_bytes(b"x")
    backup = Path("/target/profile/places.foxport-backup-1700000000.sqlite")
    a = build_artifact(
        "history",
        f,
        tmp_path,
        count=42,
        direct_write=True,
        backup_path=backup,
        notes="favicons moved aside",
    )
    assert a.direct_write
    assert a.backup_path == str(backup)
    assert a.count == 42
    assert a.notes == "favicons moved aside"


def test_build_artifact_relative_path_with_subdir(tmp_path: Path):
    sub = tmp_path / "search-engines"
    sub.mkdir()
    f = sub / "google.xml"
    f.write_bytes(b"<OpenSearchDescription/>")
    a = build_artifact("search_engines", f, tmp_path)
    assert a.path == "search-engines/google.xml"


def test_write_then_load_manifest_round_trip(tmp_path: Path):
    f = tmp_path / "bookmarks.html"
    f.write_text("<HTML>", encoding="utf-8")
    manifest = RunManifest(
        created_iso="2026-05-24T12:00:00+00:00",
        source_label="Brave - Default",
        target_label="Firefox - default-release",
        direction="forward",
        items_requested=["bookmarks"],
        network={"addons.mozilla.org": "disabled"},
        artifacts=[build_artifact("bookmarks", f, tmp_path, count=12)],
    )
    path = write_manifest(manifest, tmp_path)
    assert path.name == MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["foxport_version"]
    assert payload["artifacts"][0]["key"] == "bookmarks"

    loaded = load_manifest(path)
    assert loaded.source_label == "Brave - Default"
    assert loaded.direction == "forward"
    assert loaded.artifacts[0].key == "bookmarks"
    assert loaded.artifacts[0].count == 12


def test_load_manifest_tolerates_unknown_top_level_keys(tmp_path: Path):
    """Forward-compatible: a manifest with newer fields shouldn't TypeError."""

    raw = {
        "schema_version": 1,
        "foxport_version": "9.9.9",
        "created_iso": "2030-01-01T00:00:00+00:00",
        "source_label": "Future Chrome",
        "target_label": "Future Firefox",
        "direction": "forward",
        "dry_run": False,
        "items_requested": [],
        "network": {},
        "artifacts": [],
        "warnings": [],
        # Fields introduced after the current schema:
        "telemetry_session_id": "abc",
        "experiments": ["foo"],
    }
    path = tmp_path / MANIFEST_FILENAME
    path.write_text(json.dumps(raw), encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.foxport_version == "9.9.9"


def test_load_manifest_tolerates_unknown_artifact_keys(tmp_path: Path):
    """Per-artifact forward compat: extra fields drop without raising."""

    raw = {
        "schema_version": 1,
        "foxport_version": "1.3.0",
        "created_iso": "2026-05-24T00:00:00+00:00",
        "source_label": "X", "target_label": "Y", "direction": "forward",
        "dry_run": False, "items_requested": [], "network": {},
        "warnings": [],
        "artifacts": [{
            "key": "passwords",
            "path": "passwords.csv",
            "size_bytes": 10,
            "sha256": "0" * 64,
            "sensitivity": "sensitive",
            "action_kind": "open",
            "count": 5,
            "direct_write": False,
            "backup_path": None,
            "notes": None,
            # Future-only field:
            "encryption_status": "v11",
        }],
    }
    path = tmp_path / MANIFEST_FILENAME
    path.write_text(json.dumps(raw), encoding="utf-8")
    manifest = load_manifest(path)
    assert len(manifest.artifacts) == 1
    assert manifest.artifacts[0].count == 5


def test_manifest_never_contains_plaintext_secret_values(tmp_path: Path):
    """Sanity guard: a built artifact records bytes + digest, not the body."""

    f = tmp_path / "passwords.csv"
    secret = b"url,username,password\nhttps://bank.example,me,hunter2\n"
    f.write_bytes(secret)

    manifest = RunManifest(
        created_iso="2026-05-24T00:00:00+00:00",
        source_label="x", target_label="y",
        artifacts=[build_artifact("passwords", f, tmp_path)],
    )
    path = write_manifest(manifest, tmp_path)
    rendered = path.read_text(encoding="utf-8")
    assert "hunter2" not in rendered
    assert "bank.example" not in rendered
