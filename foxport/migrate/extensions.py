"""Map installed Chromium extensions to their Firefox AMO equivalents.

Strategy:

1. Look the Chrome extension ID up in a curated table of the most-used
   Chrome <-> Firefox pairs (uBlock Origin, Bitwarden, etc.). These are
   well-known and don't need a network round trip.
2. Otherwise hit the public AMO search API
   (``https://addons.mozilla.org/api/v5/addons/search/``) with the extension's
   reported name as the query, return the top hit if its slug looks like a
   reasonable match.
3. Anything else is reported as NO MATCH so the user can decide.

Results are written as an HTML page the user can open in their target browser
and click through to install. No network call is mandatory — offline runs
still produce a usable page from the curated table alone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Sequence

import requests

from foxport.browsers.chromium import ExtensionInfo
from foxport.browsers.detect import ChromiumProfile
from foxport.browsers.chromium import read_extensions


# Curated Chrome ID -> Firefox AMO slug map for the most common extensions.
# Add freely; an entry here suppresses the AMO API lookup for that ID.
CURATED_MAP: dict[str, str] = {
    "cjpalhdlnbpafiamejdnhcphjbkeiagm": "ublock-origin",
    "nngceckbapebfimnlniiiahkandclblb": "bitwarden-password-manager",
    "fdoeckjeapimfjeoddjlpdkogdfnighb": "ublock-origin-lite",
    "edibdbjcniadpccecjdfdjjppcpchdlm": "i-still-dont-care-about-cookies",
    "fihnjjcciajhdojfnbdddfaoknhalnja": "i-dont-care-about-cookies",
    "naepdomgkenhinolocfifgehidddafch": "browserpass-ce",
    "hlepfoohegkhhmjieoechaddaejaokhf": "refined-github-",
    "mnjggcdmjocbbbhaepdhchncahnbgone": "sponsorblock",
    "kbfnbcaeplbcioakkpcpgfkobkghlhen": "grammarly-1",
    "kdfieneakcjfaiglcfcgkidlkmlijjnh": "kagi-search-for-firefox",
    "gppongmhjkpfnbhagpmjfkannfbllamg": "wappalyzer",
    "fihnjjcciajhdojfnbdddfaoknhalnja": "i-dont-care-about-cookies",
    "ikenrfhkjjdpjnpldmonkadbnkgmgcco": "stylus",
    "clngdbkpkpeebahjckkjfobafhncgmne": "stylus",
    "jinjaccalgkegednnccohejagnlnfdag": "violentmonkey",
    "dhdgffkkebhmkfjojejmpbldmpobfkfo": "tampermonkey",
    "ekhagklcjbdpajgpjgmbionohlpdbjgc": "zotero-connector",
    "lifbcibllhkdhoafpjfnlhfpfgnpldfl": "skip-redirect",
    "ldnnhddmnhbkjipkidpdiheffobcpfmf": "facebook-container",
    "dbepggeogbaibhgnhhndojpepiihcmeb": "vimium-ff",
    "mhfkadjmiocppcphjbnmgilndalbghjm": "search-by-image",
    "lkbebcjgcmobigpeffafkodonchffocl": "bukubrow",
    "bhchdcejhohfmigjafbampogmaanbfkg": "auto-tab-discard",
    "jaoafjdoijdconemdmodhbfpianehlon": "skip-redirect",
}


@dataclass
class ExtensionMatch:
    """One row in the extensions report."""

    source: ExtensionInfo
    amo_slug: str | None
    amo_name: str | None
    confidence: str          # "curated", "amo-search", "no-match"

    @property
    def amo_url(self) -> str | None:
        if not self.amo_slug:
            return None
        return f"https://addons.mozilla.org/firefox/addon/{self.amo_slug}/"


@dataclass
class ExtensionResult:
    """Outcome of an extensions migration run."""

    html_path: Path
    json_path: Path
    matches: list[ExtensionMatch]

    @property
    def matched(self) -> int:
        return sum(1 for m in self.matches if m.amo_slug)

    @property
    def unmatched(self) -> int:
        return sum(1 for m in self.matches if not m.amo_slug)


_AMO_SEARCH = "https://addons.mozilla.org/api/v5/addons/search/"
_NAME_NORMALIZE = re.compile(r"[^a-z0-9]+")


def _normalize(name: str) -> str:
    return _NAME_NORMALIZE.sub("", name.lower())


def _amo_lookup(name: str, session: requests.Session) -> tuple[str, str] | None:
    """Hit AMO search and return ``(slug, name)`` of the top reasonable hit."""
    if not name:
        return None
    try:
        resp = session.get(
            _AMO_SEARCH,
            params={"q": name, "type": "extension", "app": "firefox", "page_size": 5},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    results = data.get("results") or []
    if not results:
        return None
    needle = _normalize(name)
    # First pass: a result whose name normalizes to exactly our query.
    for hit in results:
        hit_name = ""
        name_field = hit.get("name")
        if isinstance(name_field, dict):
            hit_name = name_field.get("en-US") or next(iter(name_field.values()), "")
        elif isinstance(name_field, str):
            hit_name = name_field
        if _normalize(hit_name) == needle:
            slug = hit.get("slug")
            if slug:
                return slug, hit_name
    # Second pass: substring overlap on the very first result.
    first = results[0]
    slug = first.get("slug")
    name_field = first.get("name")
    hit_name = ""
    if isinstance(name_field, dict):
        hit_name = name_field.get("en-US") or next(iter(name_field.values()), "")
    elif isinstance(name_field, str):
        hit_name = name_field
    if slug and needle and _normalize(hit_name).startswith(needle[:6]):
        return slug, hit_name
    return None


def _match_one(ext: ExtensionInfo, session: requests.Session | None) -> ExtensionMatch:
    slug = CURATED_MAP.get(ext.extension_id)
    if slug:
        return ExtensionMatch(
            source=ext,
            amo_slug=slug,
            amo_name=None,
            confidence="curated",
        )
    if session is not None:
        hit = _amo_lookup(ext.name, session)
        if hit:
            slug, hit_name = hit
            return ExtensionMatch(
                source=ext,
                amo_slug=slug,
                amo_name=hit_name,
                confidence="amo-search",
            )
    return ExtensionMatch(source=ext, amo_slug=None, amo_name=None, confidence="no-match")


def match_extensions(
    extensions: Sequence[ExtensionInfo],
    *,
    online: bool = True,
) -> list[ExtensionMatch]:
    """Resolve a list of installed extensions to AMO equivalents where possible."""
    session: requests.Session | None = None
    if online:
        session = requests.Session()
        session.headers.update({"User-Agent": "FoxPort/0.1 (+https://github.com/SysAdminDoc/FoxPort)"})
    try:
        return [_match_one(ext, session) for ext in extensions]
    finally:
        if session is not None:
            session.close()


def _build_html(matches: list[ExtensionMatch], source_label: str) -> str:
    rows: list[str] = []
    for m in matches:
        if m.amo_slug:
            link = f'<a href="{escape(m.amo_url or "", quote=True)}">Install on Firefox</a>'
            badge = m.confidence
        else:
            link = '<span class="no-match">NO MATCH on AMO</span>'
            badge = "no-match"
        rows.append(
            "<tr>"
            f"<td>{escape(m.source.name)}</td>"
            f"<td><code>{escape(m.source.extension_id)}</code></td>"
            f"<td>{escape(m.source.version)}</td>"
            f"<td>{link}</td>"
            f"<td>{escape(badge)}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FoxPort — Extensions to install</title>
<style>
 body {{ font: 14px system-ui, sans-serif; background: #1e1e2e; color: #cdd6f4; margin: 24px; }}
 h1 {{ color: #f5c2e7; margin: 0 0 4px; }}
 p.sub {{ color: #a6adc8; margin: 0 0 18px; }}
 table {{ border-collapse: collapse; width: 100%; background: #181825; border-radius: 8px; overflow: hidden; }}
 th, td {{ padding: 10px 14px; border-bottom: 1px solid #313244; text-align: left; vertical-align: top; }}
 th {{ background: #313244; color: #cdd6f4; }}
 tr:last-child td {{ border-bottom: none; }}
 a {{ color: #89b4fa; text-decoration: none; }}
 a:hover {{ text-decoration: underline; }}
 code {{ font-family: ui-monospace, Cascadia Code, Consolas, monospace; color: #a6e3a1; font-size: 12px; }}
 .no-match {{ color: #f38ba8; }}
</style>
</head>
<body>
<h1>Extensions to install in Firefox</h1>
<p class="sub">Source: {escape(source_label)}. Click each Install link to add the equivalent from addons.mozilla.org.</p>
<table>
 <thead><tr><th>Source extension</th><th>Chrome ID</th><th>Version</th><th>Firefox equivalent</th><th>Match</th></tr></thead>
 <tbody>
 {''.join(rows)}
 </tbody>
</table>
</body>
</html>
"""


def migrate_extensions(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    online: bool = True,
) -> ExtensionResult:
    """Enumerate ``profile``'s extensions and emit ``extensions.html`` + ``.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    extensions = read_extensions(profile)
    matches = match_extensions(extensions, online=online)

    html_path = out_dir / "extensions.html"
    html_path.write_text(_build_html(matches, profile.label), encoding="utf-8")

    json_path = out_dir / "extensions.json"
    json_path.write_text(json.dumps([
        {
            "id": m.source.extension_id,
            "name": m.source.name,
            "version": m.source.version,
            "amo_slug": m.amo_slug,
            "amo_url": m.amo_url,
            "amo_name": m.amo_name,
            "confidence": m.confidence,
        }
        for m in matches
    ], indent=2), encoding="utf-8")

    return ExtensionResult(html_path=html_path, json_path=json_path, matches=matches)
