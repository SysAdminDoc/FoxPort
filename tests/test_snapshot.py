"""Tests for the .fxport snapshot bundle (plain + encrypted)."""

import io
import json
import zipfile

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


def test_create_snapshot_refuses_to_write_inside_input_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    with pytest.raises(ValueError, match="inside its own input directory"):
        create_snapshot(src, src / "nested.fxport", source_label="x", target_label="y")


def test_restore_refuses_non_empty_output_without_overwrite(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)
    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y")

    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "keep.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="output directory is not empty"):
        restore_snapshot(bundle, restored)


def test_restore_overwrite_allows_non_empty_output(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)
    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y")

    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "keep.txt").write_text("existing", encoding="utf-8")

    manifest = restore_snapshot(bundle, restored, overwrite=True)

    assert manifest.source_label == "x"
    assert (restored / "keep.txt").read_text(encoding="utf-8") == "existing"
    assert (restored / "passwords.csv").exists()


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


def test_wrong_passphrase_raises_value_error_with_friendly_message(tmp_path):
    """The CLI ``restore`` only catches ``ValueError`` — without the
    InvalidTag → ValueError translation in ``_decrypt_bundle`` a wrong
    passphrase would surface as an uncaught crypto traceback to the
    end user. Pin the friendly-error contract so the CLI surfaces
    "wrong passphrase or corrupted bundle".
    """

    src = tmp_path / "src"
    src.mkdir()
    _populate(src)

    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y", passphrase="correct")

    with pytest.raises(ValueError, match="wrong passphrase or corrupted bundle"):
        restore_snapshot(bundle, tmp_path / "restored2", passphrase="wrong")


def test_truncated_encrypted_bundle_raises_value_error(tmp_path):
    """A bundle missing the AES-GCM tag is malformed; the helper should
    translate the crypto failure into a friendly ValueError (CLI catch).
    """

    from foxport.snapshot import _MAGIC_ENCRYPTED, _decrypt_bundle
    # Magic + 4-byte iters + 16-byte salt + 12-byte nonce — no ciphertext.
    blob = _MAGIC_ENCRYPTED + (200_000).to_bytes(4, "little") + b"\x00" * 16 + b"\x00" * 12
    with pytest.raises(ValueError, match="truncated or malformed"):
        _decrypt_bundle(blob, "anything")


def _craft_bundle(tmp_path, entries: list[tuple[str, bytes]],
                  manifest_files: list[dict] | None = None):
    """Build a hand-rolled plain .fxport bundle with arbitrary entries +
    manifest, so we can test the hardening checks against tampering."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        files = manifest_files if manifest_files is not None else [
            {"path": name, "size": len(data), "sha256": ""}
            for name, data in entries if name != "manifest.json"
        ]
        zf.writestr("manifest.json", json.dumps({
            "foxport_version": "test",
            "created_iso": "2026-01-01T00:00:00+00:00",
            "source_label": "src",
            "target_label": "dst",
            "encrypted": False,
            "files": files,
        }))
    bundle = tmp_path / "crafted.fxport"
    bundle.write_bytes(buf.getvalue())
    return bundle


def test_restore_rejects_path_traversal_via_parent(tmp_path):
    bundle = _craft_bundle(tmp_path, [("../escape.txt", b"x")])
    with pytest.raises(ValueError, match="suspicious path"):
        restore_snapshot(bundle, tmp_path / "out")


def test_restore_rejects_absolute_paths(tmp_path):
    # POSIX absolute path. On Windows this isn't strictly is_absolute(),
    # but the resolved-target/relative_to safety net still rejects it.
    bundle = _craft_bundle(tmp_path, [("/etc/passwd", b"x")])
    with pytest.raises(ValueError, match="suspicious path|outside out_dir"):
        restore_snapshot(bundle, tmp_path / "out")


def test_restore_verifies_sha256(tmp_path):
    # Manifest claims a digest the file content doesn't actually match.
    bundle = _craft_bundle(
        tmp_path,
        [("good.txt", b"real content")],
        manifest_files=[{
            "path": "good.txt",
            "size": 12,
            "sha256": "deadbeef" + "0" * 56,  # 64 chars, definitely wrong
        }],
    )
    with pytest.raises(ValueError, match="integrity check failed"):
        restore_snapshot(bundle, tmp_path / "out")


def test_restore_ignores_unknown_manifest_keys(tmp_path):
    # An older or tampered bundle could carry extra top-level keys; we
    # should silently drop them rather than crash with TypeError.
    src = tmp_path / "src"
    src.mkdir()
    _populate(src)
    bundle = tmp_path / "out.fxport"
    create_snapshot(src, bundle, source_label="x", target_label="y")

    # Tamper: re-pack with an extra manifest key.
    blob = bundle.read_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        files = list(zf.namelist())
        contents = {n: zf.read(n) for n in files}
    manifest = json.loads(contents["manifest.json"])
    manifest["future_field"] = "ignore me"
    contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as zf:
        for name, data in contents.items():
            zf.writestr(name, data)
    bundle.write_bytes(out_buf.getvalue())

    # Should restore cleanly (extra key silently dropped).
    manifest_obj = restore_snapshot(bundle, tmp_path / "restored3")
    assert manifest_obj.source_label == "x"
