"""Windows DPAPI + AES-GCM decryption for Chromium Login Data.

Chromium (Chrome 80+, Brave, Edge, Vivaldi, Opera) encrypts saved passwords with
AES-256-GCM, where the AES key itself is wrapped by Windows DPAPI in
``Local State`` under ``os_crypt.encrypted_key`` (base64, prefixed with "DPAPI").

Per-entry layout:
    v10|v11    (3 bytes, version tag)
    nonce      (12 bytes)
    ciphertext (variable)
    tag        (16 bytes)
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DecryptionError(RuntimeError):
    """Raised when a password blob cannot be decrypted."""


class AppBoundEncryptionError(DecryptionError):
    """Raised when a blob requires the App-Bound Encryption bypass we don't ship."""


@dataclass(frozen=True)
class ChromiumKey:
    """Decrypted master key extracted from ``Local State`` (Windows) or
    derived from the platform keychain (macOS / Linux).

    Length depends on platform: Windows uses AES-256 (32 bytes), while
    macOS and Linux use AES-128 (16 bytes). The :func:`decrypt_value`
    function branches on blob prefix and key length to call the right
    cipher.
    """

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) not in (16, 32):
            raise DecryptionError(f"expected 16- or 32-byte AES key, got {len(self.key)}")


@dataclass(frozen=True)
class LocalStateInfo:
    """Summary of what was found in a Chromium ``Local State`` file."""

    has_classic_key: bool       # os_crypt.encrypted_key (DPAPI v10)
    has_app_bound_key: bool     # os_crypt.app_bound_encrypted_key (ABE, Chrome 127+)
    encrypted_key_b64: str | None
    app_bound_key_b64: str | None


def _dpapi_unprotect(blob: bytes) -> bytes:
    """Run Windows DPAPI ``CryptUnprotectData`` against ``blob``.

    Only works on the same Windows user account that originally encrypted the
    data. On non-Windows, this is unreachable and raises.
    """
    if sys.platform != "win32":
        raise DecryptionError("DPAPI is only available on Windows")
    import win32crypt  # type: ignore[import-not-found]

    try:
        _desc, plaintext = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    except Exception as exc:  # pywin32 raises a generic pywintypes.error
        raise DecryptionError(f"DPAPI unprotect failed: {exc}") from exc
    return bytes(plaintext)


def inspect_local_state(local_state_path: Path) -> LocalStateInfo:
    """Look at a ``Local State`` file and report what keys are present.

    Used to surface App-Bound Encryption to the user without blowing up the
    whole migration. Returns a populated :class:`LocalStateInfo` even when
    neither key is present (caller decides what to do).
    """
    try:
        raw = local_state_path.read_text(encoding="utf-8", errors="ignore")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return LocalStateInfo(False, False, None, None)
    os_crypt = data.get("os_crypt", {}) or {}
    classic = os_crypt.get("encrypted_key")
    abe = os_crypt.get("app_bound_encrypted_key")
    return LocalStateInfo(
        has_classic_key=bool(classic),
        has_app_bound_key=bool(abe),
        encrypted_key_b64=classic,
        app_bound_key_b64=abe,
    )


def load_master_key(
    local_state_path: Path,
    *,
    browser_display: str | None = None,
    try_abe: bool = True,
) -> ChromiumKey:
    """Extract / derive the master AES key for this Chromium profile.

    Dispatches by platform:

    * **Windows** — DPAPI unwrap of ``os_crypt.encrypted_key``, falling back
      to the ABE sidecar when only the App-Bound key is present.
    * **macOS** — Keychain item lookup + PBKDF2-SHA1 (1003 iterations).
    * **Linux** — libsecret / kwallet / "peanuts" fallback + PBKDF2-SHA1
      (1 iteration).
    """
    display = browser_display or "Google Chrome"
    if sys.platform == "darwin":
        from foxport.crypto.keychain import KeychainError, load_master_key_macos
        try:
            v10 = load_master_key_macos(display)
        except KeychainError as exc:
            raise DecryptionError(str(exc)) from exc
        return ChromiumKey(key=v10.key)
    if sys.platform.startswith("linux"):
        from foxport.crypto.keychain import KeychainError, load_master_key_linux
        try:
            v10 = load_master_key_linux(display)
        except KeychainError as exc:
            raise DecryptionError(str(exc)) from exc
        return ChromiumKey(key=v10.key)

    info = inspect_local_state(local_state_path)
    if info.has_classic_key:
        wrapped = base64.b64decode(info.encrypted_key_b64 or "")
        if not wrapped.startswith(b"DPAPI"):
            raise DecryptionError("encrypted_key missing DPAPI prefix")
        return ChromiumKey(key=_dpapi_unprotect(wrapped[5:]))
    if info.has_app_bound_key and try_abe:
        # Import lazily so non-Windows tests don't fail on the sidecar module.
        from foxport.crypto.abe import (
            AbeSidecarError,
            AbeSidecarMissingError,
            recover_app_bound_key,
        )
        try:
            return recover_app_bound_key(
                local_state_path,
                browser_display=browser_display or "Google Chrome",
            )
        except AbeSidecarMissingError as exc:
            raise AppBoundEncryptionError(str(exc)) from exc
        except AbeSidecarError as exc:
            raise AppBoundEncryptionError(f"ABE sidecar failed: {exc}") from exc
    if info.has_app_bound_key:
        raise AppBoundEncryptionError(
            "this profile uses App-Bound Encryption only (Chrome 127+); "
            "ABE recovery was skipped (try_abe=False)."
        )
    raise DecryptionError(f"no os_crypt.encrypted_key in {local_state_path}")


def decrypt_value(blob: bytes, master: ChromiumKey) -> str:
    """Decrypt a single Chromium-encrypted value (password, cookie, etc.).

    Returns the decoded UTF-8 string. Raises :class:`DecryptionError` on failure.
    Handles three blob formats:

    * **v10/v11 AES-GCM** with a 32-byte key (Windows Chromium 80+)
    * **v10 AES-128-CBC** with a 16-byte key (macOS/Linux Chromium 80+)
    * **Raw DPAPI UTF-16LE** (pre-Chromium 80, Windows only)
    """
    if not blob:
        return ""
    prefix = blob[:3]
    if prefix in (b"v10", b"v11"):
        # 16-byte key => macOS/Linux CBC path; 32-byte key => Windows GCM path.
        if len(master.key) == 16:
            from foxport.crypto.keychain import ChromiumKeyV10, decrypt_value_v10
            return decrypt_value_v10(blob, ChromiumKeyV10(key=master.key))
        nonce = blob[3:15]
        ct_and_tag = blob[15:]
        aes = AESGCM(master.key)
        try:
            plaintext = aes.decrypt(nonce, ct_and_tag, None)
        except Exception as exc:
            raise DecryptionError(f"AES-GCM decrypt failed: {exc}") from exc
        return plaintext.decode("utf-8", errors="replace")
    # Pre-Chromium 80: raw DPAPI-encrypted UTF-16LE string (Windows only).
    try:
        plaintext = _dpapi_unprotect(blob)
    except DecryptionError:
        raise
    try:
        return plaintext.decode("utf-16-le", errors="replace").rstrip("\x00")
    except UnicodeDecodeError:
        return plaintext.decode("utf-8", errors="replace")
