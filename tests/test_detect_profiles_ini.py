"""Defensive parsing of Firefox ``profiles.ini``.

Real-world profiles.ini files can be hand-edited with non-canonical
``IsRelative`` values ("yes" / "true") or include sections we don't
recognize. Pre-v1.3.2 the parser raised ``ValueError`` on
``IsRelative=yes`` and silently returned the empty list, which made the
Target picker look like every profile had vanished.

These tests pin the defensive contract: parse what we can; never raise.
"""

from __future__ import annotations

from pathlib import Path

from foxport.browsers.detect import _parse_profiles_ini


def _write_ini(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "profiles.ini"
    path.write_text(body, encoding="utf-8")
    return path


def _make_profile_dir(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_parse_valid_profiles_ini_returns_each_profile(tmp_path: Path):
    """Happy path: a canonical profiles.ini with two profiles + install
    default. Both profiles must surface; the install-default one must
    be flagged as default.
    """

    _make_profile_dir(tmp_path, "abc.default-release")
    _make_profile_dir(tmp_path, "xyz.dev-edition")
    ini = _write_ini(tmp_path, """\
[Install4F96D1932A9F858E]
Default=abc.default-release
Locked=1

[Profile0]
Name=default-release
IsRelative=1
Path=abc.default-release
Default=1

[Profile1]
Name=dev-edition
IsRelative=1
Path=xyz.dev-edition
""")
    profiles = _parse_profiles_ini(ini, tmp_path)
    by_name = {p.profile_name: p for p in profiles}
    assert set(by_name) == {"default-release", "dev-edition"}
    assert by_name["default-release"].is_default is True


def test_parse_handles_non_numeric_is_relative(tmp_path: Path):
    """Hand-edited ``IsRelative=yes`` used to raise ValueError and
    silently nuke the whole parse.
    """

    _make_profile_dir(tmp_path, "abc.weird")
    ini = _write_ini(tmp_path, """\
[Profile0]
Name=weird
IsRelative=yes
Path=abc.weird
""")
    profiles = _parse_profiles_ini(ini, tmp_path)
    assert len(profiles) == 1
    assert profiles[0].profile_name == "weird"


def test_parse_skips_missing_profile_dirs(tmp_path: Path):
    """A profiles.ini that references a path which doesn't exist on disk
    (manual cleanup, stale entry) must not surface that profile —
    otherwise the wizard would offer an unwriteable target.
    """

    ini = _write_ini(tmp_path, """\
[Profile0]
Name=ghost
IsRelative=1
Path=does-not-exist
""")
    assert _parse_profiles_ini(ini, tmp_path) == []


def test_parse_tolerates_truncated_or_corrupt_ini(tmp_path: Path):
    """A truncated profiles.ini (e.g. write killed mid-flight) must not
    crash the wizard's Target page. Return an empty list and let the
    caller fall back to "no profiles found".
    """

    ini = _write_ini(tmp_path, "[Profile0\nName=oops")
    # configparser raises MissingSectionHeaderError on a malformed section
    # marker; we swallow it and return empty.
    assert _parse_profiles_ini(ini, tmp_path) == []


def test_parse_missing_file_returns_empty(tmp_path: Path):
    assert _parse_profiles_ini(tmp_path / "missing.ini", tmp_path) == []
