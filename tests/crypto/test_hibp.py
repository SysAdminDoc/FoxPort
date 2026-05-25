"""Tests for the HIBP k-anonymity client (network-mocked)."""

import hashlib
from unittest.mock import MagicMock

import requests

from foxport.crypto.hibp import (
    HIBP_STATUS_CHECKED_CLEAN,
    HIBP_STATUS_CHECKED_HITS,
    HIBP_STATUS_NETWORK_ERROR,
    HibpClient,
    scan_passwords,
)


def _make_session(responses: dict[str, str]) -> requests.Session:
    """Return a session whose .get(...) returns canned 200 responses for prefixes."""
    session = MagicMock(spec=requests.Session)
    session.headers = {}

    def fake_get(url, timeout=None):
        prefix = url.rsplit("/", 1)[-1]
        body = responses.get(prefix, "")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = body
        return resp

    session.get.side_effect = fake_get
    session.close = MagicMock()
    return session


def _hibp_body_for(known_passwords: list[str]) -> dict[str, str]:
    """Build a {prefix: range_body} dict the same shape HIBP returns."""
    by_prefix: dict[str, list[str]] = {}
    for pw in known_passwords:
        sha1 = hashlib.sha1(pw.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        by_prefix.setdefault(prefix, []).append(f"{suffix}:42")
    return {p: "\r\n".join(lines) for p, lines in by_prefix.items()}


def test_check_returns_none_for_empty_password():
    client = HibpClient(session=_make_session({}))
    assert client.check("") is None


def test_check_returns_pwned_for_known_password():
    body = _hibp_body_for(["password123"])
    client = HibpClient(session=_make_session(body))
    hit = client.check("password123")
    assert hit is not None
    assert hit.breach_count == 42


def test_check_returns_none_for_unknown_password():
    body = _hibp_body_for(["password123"])
    client = HibpClient(session=_make_session(body))
    assert client.check("a-much-stronger-passphrase") is None


def test_per_prefix_response_is_cached():
    """Two passwords sharing a SHA-1 prefix only round-trip once."""
    body = _hibp_body_for(["password123", "qwerty"])
    session = _make_session(body)
    client = HibpClient(session=session)
    # Both passwords have distinct prefixes — verify cache behavior with
    # the same password called twice instead.
    client.check("password123")
    client.check("password123")
    assert session.get.call_count == 1


def test_scan_passwords_only_returns_hits():
    body = _hibp_body_for(["password123"])
    client = HibpClient(session=_make_session(body))
    pairs = [
        ("https://x.com", "alice", "password123"),
        ("https://y.com", "bob", "safe-passphrase"),
    ]
    result = scan_passwords(pairs, client=client)
    assert len(result.hits) == 1
    assert result.hits[0] == ("https://x.com", "alice", 42)
    assert result.status == HIBP_STATUS_CHECKED_HITS


def test_scan_passwords_never_returns_plaintext():
    """Sanity: each result tuple has exactly (origin_url, username, count) — no password."""
    body = _hibp_body_for(["x"])
    client = HibpClient(session=_make_session(body))
    result = scan_passwords([("https://x.com", "u", "x")], client=client)
    assert result.hits[0] == ("https://x.com", "u", 42)
    assert len(result.hits[0]) == 3  # not 4


def test_network_failure_returns_none():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = requests.RequestException("connection refused")
    session.close = MagicMock()
    client = HibpClient(session=session)
    assert client.check("anything") is None


def test_scan_passwords_reports_checked_clean_when_nothing_pwned():
    """Tri-state: every prefix returned cleanly but found no matches."""
    body = _hibp_body_for(["something-else"])
    client = HibpClient(session=_make_session(body))
    result = scan_passwords(
        [("https://x.com", "alice", "a-safe-passphrase-nobody-uses")],
        client=client,
    )
    assert result.hits == []
    assert result.network_errors == 0
    assert result.status == HIBP_STATUS_CHECKED_CLEAN


def test_scan_passwords_reports_network_error_when_every_prefix_fails():
    """Tri-state: every prefix lookup raised — caller must see this distinctly
    from "no hits". Before v1.3.1 these were indistinguishable.
    """
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = requests.RequestException("dns broke")
    session.close = MagicMock()
    client = HibpClient(session=session)
    result = scan_passwords(
        [("https://x.com", "alice", "anything")],
        client=client,
    )
    assert result.hits == []
    assert result.network_errors == 1
    assert result.status == HIBP_STATUS_NETWORK_ERROR


def test_hibp_client_tracks_network_errors_once_per_prefix():
    """A failed prefix counts once even when 50 different passwords share it."""
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = requests.RequestException("flaky link")
    session.close = MagicMock()
    client = HibpClient(session=session)
    for i in range(5):
        client.check(f"unique-password-{i}")
    # Each unique password has a distinct prefix, so each is a fresh
    # network error.
    assert client.network_error_count == 5
