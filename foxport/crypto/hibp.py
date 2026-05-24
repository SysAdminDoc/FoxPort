"""Have-I-Been-Pwned 'Pwned Passwords' k-anonymity scan.

For each plaintext password:

1. SHA-1 hash the password.
2. Take the first 5 hex chars as the *prefix*.
3. Request ``api.pwnedpasswords.com/range/<prefix>`` — the API returns
   every (suffix : breach_count) pair for hashes starting with that prefix.
4. Scan the response for the remaining 35 chars.

The prefix-only query means the API never learns which password was
checked — it only sees the 5-char prefix that covers ~500 possible
hashes. The free public API requires no auth and has no documented rate
limit; we still cache per-prefix responses within a run to avoid
re-querying when many passwords share a prefix.

Reference: https://haveibeenpwned.com/API/v3
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

import requests


_HIBP_RANGE = "https://api.pwnedpasswords.com/range"
_USER_AGENT = "FoxPort/1.2 (+https://github.com/SysAdminDoc/FoxPort)"


@dataclass(frozen=True)
class PwnedResult:
    """One pwned-password hit."""

    breach_count: int     # how many times the password appears in HIBP


class HibpClient:
    """Thin client with per-prefix response caching."""

    def __init__(self, session: requests.Session | None = None, timeout: float = 8.0) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
            "Add-Padding": "true",      # extra noise so request size doesn't leak.
            "Accept-Encoding": "gzip",
        })
        self._cache: dict[str, dict[str, int]] = {}
        self._timeout = timeout

    def check(self, password: str) -> PwnedResult | None:
        """Return a :class:`PwnedResult` when the password is known-pwned, else None.

        Returns None on network failure too — callers degrade to "not checked".
        """
        if not password:
            return None
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        suffixes = self._cache.get(prefix)
        if suffixes is None:
            suffixes = self._fetch(prefix)
            if suffixes is None:
                return None
            self._cache[prefix] = suffixes
        count = suffixes.get(suffix)
        if count is None:
            return None
        return PwnedResult(breach_count=count)

    def close(self) -> None:
        self._session.close()

    def _fetch(self, prefix: str) -> dict[str, int] | None:
        try:
            resp = self._session.get(f"{_HIBP_RANGE}/{prefix}", timeout=self._timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        out: dict[str, int] = {}
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            suffix, count_str = line.split(":", 1)
            try:
                out[suffix.upper()] = int(count_str)
            except ValueError:
                continue
        return out


def scan_passwords(
    pairs: Iterable[tuple[str, str, str]],
    *,
    client: HibpClient | None = None,
) -> list[tuple[str, str, int]]:
    """Run a list of `(origin_url, username, plaintext)` tuples through HIBP.

    Returns the subset that came back as pwned, as
    `(origin_url, username, breach_count)`. The plaintext is NEVER returned —
    the caller already has it, and shoving it into the result list invites
    accidental logging.
    """
    own_client = client is None
    client = client or HibpClient()
    out: list[tuple[str, str, int]] = []
    try:
        for origin_url, username, plaintext in pairs:
            hit = client.check(plaintext)
            if hit is not None:
                out.append((origin_url, username, hit.breach_count))
    finally:
        if own_client:
            client.close()
    return out
