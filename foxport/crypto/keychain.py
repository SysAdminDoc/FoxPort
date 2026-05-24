"""Cross-platform master-key recovery for Chromium-family browsers.

Each platform stores the master encryption secret differently:

* **Windows** — `os_crypt.encrypted_key` in `Local State`, DPAPI-wrapped.
  (handled in :mod:`foxport.crypto.dpapi`)
* **macOS** — Keychain item, ``Service = "<Browser> Safe Storage"``,
  ``Account = "<Browser>"``. The Keychain returns a passphrase which we
  PBKDF2-SHA1 with ``salt = b"saltysalt"``, 1003 iterations, 16-byte key.
* **Linux** — One of:
  - libsecret / gnome-keyring (preferred; via ``secret-tool``)
  - kwallet 5/6 (via ``kwallet-query`` / ``kwallet5-query``)
  - **Plaintext fallback** ``"peanuts"`` — Chromium uses this when no
    secret store is available (CI containers, headless servers).

  Whatever string we recover gets PBKDF2-SHA1'd with **1 iteration**
  (note: differs from macOS).

The output of every path is a 16-byte AES-128 key. Cookie/password blobs
on macOS and Linux begin with the prefix ``v10`` followed by AES-128-CBC
ciphertext (16-byte IV = sixteen spaces).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_SALT = b"saltysalt"
_KEY_LEN = 16          # AES-128
_IV = b" " * 16
_ITERATIONS_MAC = 1003
_ITERATIONS_LINUX = 1


@dataclass(frozen=True)
class ChromiumKeyV10:
    """16-byte AES-128 key derived for v10-style (CBC) blob decryption."""

    key: bytes


class KeychainError(RuntimeError):
    """Keychain / secret-store lookup failed."""


# ----------------------------- macOS Keychain --------------------------------

def _macos_keychain_password(browser_display: str) -> str:
    """Look the Keychain up via the ``security`` CLI.

    Returns the raw passphrase string. Raises :class:`KeychainError` on
    Keychain access denial (the user can re-prompt by clicking "Always
    Allow" in the Keychain dialog).
    """
    service = f"{browser_display} Safe Storage"
    # Some installs (notably Brave) shorten "Google Chrome" -> "Chrome" in
    # the Keychain item — retry with that fallback if the first call fails.
    candidates = [service]
    short = browser_display.replace("Google ", "")
    if short != browser_display:
        candidates.append(f"{short} Safe Storage")
    last_err = "no candidates tried"
    for svc in candidates:
        try:
            completed = subprocess.run(
                ["security", "find-generic-password", "-w", "-s", svc],
                capture_output=True, text=True, timeout=6,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_err = f"security: {exc}"
            continue
        if completed.returncode == 0:
            return completed.stdout.strip()
        last_err = completed.stderr.strip() or f"exit {completed.returncode}"
    raise KeychainError(f"macOS Keychain lookup failed: {last_err}")


# ----------------------------- Linux secret store ----------------------------

def _linux_secret_password(browser_display: str) -> str:
    """Try libsecret/gnome-keyring then kwallet then plaintext fallback."""
    service_candidates = [
        f"{browser_display} Safe Storage",
        f"{browser_display.replace('Google ', '')} Safe Storage",
        "Chromium Safe Storage",
        "Chrome Safe Storage",
    ]
    # 1. libsecret via secret-tool
    for svc in service_candidates:
        try:
            completed = subprocess.run(
                ["secret-tool", "lookup", "application", svc.split(" Safe")[0]],
                capture_output=True, text=True, timeout=4,
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    # 2. kwallet
    for tool in ("kwallet-query", "kwallet5-query"):
        for svc in service_candidates:
            try:
                completed = subprocess.run(
                    [tool, "-r", svc, "kdewallet"],
                    capture_output=True, text=True, timeout=4,
                )
            except (OSError, subprocess.TimeoutExpired):
                break
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.strip()
    # 3. Plaintext fallback — Chromium uses literally "peanuts" when no
    #    secret store is available. Verified in os_crypt_posix.cc.
    return "peanuts"


# ----------------------------- Key derivation --------------------------------

def derive_key(password: str, iterations: int) -> ChromiumKeyV10:
    """PBKDF2-SHA1(password, "saltysalt", iterations, 16 bytes)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=_KEY_LEN,
        salt=_SALT,
        iterations=iterations,
        backend=default_backend(),
    )
    return ChromiumKeyV10(key=kdf.derive(password.encode("utf-8")))


def load_master_key_macos(browser_display: str) -> ChromiumKeyV10:
    return derive_key(_macos_keychain_password(browser_display), _ITERATIONS_MAC)


def load_master_key_linux(browser_display: str) -> ChromiumKeyV10:
    return derive_key(_linux_secret_password(browser_display), _ITERATIONS_LINUX)


def decrypt_value_v10(blob: bytes, key: ChromiumKeyV10) -> str:
    """Decrypt a macOS / Linux v10 (AES-128-CBC) blob into UTF-8.

    Blobs missing the ``v10`` prefix are returned as-is (legacy plaintext,
    e.g. Chrome 79 and earlier on Linux without keyring).
    """
    if not blob:
        return ""
    if blob[:3] != b"v10":
        try:
            return blob.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return ""
    cipher = Cipher(algorithms.AES(key.key), modes.CBC(_IV), backend=default_backend())
    decryptor = cipher.decryptor()
    raw = decryptor.update(blob[3:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(raw) + unpadder.finalize()
    return plaintext.decode("utf-8", errors="replace")
