"""Python wrapper around Firefox's NSS (Mozilla Security Services) library.

FoxPort's default password migration path emits a CSV the user imports via
``about:logins`` — safe, no DLL dependencies, no shared-library version skew.
This module is the *opt-in* alternative: load the target Firefox install's
``nss3.dll``, initialize it against the target profile, and produce
NSS-encrypted blobs the same way Firefox itself does (PK11SDR_Encrypt over
the internal key slot).

The encrypted blob is a base64-wrapped ASN.1 DER structure. Firefox writes
these into ``logins.json`` under ``encryptedUsername`` / ``encryptedPassword``
with ``encType: 1``.

Why this is opt-in:

* The DLL search must point at the *exact* Firefox install whose profile
  you're targeting. Mixing nss3.dll versions corrupts the key store.
* The profile must not be open in Firefox while we hold an NSS session,
  or NSS deadlocks on the key DB lock.
* On profiles with a master password set, NSS will silently refuse to
  decrypt — we'd be writing entries Firefox can't read.

References:
* https://github.com/unode/firefox_decrypt  (read-side reference)
* https://github.com/louisabraham/ffpass    (write-side reference)
* mozilla-central security/nss/lib/pk11wrap/pk11sdr.h
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_uint,
    c_void_p,
    cdll,
    create_string_buffer,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from foxport.browsers.detect import FirefoxProfile


# NSS uses SECStatus = 0 (SECSuccess) / -1 (SECFailure).
SECSuccess = 0
SECFailure = -1


class _SECItem(Structure):
    _fields_ = [
        ("type", c_uint),
        ("data", c_void_p),  # opaque uchar*; we use byte buffers for I/O.
        ("len", c_uint),
    ]


class NSSError(RuntimeError):
    """Anything NSS-related that went wrong."""


@dataclass(frozen=True)
class NSSLibrary:
    """Loaded NSS shared library + bound function prototypes."""

    handle: ctypes.CDLL
    install_path: Path


# Per-platform NSS shared-library names + install search paths.
_NSS_SEARCH_WIN = [
    r"C:\Program Files\Mozilla Firefox\nss3.dll",
    r"C:\Program Files (x86)\Mozilla Firefox\nss3.dll",
    r"C:\Program Files\Firefox Nightly\nss3.dll",
    r"C:\Program Files\Firefox ESR\nss3.dll",
    r"C:\Program Files\LibreWolf\nss3.dll",
    r"C:\Program Files\Waterfox\nss3.dll",
    r"C:\Program Files\Floorp\nss3.dll",
    r"C:\Program Files\Mullvad Browser\Browser\nss3.dll",
    r"C:\Program Files\Zen Browser\nss3.dll",
]

_NSS_SEARCH_MAC = [
    "/Applications/Firefox.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Firefox Nightly.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Firefox ESR.app/Contents/MacOS/libnss3.dylib",
    "/Applications/LibreWolf.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Waterfox.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Floorp.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Mullvad Browser.app/Contents/MacOS/libnss3.dylib",
    "/Applications/Zen Browser.app/Contents/MacOS/libnss3.dylib",
]

_NSS_SEARCH_LINUX = [
    "/usr/lib/firefox/libnss3.so",
    "/usr/lib64/firefox/libnss3.so",
    "/usr/lib/x86_64-linux-gnu/libnss3.so",
    "/usr/lib/librewolf/libnss3.so",
    "/usr/lib/waterfox/libnss3.so",
    "/opt/firefox/libnss3.so",
    "/snap/firefox/current/usr/lib/firefox/libnss3.so",
    "/var/lib/flatpak/app/org.mozilla.firefox/current/active/files/lib/firefox/libnss3.so",
]


def find_nss() -> Path | None:
    """Return the first Firefox-shipped NSS library we can find, or None."""
    if sys.platform == "win32":
        candidates: list[str] = list(_NSS_SEARCH_WIN)
    elif sys.platform == "darwin":
        candidates = list(_NSS_SEARCH_MAC)
    elif sys.platform.startswith("linux"):
        candidates = list(_NSS_SEARCH_LINUX)
    else:
        return None
    # Allow override via env var for advanced users / portable installs.
    override = os.environ.get("FOXPORT_NSS_PATH")
    if override:
        candidates.insert(0, override)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def load_nss(install_path: Path | None = None) -> NSSLibrary:
    """Load nss3.dll + its dependent DLLs from the same directory.

    On Windows ≥ 3.8 you must explicitly add the DLL directory before
    loading or `nssutil3.dll` / `nspr4.dll` / `mozglue.dll` won't resolve.
    """
    nss_path = install_path or find_nss()
    if not nss_path:
        raise NSSError("could not find Firefox's nss3.dll — install Firefox first or set FOXPORT_NSS_PATH")
    install_dir = nss_path.parent
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(install_dir))
        except OSError as exc:
            raise NSSError(f"add_dll_directory failed for {install_dir}: {exc}") from exc

    try:
        handle = cdll.LoadLibrary(str(nss_path))
    except OSError as exc:
        raise NSSError(f"LoadLibrary({nss_path}) failed: {exc}") from exc

    # NSS_Init(profile_path: const char*) -> SECStatus
    handle.NSS_Init.argtypes = [c_char_p]
    handle.NSS_Init.restype = c_int
    handle.NSS_Shutdown.argtypes = []
    handle.NSS_Shutdown.restype = c_int
    # PK11_GetInternalKeySlot() -> void* (PK11SlotInfo*)
    handle.PK11_GetInternalKeySlot.argtypes = []
    handle.PK11_GetInternalKeySlot.restype = c_void_p
    handle.PK11_FreeSlot.argtypes = [c_void_p]
    handle.PK11_FreeSlot.restype = None
    handle.PK11_NeedLogin.argtypes = [c_void_p]
    handle.PK11_NeedLogin.restype = c_int
    handle.PK11_CheckUserPassword.argtypes = [c_void_p, c_char_p]
    handle.PK11_CheckUserPassword.restype = c_int
    # PK11SDR_Encrypt(keyid*, data*, result*, context) -> SECStatus
    handle.PK11SDR_Encrypt.argtypes = [POINTER(_SECItem), POINTER(_SECItem), POINTER(_SECItem), c_void_p]
    handle.PK11SDR_Encrypt.restype = c_int
    handle.SECITEM_FreeItem.argtypes = [POINTER(_SECItem), c_int]
    handle.SECITEM_FreeItem.restype = None
    return NSSLibrary(handle=handle, install_path=nss_path)


class NSSSession:
    """RAII-style scoped NSS session pinned to one profile directory."""

    def __init__(self, lib: NSSLibrary, profile_dir: Path, master_password: str = "") -> None:
        self._lib = lib
        self._profile = profile_dir
        self._slot: c_void_p | None = None
        if not profile_dir.is_dir():
            raise NSSError(f"profile dir {profile_dir} does not exist")
        rv = lib.handle.NSS_Init(str(profile_dir).encode("utf-8"))
        if rv != SECSuccess:
            raise NSSError(f"NSS_Init failed for {profile_dir} (rv={rv})")
        slot = lib.handle.PK11_GetInternalKeySlot()
        if not slot:
            lib.handle.NSS_Shutdown()
            raise NSSError("PK11_GetInternalKeySlot returned NULL")
        if lib.handle.PK11_NeedLogin(slot):
            rv = lib.handle.PK11_CheckUserPassword(slot, master_password.encode("utf-8"))
            if rv != SECSuccess:
                lib.handle.PK11_FreeSlot(slot)
                lib.handle.NSS_Shutdown()
                raise NSSError(
                    "Firefox profile has a master password — pass --master-password "
                    "to NSSSession or remove the master password before importing."
                )
        self._slot = slot

    def encrypt(self, plaintext: str) -> str:
        """Encrypt ``plaintext`` via PK11SDR_Encrypt, return base64-DER result."""
        if self._slot is None:
            raise NSSError("NSS session is closed")
        data_bytes = plaintext.encode("utf-8")
        buf = create_string_buffer(data_bytes)
        data_item = _SECItem(type=0, data=ctypes.cast(buf, c_void_p).value, len=len(data_bytes))
        # An empty keyid means "use the SDR internal key" — NSS handles it.
        keyid = _SECItem(type=0, data=None, len=0)
        result = _SECItem(type=0, data=None, len=0)
        rv = self._lib.handle.PK11SDR_Encrypt(byref(keyid), byref(data_item), byref(result), None)
        if rv != SECSuccess:
            raise NSSError(f"PK11SDR_Encrypt failed (rv={rv})")
        try:
            blob = ctypes.string_at(result.data, result.len)
        finally:
            self._lib.handle.SECITEM_FreeItem(byref(result), 0)
        return base64.b64encode(blob).decode("ascii")

    def close(self) -> None:
        if self._slot is not None:
            self._lib.handle.PK11_FreeSlot(self._slot)
            self._slot = None
        self._lib.handle.NSS_Shutdown()

    def __enter__(self) -> "NSSSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_session(profile: FirefoxProfile, master_password: str = "") -> NSSSession:
    """Convenience: load NSS + open a session against ``profile``."""
    lib = load_nss()
    return NSSSession(lib, profile.profile_dir, master_password=master_password)
