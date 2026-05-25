"""Version-skew guard for the NSS direct-write path.

We can't load real ``nss3.dll`` in CI (no Firefox install on the runners),
so these tests target the small unit pieces of the guard:

* ``_is_version_compatible()`` parses "X.Y" strings safely and refuses
  major versions below 3 (the bar at which PK11SDR ABI has been stable).
* Empty / malformed version strings fail open (we'd rather try to encrypt
  than refuse a working portable Firefox build because it stripped the
  symbol).
* ``NSSLibrary.version`` is preserved through load_nss when present.
* ``open_session()`` refuses when ``require_compatible_version=True`` and
  the loaded library reports an unsafe version; ``FOXPORT_NSS_FORCE``
  overrides the refusal for power users.
"""

from __future__ import annotations

import pytest

from foxport.crypto import nss as nss_mod
from foxport.crypto.nss import (
    NSSLibrary,
    NSSVersionMismatchError,
    _is_version_compatible,
)


@pytest.mark.parametrize(
    "version,expected",
    [
        ("3.95", True),
        ("3.0", True),
        ("4.1", True),
        ("3.105", True),     # double-digit minor
        ("2.99", False),     # below the 3.x bar
        ("1.0", False),
        ("", True),          # missing → fail open (logged warning path)
        ("not a version", True),  # malformed → fail open
    ],
)
def test_version_compatibility(version: str, expected: bool):
    assert _is_version_compatible(version) is expected


def test_open_session_refuses_low_version(monkeypatch, tmp_path):
    """When the loaded NSS reports 2.x, we refuse direct-write."""

    fake_profile_dir = tmp_path / "profile"
    fake_profile_dir.mkdir()

    class _FakeProfile:
        profile_dir = fake_profile_dir
        label = "Fake/Firefox"

    def fake_load_nss():
        # Build a minimal NSSLibrary stand-in. The handle isn't dereferenced
        # because the version guard short-circuits before NSS_Init runs.
        return NSSLibrary(handle=object(), install_path=tmp_path / "nss3.dll", version="2.99")

    monkeypatch.setattr(nss_mod, "load_nss", fake_load_nss)
    monkeypatch.delenv("FOXPORT_NSS_FORCE", raising=False)

    with pytest.raises(NSSVersionMismatchError, match="2.99"):
        nss_mod.open_session(_FakeProfile(), require_compatible_version=True)


def test_open_session_override_via_env(monkeypatch, tmp_path):
    """FOXPORT_NSS_FORCE=1 should let a power user bypass the guard.

    We can't actually open a session against a fake library handle (NSS_Init
    isn't bound), so we patch NSSSession to a no-op object that records the
    library it was handed and assert the override let us through the guard.
    """

    fake_profile_dir = tmp_path / "profile"
    fake_profile_dir.mkdir()

    class _FakeProfile:
        profile_dir = fake_profile_dir
        label = "Fake/Firefox"

    def fake_load_nss():
        return NSSLibrary(handle=object(), install_path=tmp_path / "nss3.dll", version="2.99")

    captured: dict = {}

    class _StubSession:
        def __init__(self, lib, profile_dir, master_password=""):
            captured["lib"] = lib
            captured["profile_dir"] = profile_dir
            captured["master_password"] = master_password

    monkeypatch.setattr(nss_mod, "load_nss", fake_load_nss)
    monkeypatch.setattr(nss_mod, "NSSSession", _StubSession)
    monkeypatch.setenv("FOXPORT_NSS_FORCE", "1")

    # Should not raise.
    nss_mod.open_session(_FakeProfile(), require_compatible_version=True)
    assert captured["lib"].version == "2.99"


def test_open_session_compatible_version_skips_guard(monkeypatch, tmp_path):
    """A real 3.x version is accepted without env-var override."""

    fake_profile_dir = tmp_path / "profile"
    fake_profile_dir.mkdir()

    class _FakeProfile:
        profile_dir = fake_profile_dir
        label = "Fake/Firefox"

    def fake_load_nss():
        return NSSLibrary(handle=object(), install_path=tmp_path / "nss3.dll", version="3.95")

    class _StubSession:
        def __init__(self, lib, profile_dir, master_password=""):
            self.lib = lib

    monkeypatch.setattr(nss_mod, "load_nss", fake_load_nss)
    monkeypatch.setattr(nss_mod, "NSSSession", _StubSession)
    monkeypatch.delenv("FOXPORT_NSS_FORCE", raising=False)

    session = nss_mod.open_session(_FakeProfile(), require_compatible_version=True)
    assert session.lib.version == "3.95"
