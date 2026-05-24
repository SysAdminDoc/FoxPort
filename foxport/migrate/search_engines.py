"""Search-engine migration — Chromium ``Web Data.keywords`` → Firefox-ready
JSON + an OpenSearch XML file per engine the user can drag-install.

Firefox's authoritative store is ``search.json.mozlz4`` (in the profile
root). It's hash-validated and the schema flips with each Firefox release,
so writing it directly is fragile. Instead, FoxPort emits:

* ``search-engines.json`` — A machine-readable inventory of every engine
  Chromium remembers, with URL, keyword, name, last-used time.
* ``search-engines/<slug>.xml`` — An OpenSearch description document per
  engine the user can open in Firefox to install with one click via
  ``Settings → Search → Add``.

Chromium's ``keywords`` table:
    id, short_name, keyword, favicon_url, url, safe_for_autoreplace,
    originating_url, date_created, usage_count, input_encodings,
    suggest_url, prepopulate_id, created_by_policy, last_modified,
    sync_guid, alternate_urls, image_url, search_url_post_params,
    suggest_url_post_params, image_url_post_params, new_tab_url,
    last_visited, is_active, starter_pack_id
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class SearchEngineResult:
    json_path: Path
    xml_dir: Path
    total: int
    written: int
    failures: list[str] = field(default_factory=list)


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "engine").strip().lower()).strip("-") or "engine"


def _web_data_path(profile: ChromiumProfile) -> Path | None:
    candidate = profile.profile_dir / "Web Data"
    return candidate if candidate.is_file() else None


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_search_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    return dest


def _build_opensearch(name: str, keyword: str, url_template: str, suggest_url: str = "") -> str:
    """Render an OpenSearch description document. Firefox installs these by URL."""
    # Chrome's URL templates use {searchTerms} already, which is the OpenSearch
    # standard token. Other tokens (e.g. {google:baseURL}) are Chrome-specific
    # and ignored / replaced with empty.
    cleaned_url = re.sub(r"\{(google|yahoo|baidu|microsoft)[^}]*\}", "", url_template)
    cleaned_suggest = re.sub(r"\{(google|yahoo|baidu|microsoft)[^}]*\}", "", suggest_url)
    suggest_block = ""
    if cleaned_suggest:
        suggest_block = (
            f'  <Url type="application/x-suggestions+json" template="{html_escape(cleaned_suggest, quote=True)}"/>\n'
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>{html_escape(name)}</ShortName>
  <Description>{html_escape(name)} (imported by FoxPort)</Description>
  <InputEncoding>UTF-8</InputEncoding>
  <Url type="text/html" method="GET" template="{html_escape(cleaned_url, quote=True)}"/>
{suggest_block}  <Alias>{html_escape(keyword or '')}</Alias>
</OpenSearchDescription>
"""


def migrate_search_engines(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> SearchEngineResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "search-engines.json"
    xml_dir = out_dir / "search-engines"

    failures: list[str] = []
    src = _web_data_path(profile)
    if not src:
        return SearchEngineResult(json_path=json_path, xml_dir=xml_dir,
                                   total=0, written=0, failures=failures)

    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            try:
                cur = conn.execute(
                    "SELECT short_name, keyword, url, suggest_url, last_visited, "
                    "usage_count, is_active FROM keywords"
                )
                rows = cur.fetchall()
            except sqlite3.DatabaseError as exc:
                failures.append(str(exc))
                rows = []
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)

    inventory: list[dict] = []
    written = 0
    if not dry_run:
        xml_dir.mkdir(parents=True, exist_ok=True)

    for short_name, keyword, url, suggest_url, last_visited, usage_count, is_active in rows:
        name = (short_name or "").strip()
        if not name or not url:
            continue
        slug = _slugify(name)
        entry = {
            "name": name,
            "keyword": keyword or "",
            "url": url,
            "suggest_url": suggest_url or "",
            "last_visited": last_visited,
            "usage_count": usage_count,
            "is_active": bool(is_active) if is_active is not None else True,
            "opensearch_file": f"{slug}.xml",
        }
        inventory.append(entry)
        if dry_run:
            continue
        try:
            (xml_dir / f"{slug}.xml").write_text(
                _build_opensearch(name, keyword or "", url, suggest_url or ""),
                encoding="utf-8",
            )
            written += 1
        except OSError as exc:
            failures.append(f"{name}: {exc}")

    if not dry_run:
        json_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    return SearchEngineResult(
        json_path=json_path,
        xml_dir=xml_dir,
        total=len(inventory),
        written=written,
        failures=failures,
    )
