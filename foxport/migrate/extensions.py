"""Map installed Chromium extensions to their Firefox AMO equivalents.

Resolution strategy, in order of confidence:

1. **Curated table** (`foxport/data/curated_extension_map.json`) — manually
   verified Chrome ID → AMO slug pairs. Highest signal, zero network.
2. **Gecko ID probe** — if the Chromium manifest declares
   ``browser_specific_settings.gecko.id`` (a published Firefox port of the
   same extension), look it up via AMO's GUID-aware detail endpoint
   (``/api/v5/addons/addon/{guid}/``). 100%-confidence match when it resolves.
3. **AMO name search** — query ``/addons/search/`` with the localized
   extension name and pick the best hit.
4. **Permission overlap** — for non-curated matches, compare Chrome's
   declared permissions to the candidate's AMO ``permissions`` list and
   downgrade confidence when the overlap is poor.

Results are written as an HTML page the user can open in their target
browser and click through to install. The ``extensions.json`` companion
file is machine-readable for downstream tools.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Iterable, Sequence

import requests

from foxport.browsers.chromium import ExtensionInfo, read_extensions
from foxport.browsers.detect import ChromiumProfile
from foxport.data import data_file


_AMO_BASE = "https://addons.mozilla.org/api/v5"
_AMO_SEARCH = f"{_AMO_BASE}/addons/search/"
_AMO_DETAIL = f"{_AMO_BASE}/addons/addon"
_NAME_NORMALIZE = re.compile(r"[^a-z0-9]+")
_USER_AGENT = "FoxPort/0.4.0 (+https://github.com/SysAdminDoc/FoxPort)"


def load_curated_map() -> dict[str, str]:
    """Flatten the bundled curated map JSON into a single id -> slug dict."""
    path = data_file("curated_extension_map.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            for ext_id, slug in value.items():
                if isinstance(ext_id, str) and isinstance(slug, str):
                    out[ext_id] = slug
    return out


CURATED_MAP: dict[str, str] = load_curated_map()


@dataclass
class ExtensionMatch:
    """One row in the extensions report."""

    source: ExtensionInfo
    amo_slug: str | None
    amo_name: str | None
    amo_guid: str | None
    amo_users: int | None
    amo_rating: float | None
    amo_permissions: tuple[str, ...]
    confidence: str          # "curated", "gecko-id", "amo-exact", "amo-search", "no-match"
    permission_overlap: float | None
    already_installed: bool = False

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

    @property
    def already_installed(self) -> int:
        return sum(1 for m in self.matches if m.already_installed)


def _normalize(name: str) -> str:
    return _NAME_NORMALIZE.sub("", name.lower())


def _resolve_amo_name(payload: object) -> str:
    """AMO returns ``name`` as either a string or a {locale: string} dict."""
    if isinstance(payload, dict):
        return str(payload.get("en-US") or next(iter(payload.values()), ""))
    if isinstance(payload, str):
        return payload
    return ""


def _hit_to_match_fields(hit: dict) -> dict:
    """Pluck the AMO response fields FoxPort cares about."""
    current = hit.get("current_version") or {}
    file_info = current.get("file") or {}
    permissions = file_info.get("permissions") or []
    host_perms = file_info.get("host_permissions") or []
    ratings = hit.get("ratings") or {}
    return {
        "amo_slug": hit.get("slug"),
        "amo_name": _resolve_amo_name(hit.get("name")),
        "amo_guid": hit.get("guid"),
        "amo_users": hit.get("average_daily_users"),
        "amo_rating": ratings.get("average"),
        "amo_permissions": tuple(str(p) for p in (list(permissions) + list(host_perms))),
        "amo_status": hit.get("status", "public"),
        "is_disabled": bool(hit.get("is_disabled", False)),
    }


def _amo_get(session: requests.Session, url: str, params: dict | None = None) -> dict | None:
    try:
        resp = session.get(url, params=params, timeout=8)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _amo_detail(session: requests.Session, slug_or_guid: str) -> dict | None:
    return _amo_get(session, f"{_AMO_DETAIL}/{slug_or_guid}/")


def _amo_search(session: requests.Session, query: str) -> list[dict]:
    data = _amo_get(session, _AMO_SEARCH, {
        "q": query, "type": "extension", "app": "firefox", "page_size": 5,
    })
    if not data:
        return []
    return data.get("results") or []


def _permission_overlap(source_perms: Iterable[str], amo_perms: Iterable[str]) -> float:
    """Jaccard similarity of permission sets, 0.0–1.0."""
    a = {p.lower() for p in source_perms}
    b = {p.lower() for p in amo_perms}
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _confidence_for(overlap: float | None, default: str) -> str:
    if overlap is None:
        return default
    if overlap >= 0.6:
        return default            # keep the high-tier label
    if overlap >= 0.3:
        return f"{default}-medium"
    return f"{default}-low"


def _match_one(
    ext: ExtensionInfo,
    session: requests.Session | None,
) -> ExtensionMatch:
    base = dict(
        source=ext,
        amo_slug=None,
        amo_name=None,
        amo_guid=None,
        amo_users=None,
        amo_rating=None,
        amo_permissions=(),
        confidence="no-match",
        permission_overlap=None,
    )

    # 1. Curated map — highest confidence, no network needed.
    slug = CURATED_MAP.get(ext.extension_id)
    if slug:
        return ExtensionMatch(**{**base, "amo_slug": slug, "confidence": "curated"})

    if session is None:
        return ExtensionMatch(**base)

    # 2. Gecko ID probe — if the manifest declares its Firefox identity, ask AMO directly.
    if ext.gecko_id:
        detail = _amo_detail(session, ext.gecko_id)
        if detail and detail.get("status") == "public" and not detail.get("is_disabled"):
            fields = _hit_to_match_fields(detail)
            overlap = _permission_overlap(
                ext.chrome_permissions + ext.chrome_host_permissions,
                fields["amo_permissions"],
            )
            return ExtensionMatch(
                source=ext,
                amo_slug=fields["amo_slug"],
                amo_name=fields["amo_name"],
                amo_guid=fields["amo_guid"],
                amo_users=fields["amo_users"],
                amo_rating=fields["amo_rating"],
                amo_permissions=fields["amo_permissions"],
                confidence="gecko-id",
                permission_overlap=overlap,
            )

    # 3. AMO name search — pick best hit by exact-name then prefix overlap.
    if ext.name:
        results = _amo_search(session, ext.name)
        results = [r for r in results if r.get("status") == "public" and not r.get("is_disabled")]
        if results:
            needle = _normalize(ext.name)
            ranked: list[tuple[int, dict]] = []
            for hit in results:
                hit_name = _resolve_amo_name(hit.get("name"))
                normalized = _normalize(hit_name)
                score = 0
                if normalized == needle:
                    score = 100
                elif normalized.startswith(needle[:6] if len(needle) >= 6 else needle):
                    score = 50
                else:
                    score = 10
                ranked.append((score, hit))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            top_score, top_hit = ranked[0]
            confidence_tier = "amo-exact" if top_score == 100 else "amo-search"
            fields = _hit_to_match_fields(top_hit)
            overlap = _permission_overlap(
                ext.chrome_permissions + ext.chrome_host_permissions,
                fields["amo_permissions"],
            )
            return ExtensionMatch(
                source=ext,
                amo_slug=fields["amo_slug"],
                amo_name=fields["amo_name"],
                amo_guid=fields["amo_guid"],
                amo_users=fields["amo_users"],
                amo_rating=fields["amo_rating"],
                amo_permissions=fields["amo_permissions"],
                confidence=_confidence_for(overlap, confidence_tier),
                permission_overlap=overlap,
            )

    return ExtensionMatch(**base)


def match_extensions(
    extensions: Sequence[ExtensionInfo],
    *,
    online: bool = True,
    already_installed_guids: set[str] | None = None,
) -> list[ExtensionMatch]:
    """Resolve installed extensions to AMO equivalents and tag dupes."""
    already_installed_guids = already_installed_guids or set()
    session: requests.Session | None = None
    if online:
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        out: list[ExtensionMatch] = []
        for ext in extensions:
            match = _match_one(ext, session)
            if match.amo_guid and match.amo_guid in already_installed_guids:
                match.already_installed = True
            out.append(match)
        return out
    finally:
        if session is not None:
            session.close()


# ---------------------------------------------------------------------- Rendering

_CSS = """
body { font: 14px system-ui, sans-serif; background: #1e1e2e; color: #cdd6f4; margin: 24px; }
h1 { color: #f5c2e7; margin: 0 0 4px; }
p.sub { color: #a6adc8; margin: 0 0 18px; }
.summary { display: flex; gap: 18px; margin: 0 0 22px; flex-wrap: wrap; }
.stat { background: #181825; border: 1px solid #313244; border-radius: 8px; padding: 12px 18px; min-width: 130px; }
.stat .n { font-size: 22px; font-weight: 700; color: #cdd6f4; }
.stat .l { font-size: 12px; color: #a6adc8; text-transform: uppercase; letter-spacing: 1px; }
table { border-collapse: collapse; width: 100%; background: #181825; border-radius: 8px; overflow: hidden; }
th, td { padding: 10px 14px; border-bottom: 1px solid #313244; text-align: left; vertical-align: top; }
th { background: #313244; color: #cdd6f4; }
tr:last-child td { border-bottom: none; }
a { color: #89b4fa; text-decoration: none; }
a:hover { text-decoration: underline; }
code { font-family: ui-monospace, Cascadia Code, Consolas, monospace; color: #a6e3a1; font-size: 12px; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.tag.curated   { background: #2a3b2a; color: #a6e3a1; }
.tag.gecko-id  { background: #2a3b2a; color: #a6e3a1; }
.tag.amo-exact { background: #2a3445; color: #89b4fa; }
.tag.amo-search { background: #3b3a2a; color: #f9e2af; }
.tag.amo-search-medium, .tag.amo-exact-medium { background: #3b3a2a; color: #f9e2af; }
.tag.amo-search-low, .tag.amo-exact-low { background: #3b2a2a; color: #fab387; }
.tag.no-match  { background: #2a2a2a; color: #585b70; }
.installed { color: #6c7086; text-decoration: line-through; }
.perm-list { color: #a6adc8; font-size: 11px; max-width: 260px; }
.row-installed td { background: #1a1a26; }
"""


def _build_html(matches: list[ExtensionMatch], source_label: str) -> str:
    matched = sum(1 for m in matches if m.amo_slug)
    already = sum(1 for m in matches if m.already_installed)
    no_match = sum(1 for m in matches if not m.amo_slug)
    rows: list[str] = []
    for m in matches:
        installed_cls = " row-installed" if m.already_installed else ""
        name_cls = " installed" if m.already_installed else ""
        if m.amo_slug:
            label = "Already installed" if m.already_installed else "Install on Firefox"
            link = f'<a href="{escape(m.amo_url or "", quote=True)}">{label}</a>'
        else:
            link = '<span style="color:#f38ba8">No AMO match</span>'
        extras: list[str] = []
        if m.amo_users is not None:
            extras.append(f"{int(m.amo_users):,} users")
        if m.amo_rating is not None:
            extras.append(f"{m.amo_rating:.1f}★")
        if m.permission_overlap is not None:
            extras.append(f"{int(m.permission_overlap * 100)}% perm overlap")
        extras_html = ' &middot; '.join(escape(x) for x in extras) if extras else ""
        perms_preview = ""
        if m.amo_permissions:
            sample = ", ".join(m.amo_permissions[:6])
            if len(m.amo_permissions) > 6:
                sample += f", +{len(m.amo_permissions) - 6} more"
            perms_preview = f'<div class="perm-list">Will request: {escape(sample)}</div>'
        rows.append(
            f'<tr class="row-installed-tag{installed_cls}">'
            f'<td><span class="{name_cls.strip()}">{escape(m.source.name)}</span><br>'
            f'<code>{escape(m.source.extension_id)}</code> &middot; v{escape(m.source.version)}</td>'
            f'<td>{link}<br><span style="color:#a6adc8">{extras_html}</span>{perms_preview}</td>'
            f'<td><span class="tag {escape(m.confidence)}">{escape(m.confidence)}</span></td>'
            f'</tr>'
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>FoxPort — Extensions to install</title>
<style>{_CSS}</style></head>
<body>
<h1>Extensions to install in Firefox</h1>
<p class="sub">Source: {escape(source_label)}. Open this page in your Firefox-family browser and click each Install link.</p>
<div class="summary">
 <div class="stat"><div class="n">{matched}</div><div class="l">Matched</div></div>
 <div class="stat"><div class="n">{already}</div><div class="l">Already installed</div></div>
 <div class="stat"><div class="n">{no_match}</div><div class="l">No AMO match</div></div>
 <div class="stat"><div class="n">{len(matches)}</div><div class="l">Total</div></div>
</div>
<table>
 <thead><tr><th>Source extension</th><th>Firefox equivalent</th><th>Match</th></tr></thead>
 <tbody>
 {''.join(rows)}
 </tbody>
</table>
</body></html>
"""


def migrate_extensions(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    online: bool = True,
    already_installed_guids: set[str] | None = None,
    dry_run: bool = False,
) -> ExtensionResult:
    """Enumerate ``profile``'s extensions and emit ``extensions.html`` + ``.json``.

    Dry-run skips the network-fanout AMO calls (returns curated/no-match only)
    and writes nothing to disk.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    extensions = read_extensions(profile)
    matches = match_extensions(
        extensions,
        online=online and not dry_run,
        already_installed_guids=already_installed_guids,
    )

    html_path = out_dir / "extensions.html"
    json_path = out_dir / "extensions.json"
    if dry_run:
        return ExtensionResult(html_path=html_path, json_path=json_path, matches=matches)
    html_path.write_text(_build_html(matches, profile.label), encoding="utf-8")
    json_path.write_text(json.dumps([
        {
            "id": m.source.extension_id,
            "name": m.source.name,
            "version": m.source.version,
            "gecko_id": m.source.gecko_id,
            "amo_slug": m.amo_slug,
            "amo_url": m.amo_url,
            "amo_name": m.amo_name,
            "amo_guid": m.amo_guid,
            "amo_users": m.amo_users,
            "amo_rating": m.amo_rating,
            "amo_permissions": list(m.amo_permissions),
            "confidence": m.confidence,
            "permission_overlap": m.permission_overlap,
            "already_installed": m.already_installed,
        }
        for m in matches
    ], indent=2), encoding="utf-8")

    return ExtensionResult(html_path=html_path, json_path=json_path, matches=matches)
