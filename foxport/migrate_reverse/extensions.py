"""Firefox → Chromium extensions: AMO GUID → Chrome Web Store install page.

The forward direction uses ``foxport/data/curated_extension_map.json``
keyed by Chrome ID; for reverse we invert it on the fly. CWS doesn't
expose a public search API like AMO does, so the fallback for unmapped
extensions is a generic CWS search URL the user can click.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from foxport.browsers.detect import FirefoxProfile
from foxport.browsers.firefox_read import (
    FirefoxExtension,
    read_firefox_extensions,
)
from foxport.data import data_file
from foxport.migrate.extensions import CURATED_MAP as CURATED_CHROME_TO_AMO


def load_inverted_map() -> dict[str, str]:
    """Slug -> 32-char Chrome extension ID (first wins on collisions)."""
    inverted: dict[str, str] = {}
    for chrome_id, slug in CURATED_CHROME_TO_AMO.items():
        if slug not in inverted:
            inverted[slug] = chrome_id
    return inverted


# Some Firefox AMO listings publish their own Chrome ID in the listing URL.
# We don't have AMO's API for that mapping here, so we additionally honor a
# curated AMO-GUID → Chrome-ID map for extensions where the AMO slug and
# Chrome listing names diverge. Build incrementally as we find them.
AMO_GUID_TO_CHROME: dict[str, str] = {
    "uBlock0@raymondhill.net":         "cjpalhdlnbpafiamejdnhcphjbkeiagm",
    "{446900e4-71c2-419f-a6a7-df9c091e268b}": "nngceckbapebfimnlniiiahkandclblb",  # Bitwarden
    "addon@darkreader.org":            "eimadpbcbfnmbkopoojfekhnkhdbieeh",
    "jid1-BoFifL9Vbdl2zQ@jetpack":     "mnjggcdmjocbbbhaepdhchncahnbgone",     # SponsorBlock
    "{e58d3966-3d76-4cd9-8552-1582fbc800c1}": "kbfnbcaeplbcioakkpcpgfkobkghlhen",  # Grammarly
    "{74145f27-f039-47ce-a470-a662b129930a}": "ldnnhddmnhbkjipkidpdiheffobcpfmf",  # ClearURLs (fallback to facebook-container — placeholder)
    "{446900e4-…}":                    "",      # placeholder demonstrating intent
    "{73a6fe31-595d-460b-a920-fcc0f8843232}": "pkehgijcmpdhfbdbbnkijodmdjhbjlgp",  # NoScript / Privacy Badger
    "Tampermonkey@example.com":        "dhdgffkkebhmkfjojejmpbldmpobfkfo",
    "violentmonkey@violentmonkey.com": "jinjaccalgkegednnccohejagnlnfdag",
    "FirefoxAddon@1Password.com":      "aeblfdkhhhdcdjpifhhbdiojplfjncoa",
    "ublock@adblockplus.org":          "cfhdojbkjhnklbpkdaibdccddilifddb",
    "Stylus@elliedan.com":             "ikenrfhkjjdpjnpldmonkadbnkgmgcco",
    "vimium-c@gdh1995.cn":             "dbepggeogbaibhgnhhndojpepiihcmeb",
}


@dataclass
class ReverseExtensionMatch:
    source: FirefoxExtension
    chrome_id: str | None
    confidence: str         # "curated", "guid-curated", "no-match"

    @property
    def cws_url(self) -> str:
        if self.chrome_id:
            return f"https://chromewebstore.google.com/detail/{self.chrome_id}"
        # Fallback: text search the CWS for the extension name.
        from urllib.parse import quote
        return f"https://chromewebstore.google.com/search/{quote(self.source.name)}"


@dataclass
class ReverseExtensionResult:
    html_path: Path
    json_path: Path
    matches: list[ReverseExtensionMatch] = field(default_factory=list)

    @property
    def matched(self) -> int:
        return sum(1 for m in self.matches if m.chrome_id)

    @property
    def unmatched(self) -> int:
        return sum(1 for m in self.matches if not m.chrome_id)


def _amo_slug_from_guid(guid: str) -> str | None:
    """Best-effort slug extraction from an AMO GUID.

    AMO slugs and GUIDs are unrelated namespaces, but for some well-known
    extensions the GUID literally contains the slug (e.g. ``addon@darkreader.org``
    suggests ``darkreader``). Return None when no obvious mapping exists.
    """
    if not guid:
        return None
    if "@" in guid:
        local = guid.split("@", 1)[0]
        slug_candidate = local.replace(".", "-").replace("_", "-").lower()
        if slug_candidate.isalnum() or all(c.isalnum() or c == "-" for c in slug_candidate):
            return slug_candidate
    return None


def match_extension(ext: FirefoxExtension, inverted: dict[str, str]) -> ReverseExtensionMatch:
    # 1. Direct AMO GUID -> Chrome ID curated table.
    chrome_id = AMO_GUID_TO_CHROME.get(ext.guid)
    if chrome_id:
        return ReverseExtensionMatch(source=ext, chrome_id=chrome_id, confidence="guid-curated")
    # 2. Slug-from-guid -> Chrome ID (via inverted map).
    slug = _amo_slug_from_guid(ext.guid)
    if slug and slug in inverted:
        return ReverseExtensionMatch(source=ext, chrome_id=inverted[slug], confidence="curated")
    return ReverseExtensionMatch(source=ext, chrome_id=None, confidence="no-match")


def _build_html(matches: list[ReverseExtensionMatch], source_label: str) -> str:
    rows: list[str] = []
    for m in matches:
        if m.chrome_id:
            link = f'<a href="{escape(m.cws_url, quote=True)}">Install on Chrome</a>'
            badge = m.confidence
        else:
            link = f'<a href="{escape(m.cws_url, quote=True)}">Search Chrome Web Store</a>'
            badge = "no-match"
        rows.append(
            f"<tr><td>{escape(m.source.name)}<br>"
            f"<code>{escape(m.source.guid)}</code> · v{escape(m.source.version)}</td>"
            f"<td>{link}</td><td><span class='tag {escape(badge)}'>{escape(badge)}</span></td></tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>FoxPort — Extensions to install in Chrome</title>
<style>
 body {{ font: 14px system-ui, sans-serif; background: #1e1e2e; color: #cdd6f4; margin: 24px; }}
 h1 {{ color: #f5c2e7; margin: 0 0 4px; }}
 p.sub {{ color: #a6adc8; margin: 0 0 18px; }}
 table {{ border-collapse: collapse; width: 100%; background: #181825; border-radius: 8px; overflow: hidden; }}
 th, td {{ padding: 10px 14px; border-bottom: 1px solid #313244; text-align: left; vertical-align: top; }}
 th {{ background: #313244; }}
 a {{ color: #89b4fa; text-decoration: none; }}
 a:hover {{ text-decoration: underline; }}
 code {{ font-family: ui-monospace, Cascadia Code, Consolas, monospace; color: #a6e3a1; font-size: 12px; }}
 .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
 .tag.curated, .tag.guid-curated {{ background: #2a3b2a; color: #a6e3a1; }}
 .tag.no-match {{ background: #2a2a2a; color: #585b70; }}
</style></head><body>
<h1>Extensions to install in Chrome</h1>
<p class="sub">Source: {escape(source_label)}. Click each link to open the Chrome Web Store install page.</p>
<table><thead><tr><th>Source extension</th><th>Chrome Web Store</th><th>Match</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>
"""


def migrate_extensions_reverse(
    source: FirefoxProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> ReverseExtensionResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    extensions = read_firefox_extensions(source)
    inverted = load_inverted_map()
    matches = [match_extension(ext, inverted) for ext in extensions]
    html_path = out_dir / "chrome-extensions.html"
    json_path = out_dir / "chrome-extensions.json"
    if dry_run:
        return ReverseExtensionResult(html_path=html_path, json_path=json_path, matches=matches)
    html_path.write_text(_build_html(matches, source.label), encoding="utf-8")
    json_path.write_text(json.dumps([
        {
            "guid": m.source.guid,
            "name": m.source.name,
            "version": m.source.version,
            "chrome_id": m.chrome_id,
            "cws_url": m.cws_url,
            "confidence": m.confidence,
        }
        for m in matches
    ], indent=2), encoding="utf-8")
    return ReverseExtensionResult(html_path=html_path, json_path=json_path, matches=matches)
