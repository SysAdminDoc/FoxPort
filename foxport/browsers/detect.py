"""Detect installed Chromium browsers and Firefox variants on Windows.

A "Chromium browser" is anything that uses the Chrome user-data layout — most
follow ``User Data\\<profile>\\Login Data``, but Opera Stable and Opera GX put
a single profile flat at the User Data root (no ``Default\\`` subfolder). Each
quirk is encoded in the registry table below.

A "Firefox" is anything that uses the Gecko profile layout
(``profiles.ini`` + ``<profile>\\places.sqlite``, ``logins.json``,
``extensions.json``).
"""

from __future__ import annotations

import configparser
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChromiumProfile:
    """A single user profile within a Chromium-family browser."""

    browser: str            # display name, e.g. "Brave"
    family: str             # "chromium"
    profile_name: str       # "Default", "Profile 1", or "" for Opera's flat layout
    profile_dir: Path       # absolute path to the profile dir
    local_state: Path       # path to the browser-wide Local State file
    user_data_dir: Path     # parent of profile_dir (== profile_dir for Opera flat)
    process_names: tuple[str, ...] = ()  # exe names used to detect "running"

    @property
    def login_data(self) -> Path:
        return self.profile_dir / "Login Data"

    @property
    def bookmarks(self) -> Path:
        return self.profile_dir / "Bookmarks"

    @property
    def extensions_dir(self) -> Path:
        return self.profile_dir / "Extensions"

    @property
    def label(self) -> str:
        if self.profile_name:
            return f"{self.browser} — {self.profile_name}"
        return self.browser


@dataclass(frozen=True)
class FirefoxProfile:
    """A Gecko-family browser profile (Firefox, LibreWolf, Waterfox, etc.)."""

    browser: str
    family: str             # "firefox"
    profile_name: str
    profile_dir: Path
    is_default: bool = False

    @property
    def label(self) -> str:
        tag = " (default)" if self.is_default else ""
        return f"{self.browser} — {self.profile_name}{tag}"

    @property
    def lock_file(self) -> Path:
        # Firefox uses parent.lock on Windows, .parentlock on Unix.
        return self.profile_dir / ("parent.lock" if sys.platform == "win32" else ".parentlock")


@dataclass(frozen=True)
class _BrowserSpec:
    """How to find a particular Chromium-family browser on disk."""

    rel_path: str
    layout: str = "profile"     # "profile" for Default/Profile N, "flat" for Opera
    base: str = "local"         # "local" = %LOCALAPPDATA%, "roaming" = %APPDATA%
    processes: tuple[str, ...] = ()


# Map display name -> spec.
_CHROMIUM_SPECS: dict[str, _BrowserSpec] = {
    "Google Chrome":       _BrowserSpec(r"Google\Chrome\User Data",                   processes=("chrome.exe",)),
    "Google Chrome Beta":  _BrowserSpec(r"Google\Chrome Beta\User Data",              processes=("chrome.exe",)),
    "Google Chrome Canary": _BrowserSpec(r"Google\Chrome SxS\User Data",              processes=("chrome.exe",)),
    "Chromium":            _BrowserSpec(r"Chromium\User Data",                        processes=("chromium.exe", "chrome.exe")),
    "Brave":               _BrowserSpec(r"BraveSoftware\Brave-Browser\User Data",     processes=("brave.exe",)),
    "Brave Beta":          _BrowserSpec(r"BraveSoftware\Brave-Browser-Beta\User Data", processes=("brave.exe",)),
    "Brave Nightly":       _BrowserSpec(r"BraveSoftware\Brave-Browser-Nightly\User Data", processes=("brave.exe",)),
    "Microsoft Edge":      _BrowserSpec(r"Microsoft\Edge\User Data",                  processes=("msedge.exe",)),
    "Microsoft Edge Beta": _BrowserSpec(r"Microsoft\Edge Beta\User Data",             processes=("msedge.exe",)),
    "Microsoft Edge Dev":  _BrowserSpec(r"Microsoft\Edge Dev\User Data",              processes=("msedge.exe",)),
    "Vivaldi":             _BrowserSpec(r"Vivaldi\User Data",                         processes=("vivaldi.exe",)),
    "Opera":               _BrowserSpec(r"Opera Software\Opera Stable",               layout="flat", base="roaming", processes=("opera.exe", "launcher.exe")),
    "Opera GX":            _BrowserSpec(r"Opera Software\Opera GX Stable",            layout="flat", base="roaming", processes=("opera.exe",)),
    "Yandex":              _BrowserSpec(r"Yandex\YandexBrowser\User Data",            processes=("browser.exe",)),
    "Arc":                 _BrowserSpec(r"Arc\User Data",                             processes=("arc.exe",)),
    "Thorium":             _BrowserSpec(r"Thorium\User Data",                         processes=("thorium.exe", "chrome.exe")),
}

_FIREFOX_PROFILES_ROOT: dict[str, str] = {
    "Firefox":         r"Mozilla\Firefox",
    "Firefox Nightly": r"Mozilla\Firefox",
    "Firefox ESR":     r"Mozilla\Firefox",
    "LibreWolf":       r"LibreWolf",
    "Waterfox":        r"Waterfox",
    "Floorp":          r"Floorp",
    "Mullvad Browser": r"Mullvad\MullvadBrowser",
    "Zen Browser":     r"zen",
}


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))


def _enumerate_profile_subdirs(user_data: Path) -> list[str]:
    """Return profile dir names that look like real Chromium profiles."""
    if not user_data.is_dir():
        return []
    out: list[str] = []
    for child in sorted(user_data.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name == "Default" or name.startswith("Profile ") or name == "Guest Profile":
            if (child / "Preferences").is_file():
                out.append(name)
    return out


def detect_chromium() -> list[ChromiumProfile]:
    """Find every Chromium-family profile installed for the current user."""
    found: list[ChromiumProfile] = []
    local = _local_appdata()
    roaming = _appdata()
    for display, spec in _CHROMIUM_SPECS.items():
        root = (roaming if spec.base == "roaming" else local) / spec.rel_path
        local_state = root / "Local State"
        if not local_state.is_file():
            continue
        if spec.layout == "flat":
            # Opera Stable / Opera GX — single profile lives at the root.
            if (root / "Preferences").is_file():
                found.append(ChromiumProfile(
                    browser=display,
                    family="chromium",
                    profile_name="",
                    profile_dir=root,
                    local_state=local_state,
                    user_data_dir=root,
                    process_names=spec.processes,
                ))
            continue
        for profile_name in _enumerate_profile_subdirs(root):
            found.append(ChromiumProfile(
                browser=display,
                family="chromium",
                profile_name=profile_name,
                profile_dir=root / profile_name,
                local_state=local_state,
                user_data_dir=root,
                process_names=spec.processes,
            ))
    return found


def _parse_profiles_ini(ini_path: Path, root: Path) -> list[FirefoxProfile]:
    if not ini_path.is_file():
        return []
    cfg = configparser.ConfigParser()
    try:
        cfg.read(ini_path, encoding="utf-8")
    except configparser.Error:
        return []
    install_default: str | None = None
    for section in cfg.sections():
        if section.startswith("Install") and cfg.has_option(section, "Default"):
            install_default = cfg.get(section, "Default")
            break
    profiles: list[FirefoxProfile] = []
    for section in cfg.sections():
        if not section.startswith("Profile"):
            continue
        if not cfg.has_option(section, "Path"):
            continue
        rel = cfg.get(section, "Path")
        is_relative = cfg.getint(section, "IsRelative", fallback=1) == 1
        profile_dir = (root / rel) if is_relative else Path(rel)
        if not profile_dir.is_dir():
            continue
        is_default = False
        if install_default and rel == install_default:
            is_default = True
        elif cfg.has_option(section, "Default") and cfg.getint(section, "Default", fallback=0) == 1:
            is_default = True
        name = cfg.get(section, "Name", fallback=profile_dir.name)
        profiles.append(FirefoxProfile(
            browser="",
            family="firefox",
            profile_name=name,
            profile_dir=profile_dir,
            is_default=is_default,
        ))
    return profiles


def detect_firefox() -> list[FirefoxProfile]:
    found: list[FirefoxProfile] = []
    base = _appdata()
    seen: set[Path] = set()
    for display, rel in _FIREFOX_PROFILES_ROOT.items():
        root = base / rel
        ini_path = root / "profiles.ini"
        if not ini_path.is_file():
            continue
        for prof in _parse_profiles_ini(ini_path, root):
            if prof.profile_dir in seen:
                continue
            seen.add(prof.profile_dir)
            found.append(FirefoxProfile(
                browser=display,
                family=prof.family,
                profile_name=prof.profile_name,
                profile_dir=prof.profile_dir,
                is_default=prof.is_default,
            ))
    return found


# ---------------------------------------------------------------- Runtime probes

def is_chromium_running(profile: ChromiumProfile) -> bool:
    """True if the source browser appears to be running.

    Two signals: (a) any of the browser's known exe names show up in the
    current process list (tasklist on Windows), or (b) a SingletonLock /
    SingletonCookie sits in the user-data directory.
    """
    if (profile.user_data_dir / "SingletonLock").exists():
        return True
    if (profile.user_data_dir / "SingletonCookie").exists():
        return True
    if not profile.process_names:
        return False
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        # tasklist /FO CSV is fast and parsable; one call covers all exe names.
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    haystack = completed.stdout.lower()
    return any(name.lower() in haystack for name in profile.process_names)


def is_firefox_profile_locked(profile: FirefoxProfile) -> bool:
    """True if the Firefox profile holds an active lock (browser is open)."""
    return profile.lock_file.exists()


def read_installed_firefox_extensions(profile: FirefoxProfile) -> set[str]:
    """Return the set of AMO GUIDs already installed in the target profile.

    Reads ``extensions.json`` (Firefox's authoritative extension registry).
    Empty set on any read/parse failure — we don't want a stale-cache problem
    to block a migration.
    """
    ext_json = profile.profile_dir / "extensions.json"
    if not ext_json.is_file():
        return set()
    try:
        data = json.loads(ext_json.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return set()
    guids: set[str] = set()
    for addon in data.get("addons", []) or []:
        guid = addon.get("id")
        if isinstance(guid, str):
            guids.add(guid)
    return guids
