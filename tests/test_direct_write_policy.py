"""Tests for the conflict-review / direct-write-policy plumbing.

Policies thread from MigrationRequest
fields through the worker to the manifest. The dialog itself is a thin
shim around those fields; the heavy logic lives in the worker branches
and the manifest writer, which is what these tests pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_direct_write_policies_constant_exposes_values():
    """The DirectWritePolicy literal + the user-facing constant must
    enumerate exactly the policies the worker knows how to handle."""

    from foxport.migrate.conflicts import (
        DIRECT_WRITE_POLICIES,
        DIRECT_WRITE_POLICY_DEFAULT,
        DIRECT_WRITE_POLICY_LABELS,
    )

    assert DIRECT_WRITE_POLICIES == ("apply", "merge", "skip", "backup-only")
    assert DIRECT_WRITE_POLICY_DEFAULT == "apply"
    # Every policy must have a human-readable label so the dialog
    # never silently lands an empty dropdown row.
    assert set(DIRECT_WRITE_POLICY_LABELS) == set(DIRECT_WRITE_POLICIES)
    for label in DIRECT_WRITE_POLICY_LABELS.values():
        assert label, "empty label leaks into the GUI dropdown"


def test_migration_request_defaults_policy_to_apply():
    """A MigrationRequest constructed without explicit policy fields
    must default each to "apply" — pre-v1.3.3 callers stay unaffected.
    """

    from foxport.gui.workers import MigrationRequest

    req = MigrationRequest(
        source=object(),    # type: ignore[arg-type]  — never read in this test
        target=None,
        out_root=Path("/tmp"),
        do_passwords=False,
        do_bookmarks=False,
        do_extensions=False,
    )
    assert req.policy_passwords == "apply"
    assert req.policy_cookies == "apply"
    assert req.policy_history == "apply"
    assert req.policy_open_tabs == "apply"


def test_manifest_run_artifact_records_direct_write_policy():
    """RunArtifact.direct_write_policy is empty for non-direct-write
    artifacts and carries the chosen policy for direct-write ones."""

    from foxport.manifest import RunArtifact, build_artifact

    # Non-direct-write artifact — field stays empty.
    assert RunArtifact(
        key="bookmarks",
        path="bookmarks.html",
        size_bytes=10,
        sha256="abc",
    ).direct_write_policy == ""

    # Direct-write artifact with policy passed through build_artifact.
    p = Path("/tmp/places.sqlite")


def test_build_artifact_threads_policy_through(tmp_path):
    """build_artifact records the policy verbatim on the RunArtifact so
    the worker manifest writer can surface it without an extra dict."""

    from foxport.manifest import build_artifact

    f = tmp_path / "places.sqlite"
    f.write_bytes(b"SQLite format 3\x00")
    art = build_artifact(
        "history", f, tmp_path,
        direct_write=True,
        direct_write_policy="backup-only",
    )
    assert art.direct_write_policy == "backup-only"
    assert art.direct_write is True


def test_run_manifest_serializes_direct_write_policy(tmp_path):
    """The on-disk manifest.json carries direct_write_policy verbatim
    so a snapshot consumer (or the future conflict-aware restore) can
    tell whether a category was applied / skipped / backed-up."""

    import json
    from foxport.manifest import RunManifest, build_artifact, write_manifest

    f = tmp_path / "cookies.sqlite"
    f.write_bytes(b"SQLite format 3\x00")
    art = build_artifact(
        "cookies", f, tmp_path,
        direct_write=True,
        direct_write_policy="skip",
    )
    manifest = RunManifest(
        created_iso="2026-05-25T00:00:00+00:00",
        source_label="src", target_label="tgt",
        artifacts=[art],
    )
    path = write_manifest(manifest, tmp_path)
    rendered = json.loads(path.read_text(encoding="utf-8"))
    assert rendered["artifacts"][0]["direct_write_policy"] == "skip"


def test_run_manifest_load_tolerates_legacy_artifact_without_policy(tmp_path):
    """Older manifests (v1.3.0 – v1.3.2) didn't have the
    direct_write_policy field. load_manifest must default it to empty
    rather than blowing up on missing key."""

    import json
    from foxport.manifest import load_manifest

    legacy = {
        "schema_version": 1,
        "foxport_version": "1.3.1",
        "created_iso": "2026-05-24T00:00:00+00:00",
        "source_label": "src", "target_label": "tgt",
        "direction": "forward", "dry_run": False,
        "items_requested": ["cookies"],
        "network": {},
        "artifacts": [{
            "key": "cookies",
            "path": "cookies.sqlite",
            "size_bytes": 16,
            "sha256": "abc",
            "sensitivity": "sensitive",
            "action_kind": "reveal",
            "count": 5,
            "direct_write": True,
            "backup_path": None,
            "notes": None,
        }],
        "warnings": [],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = load_manifest(path)
    assert loaded.artifacts[0].direct_write_policy == ""


def test_redact_manifest_preserves_direct_write_policy():
    """redact_manifest() builds a new RunArtifact; verify the
    direct_write_policy field is copied across instead of dropping
    silently."""

    from foxport.manifest import RunArtifact, RunManifest, redact_manifest

    art = RunArtifact(
        key="passwords",
        path="passwords.csv",
        size_bytes=10,
        sha256="abc",
        direct_write=True,
        direct_write_policy="backup-only",
        backup_path="/tmp/x",
    )
    manifest = RunManifest(
        created_iso="2026-05-25T00:00:00+00:00",
        source_label="src", target_label="tgt",
        artifacts=[art],
    )
    out = redact_manifest(manifest)
    assert out.artifacts[0].direct_write_policy == "backup-only"
