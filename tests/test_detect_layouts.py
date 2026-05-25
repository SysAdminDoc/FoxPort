"""Profile-detection layout fixtures.

The detect helpers walk a per-platform browser registry; each entry
has a ``layout`` of either ``"profile"`` (canonical Chrome:
``User Data/Default``, ``User Data/Profile 1``, ...) or ``"flat"``
(Opera Stable / Opera GX: the single profile lives at the
``User Data`` root).

These tests build synthetic profile layouts via ``_enumerate_profile_subdirs``
+ ``_parse_profiles_ini`` and pin the contract independent of the
host machine. Pre-v1.4 the only detect-level test we shipped was
``test_detect_profiles_ini.py`` for the Firefox INI parser; this
expands coverage to the Chromium side.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foxport.browsers.detect import (
    ChromiumProfile,
    _enumerate_profile_subdirs,
    _parse_profiles_ini,
)


def _make_chromium_profile(parent: Path, name: str) -> Path:
    """Create a directory that looks like a real Chromium profile.

    The helper only checks for ``Preferences`` — the file's contents
    don't matter, only its presence.
    """

    profile = parent / name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "Preferences").write_text("{}", encoding="utf-8")
    return profile


def test_enumerate_profile_subdirs_finds_default_and_numbered(tmp_path: Path):
    """Default + Profile N is the canonical Chromium multi-profile layout."""

    user_data = tmp_path / "User Data"
    _make_chromium_profile(user_data, "Default")
    _make_chromium_profile(user_data, "Profile 1")
    _make_chromium_profile(user_data, "Profile 2")

    found = _enumerate_profile_subdirs(user_data)

    assert found == ["Default", "Profile 1", "Profile 2"]


def test_enumerate_skips_dirs_without_preferences_marker(tmp_path: Path):
    """A dir named "Default" with no Preferences must NOT count —
    Chrome won't have run there. Otherwise the wizard would offer a
    target that fails on the very first read.
    """

    user_data = tmp_path / "User Data"
    bogus = user_data / "Default"
    bogus.mkdir(parents=True)
    # Intentionally no Preferences file.

    assert _enumerate_profile_subdirs(user_data) == []


def test_enumerate_handles_missing_user_data_dir(tmp_path: Path):
    """A non-existent User Data dir must return [] rather than raising —
    detect_chromium iterates the registry and uses the empty result
    as "this browser isn't installed".
    """

    assert _enumerate_profile_subdirs(tmp_path / "nope") == []


def test_enumerate_includes_guest_profile_when_present(tmp_path: Path):
    """Guest Profile is a special-cased name that Chrome creates on
    "Browse as Guest" — when populated it has its own Preferences
    file. We surface it so the user can choose to migrate from it.
    """

    user_data = tmp_path / "User Data"
    _make_chromium_profile(user_data, "Default")
    _make_chromium_profile(user_data, "Guest Profile")

    found = _enumerate_profile_subdirs(user_data)

    assert "Guest Profile" in found
    assert "Default" in found


def test_enumerate_skips_non_profile_subdirs(tmp_path: Path):
    """User Data also contains ``Crashpad`` / ``GrShaderCache`` /
    ``GraphiteDawnCache`` / ``ShaderCache`` etc. None of those are
    profiles and must NOT surface in the Source picker.
    """

    user_data = tmp_path / "User Data"
    _make_chromium_profile(user_data, "Default")
    (user_data / "Crashpad").mkdir(parents=True)
    (user_data / "ShaderCache").mkdir(parents=True)
    # Even if a stray Preferences file lands in one of these, the name
    # filter rejects it — pin that explicitly.
    (user_data / "ShaderCache" / "Preferences").write_text("{}", encoding="utf-8")

    found = _enumerate_profile_subdirs(user_data)

    assert found == ["Default"]


def test_parse_profiles_ini_promotes_install_default(tmp_path: Path):
    """``[InstallXXX] Default=`` is the post-Firefox-67 way to mark the
    default profile (instead of per-section ``Default=1``). The parser
    must honor it so the Target picker's default-checkmark lands on
    the right profile.
    """

    _make_chromium_profile(tmp_path, "abc.default-release")
    _make_chromium_profile(tmp_path, "xyz.dev-edition")
    ini = tmp_path / "profiles.ini"
    ini.write_text("""\
[Install4F96D1932A9F858E]
Default=abc.default-release
Locked=1

[Profile0]
Name=default-release
IsRelative=1
Path=abc.default-release

[Profile1]
Name=dev-edition
IsRelative=1
Path=xyz.dev-edition
""", encoding="utf-8")

    profiles = _parse_profiles_ini(ini, tmp_path)
    by_name = {p.profile_name: p for p in profiles}

    assert by_name["default-release"].is_default is True
    assert by_name["dev-edition"].is_default is False


def test_parse_profiles_ini_handles_absolute_path(tmp_path: Path):
    """``IsRelative=0`` means ``Path`` is absolute — portable Firefox
    installs from a USB drive use this layout. The parser must honor
    it instead of joining against the ini's root.
    """

    portable = tmp_path / "portable" / "Profiles" / "default"
    portable.mkdir(parents=True)
    (portable / "Preferences").write_text("{}", encoding="utf-8")

    ini = tmp_path / "profiles.ini"
    ini.write_text(f"""\
[Profile0]
Name=portable
IsRelative=0
Path={portable.as_posix()}
""", encoding="utf-8")

    profiles = _parse_profiles_ini(ini, tmp_path)

    assert len(profiles) == 1
    assert profiles[0].profile_dir == portable
