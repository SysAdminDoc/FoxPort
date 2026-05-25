import os

import pytest

from foxport.fileops import (
    replace_file_atomic,
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
