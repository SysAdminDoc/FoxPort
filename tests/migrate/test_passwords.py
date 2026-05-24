"""Tests for the audit-pass invariants in foxport.migrate.passwords.

The key contract:

* ``_decrypt_all`` runs at most one decrypt call per row.
* ``total == decrypted + skipped_empty + failed`` for any completed
  (non-exception) run.
* HIBP path does NOT redecrypt — it consumes the same in-memory list
  the CSV writer used.
"""

from __future__ import annotations

from foxport.browsers.chromium import PasswordRow
from foxport.migrate.passwords import _decrypt_all


class _StubKey:
    """Lookalike for a Chromium master key — never touched by the test
    fakes because we monkey-patch decrypt_value at the module level."""


def _row(origin: str, username: str, blob: bytes) -> PasswordRow:
    return PasswordRow(
        origin_url=origin,
        action_url="",
        username=username,
        password_blob=blob,
        date_created=0,
        date_last_used=0,
        date_password_modified=0,
    )


def test_decrypt_all_skips_empty_blobs(monkeypatch):
    """Empty blobs are placeholders Chromium creates for 'Never save for
    this site' — they should count toward skipped_empty, not failed."""
    from foxport.migrate import passwords as pwmod

    def fake_decrypt(blob, key):
        return blob.decode("utf-8")

    monkeypatch.setattr(pwmod, "decrypt_value", fake_decrypt)
    rows = [
        _row("https://a", "alice", b"hunter2"),
        _row("https://b", "bob", b""),                # placeholder
        _row("https://c", "carol", b"correct horse"),
    ]
    decrypted, skipped_empty, failures = _decrypt_all(rows, _StubKey())
    assert len(decrypted) == 2
    assert skipped_empty == 1
    assert failures == []


def test_decrypt_all_counts_decryption_failures(monkeypatch):
    from foxport.crypto.dpapi import DecryptionError
    from foxport.migrate import passwords as pwmod

    def fake_decrypt(blob, key):
        if blob == b"BAD":
            raise DecryptionError("simulated DPAPI failure")
        return blob.decode("utf-8")

    monkeypatch.setattr(pwmod, "decrypt_value", fake_decrypt)
    rows = [
        _row("https://a", "alice", b"good"),
        _row("https://b", "bob", b"BAD"),
        _row("https://c", "carol", b"good2"),
    ]
    decrypted, skipped_empty, failures = _decrypt_all(rows, _StubKey())
    assert len(decrypted) == 2
    assert skipped_empty == 0
    assert len(failures) == 1
    assert "bob" in failures[0]


def test_decrypt_all_catches_unexpected_exceptions(monkeypatch):
    """A wrong-length master key raises ValueError, not DecryptionError —
    must not abort the whole batch."""
    from foxport.migrate import passwords as pwmod

    calls = {"n": 0}

    def fake_decrypt(blob, key):
        calls["n"] += 1
        if blob == b"BOOM":
            raise ValueError("AES key wrong length")
        return blob.decode("utf-8")

    monkeypatch.setattr(pwmod, "decrypt_value", fake_decrypt)
    rows = [
        _row("https://a", "alice", b"good"),
        _row("https://b", "bob", b"BOOM"),
        _row("https://c", "carol", b"good2"),
    ]
    decrypted, skipped_empty, failures = _decrypt_all(rows, _StubKey())
    assert len(decrypted) == 2
    assert skipped_empty == 0
    assert len(failures) == 1
    assert "ValueError" in failures[0]
    # And the third row was still processed (i.e. exception didn't abort).
    assert calls["n"] == 3


def test_decrypt_all_counts_empty_plaintext_as_skipped(monkeypatch):
    """A blob that decodes to '' is also a 'no password stored' shape —
    those land in skipped_empty, not in decrypted."""
    from foxport.migrate import passwords as pwmod

    def fake_decrypt(blob, key):
        return "" if blob == b"NULL" else blob.decode("utf-8")

    monkeypatch.setattr(pwmod, "decrypt_value", fake_decrypt)
    rows = [
        _row("https://a", "alice", b"good"),
        _row("https://b", "bob", b"NULL"),
    ]
    decrypted, skipped_empty, failures = _decrypt_all(rows, _StubKey())
    assert len(decrypted) == 1
    assert skipped_empty == 1
    assert failures == []


def test_decrypt_all_invariant_total_balance(monkeypatch):
    """Invariant: every input row lands in exactly one bucket."""
    from foxport.crypto.dpapi import DecryptionError
    from foxport.migrate import passwords as pwmod

    def fake_decrypt(blob, key):
        if blob == b"BAD":
            raise DecryptionError("nope")
        if blob == b"EMPTY":
            return ""
        return blob.decode("utf-8")

    monkeypatch.setattr(pwmod, "decrypt_value", fake_decrypt)
    rows = [
        _row("https://a", "alice", b"good"),
        _row("https://b", "bob", b""),       # empty blob → skipped
        _row("https://c", "carol", b"BAD"),  # decrypt fail → failure
        _row("https://d", "dan", b"EMPTY"),  # empty plain → skipped
        _row("https://e", "eve", b"good2"),
    ]
    decrypted, skipped_empty, failures = _decrypt_all(rows, _StubKey())
    assert len(decrypted) + skipped_empty + len(failures) == len(rows) == 5
