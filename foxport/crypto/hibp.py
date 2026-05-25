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
from dataclasses import dataclass, field
from typing import Iterable

import requests

from foxport import __version__


_HIBP_RANGE = "https://api.pwnedpasswords.com/range"
_USER_AGENT = f"FoxPort/{__version__} (+https://github.com/SysAdminDoc/FoxPort)"


@dataclass(frozen=True)
class PwnedResult:
    """One pwned-password hit."""

    breach_count: int     # how many times the password appears in HIBP


# Tri-state used everywhere downstream (PasswordResult.hibp_status,
# RunManifest.network, GUI log copy). Keep the strings stable — they're
# part of the manifest schema (additive new states must be safe to ignore
# by older readers).
HIBP_STATUS_DISABLED = "disabled"
HIBP_STATUS_CHECKED_CLEAN = "checked-clean"
HIBP_STATUS_CHECKED_HITS = "checked-hits"
HIBP_STATUS_NETWORK_ERROR = "network-error"


@dataclass
class HibpScanResult:
    """Outcome of a batch HIBP scan.

    Before v1.3.1, ``scan_passwords`` returned a bare ``list`` of hits
    and the worker treated "no hits" as success even when every API call
    had failed. The tri-state status field makes "user opted in but the
    network rejected the scan" distinguishable from "no breaches".

    ``hits`` is the list of ``(origin_url, username, breach_count)``
    tuples (plaintext is never included). ``queries`` is the total
    password count offered to the scan. ``network_errors`` is the
    number of *unique prefixes* that the API failed on — duplicated
    failures across passwords sharing one prefix are counted once thanks
    to per-prefix caching.
    """

    hits: list[tuple[str, str, int]] = field(default_factory=list)
    queries: int = 0
    network_errors: int = 0

    @property
    def status(self) -> str:
        """Tri-state for downstream copy + manifest emission."""
        if self.hits:
            return HIBP_STATUS_CHECKED_HITS
        if self.network_errors and not self.queries:
            return HIBP_STATUS_NETWORK_ERROR
        if self.network_errors:
            # Mixed: some prefixes succeeded with no hits, others failed.
            # Prefer the cautious label — the user's password might be in
            # a breach we couldn't reach. Caller logs which.
            return HIBP_STATUS_NETWORK_ERROR
        return HIBP_STATUS_CHECKED_CLEAN


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
        # Track per-prefix failures so the caller can tell "scan ran cleanly
        # with zero hits" apart from "scan failed and the user got no
        # signal". Prefixes that already hit a network error stay
        # in this set so a retry on the same prefix doesn't double-count.
        self._failed_prefixes: set[str] = set()
        self._timeout = timeout

    @property
    def network_error_count(self) -> int:
        """Number of unique prefixes that failed to fetch during this client's
        lifetime. Counted once per prefix even when many passwords share it."""
        return len(self._failed_prefixes)

    def check(self, password: str) -> PwnedResult | None:
        """Return a :class:`PwnedResult` when the password is known-pwned, else None.

        Returns None on network failure too — callers degrade to "not checked".
        Use :pyattr:`network_error_count` to distinguish failure from
        genuine "not pwned".
        """
        if not password:
            return None
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        suffixes = self._cache.get(prefix)
        if suffixes is None:
            suffixes = self._fetch(prefix)
            if suffixes is None:
                self._failed_prefixes.add(prefix)
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
) -> HibpScanResult:
    """Run a list of `(origin_url, username, plaintext)` tuples through HIBP.

    Returns a :class:`HibpScanResult` carrying the hits AND the network-
    error count so callers can distinguish "checked, no breaches" from
    "scan failed, passwords NOT checked". The plaintext is NEVER
    surfaced on the result — the caller already has it, and shoving it
    into the result list invites accidental logging.
    """
    own_client = client is None
    client = client or HibpClient()
    result = HibpScanResult()
    try:
        for origin_url, username, plaintext in pairs:
            if not plaintext:
                continue
            result.queries += 1
            hit = client.check(plaintext)
            if hit is not None:
                result.hits.append((origin_url, username, hit.breach_count))
        result.network_errors = client.network_error_count
    finally:
        if own_client:
            client.close()
    return result
