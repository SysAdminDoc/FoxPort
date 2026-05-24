"""Python wrapper around the ``foxport_abe.exe`` App-Bound Encryption sidecar.

When a Chromium profile only has ``app_bound_encrypted_key`` (no classic
``encrypted_key``), the AES master key can't be recovered without a call
into the per-browser ``IElevator`` elevated COM interface. The interface
demands a path-validated, elevated caller, so we ship a tiny native EXE
(``tools/abe_sidecar/foxport_abe.cpp``) that handles the dance and prints
the recovered key to stdout.

This module:

1. Locates a bundled ``foxport_abe.exe`` next to FoxPort (in
   ``foxport/data/`` or alongside the PyInstaller bundle's ``_internal/``).
2. Maps the FoxPort browser display name to a sidecar ``--browser`` value.
3. Invokes the sidecar with UAC, captures stdout, returns the 32-byte key.

When the sidecar isn't bundled (e.g. running from a dev checkout without
a CMake build), raises :class:`AbeSidecarMissingError` so the caller can
surface a clear "build the sidecar first" message instead of a generic
import error.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from foxport.crypto.dpapi import ChromiumKey, DecryptionError
from foxport.data import data_file


class AbeSidecarMissingError(DecryptionError):
    """Raised when ``foxport_abe.exe`` is not bundled with this install."""


class AbeSidecarError(DecryptionError):
    """Raised when the sidecar EXE ran but reported a failure."""


# FoxPort browser display name -> sidecar --browser argument.
_BROWSER_TO_SIDECAR: dict[str, str] = {
    "Google Chrome":        "chrome",
    "Google Chrome Beta":   "chrome",
    "Google Chrome Canary": "chrome",
    "Chromium":             "chrome",
    "Brave":                "brave",
    "Brave Beta":           "brave",
    "Brave Nightly":        "brave",
    "Microsoft Edge":       "edge",
    "Microsoft Edge Beta":  "edge",
    "Microsoft Edge Dev":   "edge",
    # Vivaldi / Opera / Arc / Thorium use Chrome's IElevator at present.
    "Vivaldi":              "chrome",
    "Opera":                "chrome",
    "Opera GX":             "chrome",
    "Arc":                  "chrome",
    "Thorium":              "chrome",
    "Yandex":               "chrome",
}


def sidecar_path() -> Path | None:
    """Return the path to a bundled ``foxport_abe.exe`` if present."""
    # 1. Sibling of the foxport package (dev checkout convention).
    candidate = data_file("foxport_abe.exe")
    if candidate.is_file():
        return candidate
    # 2. PyInstaller --onedir / --onefile bundle: sys._MEIPASS is set.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "foxport_abe.exe"
        if candidate.is_file():
            return candidate
    # 3. Next to the running Python script / packaged executable.
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "foxport_abe.exe"
        if candidate.is_file():
            return candidate
    return None


def sidecar_browser_name(display_name: str) -> str:
    """Translate FoxPort's browser display name to the sidecar's --browser arg."""
    return _BROWSER_TO_SIDECAR.get(display_name, "chrome")


def recover_app_bound_key(local_state_path: Path, browser_display: str) -> ChromiumKey:
    """Run ``foxport_abe.exe`` and return the recovered 32-byte AES key.

    Raises :class:`AbeSidecarMissingError` if the sidecar EXE isn't bundled,
    or :class:`AbeSidecarError` if it ran but failed (non-zero exit code,
    UAC denied, IElevator returned an error, ...).
    """
    if sys.platform != "win32":
        raise AbeSidecarError("App-Bound Encryption recovery is Windows-only")
    exe = sidecar_path()
    if not exe:
        raise AbeSidecarMissingError(
            "foxport_abe.exe is not bundled with this install. "
            "Build it from tools/abe_sidecar/ (cmake -B build -A x64 && "
            "cmake --build build --config Release) and copy the result into "
            "foxport/data/."
        )
    cmd = [
        str(exe),
        "--browser", sidecar_browser_name(browser_display),
        "--local-state", str(local_state_path),
    ]
    try:
        # Sidecar elevates itself via its manifest; the UAC prompt happens
        # at CreateProcess time. We don't redirect stdin so the process can
        # surface the elevation dialog normally.
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AbeSidecarError(f"failed to launch foxport_abe.exe: {exc}") from exc

    if completed.returncode != 0:
        msg = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise AbeSidecarError(
            f"foxport_abe.exe exited {completed.returncode}: {msg}"
        )

    key_hex: str | None = None
    saw_ok = False
    for line in completed.stdout.splitlines():
        line = line.strip()
        if line.startswith("KEY_HEX:"):
            key_hex = line[len("KEY_HEX:"):].strip().lower()
        elif line == "OK":
            saw_ok = True
    if not (key_hex and saw_ok and len(key_hex) == 64):
        raise AbeSidecarError(
            f"foxport_abe.exe finished without a valid key line: {completed.stdout!r}"
        )
    try:
        key_bytes = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise AbeSidecarError(f"sidecar produced non-hex key: {exc}") from exc
    return ChromiumKey(key=key_bytes)
