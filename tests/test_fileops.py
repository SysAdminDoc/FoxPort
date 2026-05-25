import pytest

from foxport.fileops import replace_file_atomic, write_bytes_atomic


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
