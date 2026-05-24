"""Detect installed Chromium browsers and Firefox variants on Windows.

A "Chromium browser" is anything that uses the Chrome user-data layout
(``User Data\\<profile>\\Login Data``, ``Bookmarks``, ``Extensions\\``, plus a
top-level ``Local State``). We probe known install paths and enumerate any
extra profiles each browser holds.

A "Firefox" is anything that uses the Gecko profile layout
(``profiles.ini`` + ``<profile>\\places.sqlite``, ``logins.json``,
``extensions.json``).
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChromiumProfile:
    """A single user profile within a Chromium-family browser."""

    browser: str            # display name, e.g. "Brave"
    family: str             # "chromium"
    profile_name: str       # "Default", "Profile 1", etc.
    profile_dir: Path       # absolute path to the profile dir
    local_state: Path       # path to the browser-wide Local State file
    user_data_dir: Path     # parent of profile_dir

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
        return f"{self.browser} — {self.profile_name}"


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


# Map browser display name -> %LOCALAPPDATA% relative path holding User Data.
_CHROMIUM_USER_DATA: dict[str, str] = {
    "Google Chrome":       r"Google\Chrome\User Data",
    "Google Chrome Beta":  r"Google\Chrome Beta\User Data",
    "Google Chrome Canary": r"Google\Chrome SxS\User Data",
    "Chromium":            r"Chromium\User Data",
    "Brave":               r"BraveSoftware\Brave-Browser\User Data",
    "Brave Beta":          r"BraveSoftware\Brave-Browser-Beta\User Data",
    "Brave Nightly":       r"BraveSoftware\Brave-Browser-Nightly\User Data",
    "Microsoft Edge":      r"Microsoft\Edge\User Data",
    "Microsoft Edge Beta": r"Microsoft\Edge Beta\User Data",
    "Microsoft Edge Dev":  r"Microsoft\Edge Dev\User Data",
    "Vivaldi":             r"Vivaldi\User Data",
    "Opera":               r"Opera Software\Opera Stable",
    "Opera GX":            r"Opera Software\Opera GX Stable",
    "Yandex":              r"Yandex\YandexBrowser\User Data",
    "Arc":                 r"Arc\User Data",
    "Thorium":             r"Thorium\User Data",
}

# Firefox-family profiles live under %APPDATA%.
_FIREFOX_PROFILES_ROOT: dict[str, str] = {
    "Firefox":         r"Mozilla\Firefox",
    "Firefox Nightly": r"Mozilla\Firefox",   # shares profiles.ini, separate channel
    "Firefox ESR":     r"Mozilla\Firefox",
    "LibreWolf":       r"LibreWolf",
    "Waterfox":        r"Waterfox",
    "Floorp":          r"Floorp",
    "Mullvad Browser": r"Mullvad\MullvadBrowser",
    "Tor Browser":     r"tor browser\Browser",  # portable layout — fallback to %APPDATA%
    "Zen Browser":     r"zen",
}


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))


def _enumerate_chromium_profiles(user_data: Path) -> list[str]:
    """Return profile dir names that look like real Chromium profiles."""
    if not user_data.is_dir():
        return []
    candidates: list[str] = []
    for child in sorted(user_data.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        # "Default", "Profile 1", "Profile 2"... plus the optional "Guest Profile".
        if name == "Default" or name.startswith("Profile ") or name == "Guest Profile":
            if (child / "Preferences").is_file():
                candidates.append(name)
    return candidates


def detect_chromium() -> list[ChromiumProfile]:
    """Find every Chromium-family profile installed for the current user."""
    found: list[ChromiumProfile] = []
    base = _local_appdata()
    for display, rel in _CHROMIUM_USER_DATA.items():
        user_data = base / rel
        local_state = user_data / "Local State"
        if not local_state.is_file():
            continue
        for profile_name in _enumerate_chromium_profiles(user_data):
            profile_dir = user_data / profile_name
            found.append(ChromiumProfile(
                browser=display,
                family="chromium",
                profile_name=profile_name,
                profile_dir=profile_dir,
                local_state=local_state,
                user_data_dir=user_data,
            ))
    return found


def _parse_profiles_ini(ini_path: Path, root: Path) -> list[FirefoxProfile]:
    """Walk a Firefox-style ``profiles.ini`` and return absolute profile dirs."""
    if not ini_path.is_file():
        return []
    cfg = configparser.ConfigParser()
    try:
        cfg.read(ini_path, encoding="utf-8")
    except configparser.Error:
        return []
    # Determine default from any Install* section first.
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
            browser="",  # filled in by caller
            family="firefox",
            profile_name=name,
            profile_dir=profile_dir,
            is_default=is_default,
        ))
    return profiles


def detect_firefox() -> list[FirefoxProfile]:
    """Find every Firefox-family profile installed for the current user."""
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
