"""Browser-snapshot bundle (``.fxport``) — zip-around a migration's
output folder for portable backup/restore.

A ``.fxport`` is just a ZIP archive of every artifact FoxPort emitted
during a single migration run, with a ``manifest.json`` describing the
source/target/date/tool-version + a digest per file. Restore = unzip the
bundle, then point FoxPort's existing direct-write paths at the
restored artifacts.

This is **not** a Firefox-Sync replacement. It's a portable "copy of my
browser state at point in time" — useful for OS reinstalls, switching
machines, archiving before account churn, or sharing a clean
configuration with a teammate.

Optional passphrase encryption uses PBKDF2-HMAC-SHA256 (200k iterations,
16-byte random salt per bundle) → AES-256-GCM over the inner ZIP bytes.
The encrypted bundle adds a ``foxport-encrypted-v1`` magic, salt, and
nonce alongside the ciphertext + tag.
"""

from __future__ import annotations

import io
import json
import secrets
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from foxport import __version__


_MAGIC_ENCRYPTED = b"FXP\x00enc\x00v1\x00"
_MAGIC_ENCRYPTED_LEN = len(_MAGIC_ENCRYPTED)
_PBKDF2_ITERATIONS = 200_000
_SALT_LEN = 16
_NONCE_LEN = 12


@dataclass
class SnapshotManifest:
    foxport_version: str
    created_iso: str
    source_label: str
    target_label: str
    files: list[dict]                     # [{"path": ..., "size": ..., "sha256": ...}]
    encrypted: bool = False


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_manifest(input_dir: Path, source_label: str, target_label: str,
                    encrypted: bool) -> SnapshotManifest:
    files: list[dict] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(input_dir).as_posix()
        files.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": _digest(path),
        })
    return SnapshotManifest(
        foxport_version=__version__,
        created_iso=datetime.now(timezone.utc).isoformat(),
        source_label=source_label,
        target_label=target_label,
        files=files,
        encrypted=encrypted,
    )


def _zip_bytes(input_dir: Path, manifest: SnapshotManifest) -> bytes:
    """Return the inner ZIP as bytes (file content + manifest.json)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in manifest.files:
            path = input_dir / entry["path"]
            zf.write(path, arcname=entry["path"])
        zf.writestr(
            "manifest.json",
            json.dumps({
                "foxport_version": manifest.foxport_version,
                "created_iso": manifest.created_iso,
                "source_label": manifest.source_label,
                "target_label": manifest.target_label,
                "encrypted": manifest.encrypted,
                "files": manifest.files,
            }, indent=2),
        )
    return buf.getvalue()


def _encrypt_bundle(inner: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = secrets.token_bytes(_SALT_LEN)
    nonce = secrets.token_bytes(_NONCE_LEN)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = kdf.derive(passphrase.encode("utf-8"))
    aes = AESGCM(key)
    ct = aes.encrypt(nonce, inner, _MAGIC_ENCRYPTED)
    return (
        _MAGIC_ENCRYPTED
        + struct.pack("<I", _PBKDF2_ITERATIONS)
        + salt
        + nonce
        + ct
    )


def _decrypt_bundle(blob: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    if not blob.startswith(_MAGIC_ENCRYPTED):
        raise ValueError("not a FoxPort encrypted snapshot")
    offset = _MAGIC_ENCRYPTED_LEN
    (iterations,) = struct.unpack_from("<I", blob, offset)
    offset += 4
    salt = blob[offset: offset + _SALT_LEN]
    offset += _SALT_LEN
    nonce = blob[offset: offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ct = blob[offset:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = kdf.derive(passphrase.encode("utf-8"))
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, _MAGIC_ENCRYPTED)


def create_snapshot(
    input_dir: Path,
    out_path: Path,
    *,
    source_label: str,
    target_label: str,
    passphrase: str | None = None,
) -> SnapshotManifest:
    """Bundle ``input_dir`` into a ``.fxport`` archive.

    When ``passphrase`` is given, the resulting file is the encrypted
    layout (magic + iterations + salt + nonce + AES-GCM ciphertext);
    otherwise it's a plain ZIP.
    """
    manifest = _build_manifest(input_dir, source_label, target_label,
                                encrypted=bool(passphrase))
    inner = _zip_bytes(input_dir, manifest)
    if passphrase:
        out_path.write_bytes(_encrypt_bundle(inner, passphrase))
    else:
        out_path.write_bytes(inner)
    return manifest


def restore_snapshot(
    bundle_path: Path,
    out_dir: Path,
    *,
    passphrase: str | None = None,
) -> SnapshotManifest:
    """Unpack a ``.fxport`` bundle into ``out_dir``. Returns the manifest.

    If the bundle starts with the encrypted magic, ``passphrase`` is
    required. Plain bundles are detected by ``zipfile.is_zipfile``.
    """
    blob = bundle_path.read_bytes()
    if blob.startswith(_MAGIC_ENCRYPTED):
        if not passphrase:
            raise ValueError("encrypted bundle requires --passphrase")
        inner = _decrypt_bundle(blob, passphrase)
    else:
        inner = blob

    out_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(inner)
    with zipfile.ZipFile(buf) as zf:
        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        for entry in manifest_data.get("files", []):
            rel = entry["path"]
            # Slash normalization (Windows-emitted ZIPs sometimes carry
            # backslashes); zipfile already handles this, but make the
            # output path safe.
            target = (out_dir / rel).resolve()
            if not str(target).startswith(str(out_dir.resolve())):
                raise ValueError(f"refusing to extract outside out_dir: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(rel))
    manifest = SnapshotManifest(**manifest_data)
    return manifest
