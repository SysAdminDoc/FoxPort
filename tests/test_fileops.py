import os
from pathlib import Path

import pytest

from foxport.fileops import (
    original_from_backup,
    replace_file_atomic,
    restore_from_backup,
    timestamped_backup_path,
    write_bytes_atomic,
)


def test_write_bytes_atomic_replaces_existing_file(tmp_path):
    target = tmp_path / "artifact.txt"
    target.write_text("old", encoding="utf-8")

    write_bytes_atomic(target, b"new")

    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".artifact.txt.foxport-*"))


def test_replace_file_atomic_preserves_target_when_source_read_fails(tmp_path):
    target = tmp_path / "artifact.txt"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        replace_file_atomic(tmp_path / "missing.txt", target)

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".artifact.txt.foxport-*"))


def test_timestamped_backup_path_returns_none_when_missing(tmp_path):
    assert timestamped_backup_path(tmp_path / "missing.sqlite") is None


def test_timestamped_backup_path_preserves_suffix(tmp_path):
    """Naming convention shared by every direct-write helper:
    ``{stem}.foxport-backup-{mtime}{suffix}`` next to the target.
    """

    target = tmp_path / "logins.json"
    target.write_text("{}", encoding="utf-8")
    fixed_mtime = 1_234_567_890
    os.utime(target, (fixed_mtime, fixed_mtime))

    backup = timestamped_backup_path(target)

    assert backup is not None
    assert backup.parent == tmp_path
    assert backup.name == f"logins.foxport-backup-{fixed_mtime}.json"


def test_timestamped_backup_path_handles_extensionless(tmp_path):
    """Files without a suffix (e.g. Chromium's bare ``Login Data``) get
    the timestamp inserted after the bare stem with no trailing suffix.
    """

    target = tmp_path / "Login Data"
    target.write_text("blob", encoding="utf-8")
    fixed_mtime = 1_700_000_000
    os.utime(target, (fixed_mtime, fixed_mtime))

    backup = timestamped_backup_path(target)

    assert backup is not None
    assert backup.name == f"Login Data.foxport-backup-{fixed_mtime}"


def test_write_bytes_atomic_preserves_target_when_replace_fails(tmp_path, monkeypatch):
    """A torn write (here simulated by forcing ``tmp.replace`` to raise) must:

    1. Leave the original target file intact (the staged file is in a
       sibling temp file until the final replace step).
    2. Clean up the orphan ``.{name}.foxport-*`` tmpfile so the directory
       doesn't accumulate garbage across crashes.

    This is the v1.3 invariant that lets a half-finished migration
    abandon partial CSV / SQLite / JSON / HTML artifacts safely — the
    README.txt and manifest.json never reference a corrupt file.
    """

    from foxport import fileops

    target = tmp_path / "artifact.csv"
    target.write_text("old content", encoding="utf-8")

    real_replace = Path.replace

    def boom(self, *args, **kwargs):
        # Only fail the FIRST replace call (the one against ``artifact.csv``);
        # the post-error unlink path uses Path.unlink, not replace, so this
        # branch is only ever taken once per test.
        raise OSError("disk full simulation")

    monkeypatch.setattr(Path, "replace", boom)

    with pytest.raises(OSError, match="disk full"):
        fileops.write_bytes_atomic(target, b"new content")

    # Original file untouched.
    assert target.read_text(encoding="utf-8") == "old content"
    # No `.artifact.csv.foxport-*` orphans left behind.
    orphans = list(tmp_path.glob(".artifact.csv.foxport-*"))
    assert orphans == [], f"orphan tmpfiles after failed replace: {orphans}"


def test_replace_file_atomic_preserves_target_when_replace_fails(tmp_path, monkeypatch):
    """Same invariant for the source-on-disk variant: a torn copy_atomic
    must leave the existing target intact and leave no orphan tmpfile."""

    from foxport import fileops

    target = tmp_path / "logins.json"
    target.write_text('{"existing": true}', encoding="utf-8")
    source = tmp_path / "src.json"
    source.write_text('{"new": true}', encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise OSError("rename failed")

    monkeypatch.setattr(Path, "replace", boom)

    with pytest.raises(OSError, match="rename failed"):
        fileops.replace_file_atomic(source, target)

    assert target.read_text(encoding="utf-8") == '{"existing": true}'
    orphans = list(tmp_path.glob(".logins.json.foxport-*"))
    assert orphans == [], f"orphan tmpfiles after failed replace: {orphans}"


# --------------------------- original_from_backup ----------------------------

def test_original_from_backup_resolves_suffixed_file(tmp_path: Path):
    """logins.foxport-backup-1700000000.json -> logins.json"""

    backup = tmp_path / "logins.foxport-backup-1700000000.json"
    assert original_from_backup(backup) == tmp_path / "logins.json"


def test_original_from_backup_resolves_extensionless_file(tmp_path: Path):
    """Login Data.foxport-backup-1700000000 -> Login Data"""

    backup = tmp_path / "Login Data.foxport-backup-1700000000"
    assert original_from_backup(backup) == tmp_path / "Login Data"


def test_original_from_backup_rejects_non_backup_name(tmp_path: Path):
    """A regular file that doesn't match the convention returns None
    so the CLI restore-backup can prompt the user for an explicit target."""

    assert original_from_backup(tmp_path / "logins.json") is None
    assert original_from_backup(tmp_path / "logins.backup.json") is None


def test_restore_from_backup_atomically_overwrites_target(tmp_path: Path):
    """End-to-end: backup file copied over the original target via
    atomic-replace; original content is gone, backup content lands."""

    target = tmp_path / "logins.json"
    target.write_text('{"current": true}', encoding="utf-8")
    backup = tmp_path / "logins.foxport-backup-1700000000.json"
    backup.write_text('{"previous": true}', encoding="utf-8")

    restored = restore_from_backup(backup)

    assert restored == target
    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    # Backup itself is left alone — copied, not moved, so the user
    # can re-undo if they change their mind again.
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == '{"previous": true}'


def test_restore_from_backup_with_explicit_target(tmp_path: Path):
    """When the user supplies --target explicitly, that path wins
    over the auto-resolved one."""

    backup = tmp_path / "logins.foxport-backup-1700000000.json"
    backup.write_text("backup contents", encoding="utf-8")
    explicit = tmp_path / "elsewhere" / "renamed.json"

    restored = restore_from_backup(backup, target_path=explicit)

    assert restored == explicit
    assert explicit.read_text(encoding="utf-8") == "backup contents"


def test_restore_from_backup_missing_backup_raises(tmp_path: Path):
    """The CLI surfaces FileNotFoundError as a clean error code 2."""

    with pytest.raises(FileNotFoundError):
        restore_from_backup(tmp_path / "missing.foxport-backup-1.json")


def test_restore_from_backup_non_convention_name_requires_explicit_target(tmp_path: Path):
    """A file whose name doesn't match the convention can't be auto-
    resolved; the caller must pass --target."""

    weird = tmp_path / "not-a-backup.json"
    weird.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="foxport-backup naming convention"):
        restore_from_backup(weird)
