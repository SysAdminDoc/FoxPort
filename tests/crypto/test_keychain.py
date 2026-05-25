"""Cross-platform secret-store password recovery.

These tests mock the per-platform CLIs (``security`` on macOS,
``secret-tool`` / ``kwallet-query`` on Linux) so they run unchanged on
every CI platform. The keychain module itself never runs the real
subprocess in tests; the fixtures inject a fake ``subprocess.run``.

Pre-v1.4 the only crypto/ tests we shipped covered HIBP + mozhash + NSS
version. macOS Keychain + Linux secret-store paths had zero coverage,
which made the "peanuts" plaintext fallback particularly easy to break
during a refactor.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from foxport.crypto import keychain
from foxport.crypto.keychain import (
    ChromiumKeyV10,
    KeychainError,
    _ITERATIONS_LINUX,
    _ITERATIONS_MAC,
    _linux_secret_password,
    _macos_keychain_password,
    derive_key,
    load_master_key_linux,
    load_master_key_macos,
)


def _fake_completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """Build the minimal subprocess.CompletedProcess shape the keychain
    helpers read from."""
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


# ----------------------------- macOS --------------------------------------

def test_macos_keychain_returns_passphrase_on_first_try(monkeypatch):
    """Happy path: ``security find-generic-password`` succeeds with the
    canonical ``"<Browser> Safe Storage"`` service name."""

    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _fake_completed(stdout="hunter2\n", returncode=0)

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)

    pw = _macos_keychain_password("Brave")

    assert pw == "hunter2"
    assert captured["cmd"][:3] == ["security", "find-generic-password", "-w"]
    assert "Brave Safe Storage" in captured["cmd"]


def test_macos_keychain_falls_back_to_short_name_for_google_chrome(monkeypatch):
    """The ``Google Chrome`` Keychain item is sometimes filed under just
    ``Chrome Safe Storage`` (Brave-installed Chrome, MAS-distributed
    Chrome, etc.). The helper retries with the shortened name when the
    first lookup fails.
    """

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(list(cmd))
        # First call (with "Google Chrome Safe Storage") fails.
        if "Google Chrome Safe Storage" in cmd:
            return _fake_completed(returncode=1, stderr="The specified item could not be found")
        # Second call (with "Chrome Safe Storage") succeeds.
        return _fake_completed(stdout="alt-secret\n", returncode=0)

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)

    pw = _macos_keychain_password("Google Chrome")

    assert pw == "alt-secret"
    assert len(calls) == 2
    assert "Google Chrome Safe Storage" in calls[0]
    assert "Chrome Safe Storage" in calls[1]


def test_macos_keychain_raises_when_every_candidate_fails(monkeypatch):
    """When both the full and shortened service names fail, the helper
    raises ``KeychainError`` with the last stderr — the GUI surfaces
    this as the migration's per-row failure list."""

    def fake_run(cmd, capture_output, text, timeout):
        return _fake_completed(returncode=1, stderr="errSecItemNotFound")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)

    with pytest.raises(KeychainError, match="errSecItemNotFound"):
        _macos_keychain_password("Brave")


def test_macos_keychain_handles_security_not_installed(monkeypatch):
    """If the ``security`` binary isn't on PATH (rare but possible on
    Linux runners running macOS-targeted tests), subprocess raises OSError.
    The helper must convert that to KeychainError, not bubble it.
    """

    def fake_run(cmd, capture_output, text, timeout):
        raise OSError("[Errno 2] No such file or directory: 'security'")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)

    with pytest.raises(KeychainError):
        _macos_keychain_password("Brave")


def test_load_master_key_macos_derives_16_byte_aes_128_key(monkeypatch):
    """End-to-end: the macOS code path derives a 16-byte AES-128 key
    via PBKDF2-SHA1 with the canonical mac iteration count (1003)."""

    monkeypatch.setattr(keychain, "_macos_keychain_password",
                        lambda browser_display: "hunter2")
    key = load_master_key_macos("Brave")
    assert isinstance(key, ChromiumKeyV10)
    assert len(key.key) == 16
    # Same input must produce the same key.
    again = load_master_key_macos("Brave")
    assert again.key == key.key


# ----------------------------- Linux --------------------------------------

def test_linux_secret_tool_returns_passphrase_first_try(monkeypatch):
    """``secret-tool lookup application Brave`` is the preferred Linux
    path. When it succeeds we never consult kwallet or fall back to
    "peanuts".
    """

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(list(cmd))
        return _fake_completed(stdout="libsecret-passphrase\n", returncode=0)

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    pw = _linux_secret_password("Brave")

    assert pw == "libsecret-passphrase"
    # Only secret-tool was queried — kwallet wasn't reached.
    assert all(call[0] == "secret-tool" for call in calls)


def test_linux_falls_back_to_kwallet_then_peanuts(monkeypatch):
    """When secret-tool returns empty / non-zero AND kwallet-query
    also fails, the Linux path falls back to the documented Chromium
    ``"peanuts"`` plaintext. Pin the fallback so a refactor doesn't
    accidentally break CI containers / headless servers.
    """

    def fake_run(cmd, capture_output, text, timeout):
        # Every CLI invocation fails for this test.
        if cmd[0] == "secret-tool":
            return _fake_completed(returncode=1, stderr="No matching secret")
        if cmd[0] in ("kwallet-query", "kwallet5-query"):
            return _fake_completed(returncode=1, stderr="kwallet not running")
        raise AssertionError(f"unexpected tool: {cmd[0]}")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    assert _linux_secret_password("Brave") == "peanuts"


def test_linux_falls_back_to_peanuts_when_no_tools_installed(monkeypatch):
    """``OSError`` from subprocess.run means the binary isn't even on
    PATH. The Linux path must still degrade to "peanuts" rather than
    bubbling the OSError out (Chromium would behave identically)."""

    def fake_run(cmd, capture_output, text, timeout):
        raise OSError("not on PATH")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    assert _linux_secret_password("Brave") == "peanuts"


def test_load_master_key_linux_uses_1_iteration(monkeypatch):
    """The Linux derivation is PBKDF2-SHA1(password, salt, 1) — a
    single iteration, NOT the macOS 1003. Mixing the iteration counts
    produces a key that doesn't decrypt anything. Pin the contract.
    """

    monkeypatch.setattr(keychain, "_linux_secret_password",
                        lambda browser_display: "peanuts")
    key_linux = load_master_key_linux("Brave")
    key_with_1_explicit = derive_key("peanuts", 1)
    # Same iteration => same key.
    assert key_linux.key == key_with_1_explicit.key
    # And different from the 1003-iteration macOS variant.
    key_mac_style = derive_key("peanuts", _ITERATIONS_MAC)
    assert key_linux.key != key_mac_style.key
    # Sanity: iteration constants stay aligned with the documented
    # Chromium values.
    assert _ITERATIONS_LINUX == 1
    assert _ITERATIONS_MAC == 1003
