"""Hit AMO for every slug in the curated extension map and report broken / stale entries.

Usage:

    python scripts/check_curated_map.py
    python scripts/check_curated_map.py --json out/audit.json
    python scripts/check_curated_map.py --stale-months 24

Designed to run from CI on a monthly schedule. Returns non-zero if any
curated entry is missing or `is_disabled=True` on AMO.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from foxport.data import data_file


_AMO_DETAIL = "https://addons.mozilla.org/api/v5/addons/addon"
_USER_AGENT = "FoxPort-CuratedMapAuditor/1.0 (+https://github.com/SysAdminDoc/FoxPort)"


def _flatten(map_json: dict) -> dict[str, tuple[str, str]]:
    """Return id -> (category, slug)."""
    out: dict[str, tuple[str, str]] = {}
    for category, entries in map_json.items():
        if category.startswith("_") or not isinstance(entries, dict):
            continue
        for ext_id, slug in entries.items():
            if isinstance(ext_id, str) and isinstance(slug, str):
                out[ext_id] = (category, slug)
    return out


def _check_slug(session: requests.Session, slug: str) -> dict:
    try:
        resp = session.get(f"{_AMO_DETAIL}/{slug}/", timeout=10)
    except requests.RequestException as exc:
        return {"status": "network-error", "error": str(exc)}
    if resp.status_code == 404:
        return {"status": "404"}
    if resp.status_code != 200:
        return {"status": f"http-{resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"status": "non-json"}
    return {
        "status": "ok",
        "is_disabled": bool(data.get("is_disabled", False)),
        "amo_status": data.get("status"),
        "last_updated": data.get("last_updated"),
        "users": data.get("average_daily_users"),
        "guid": data.get("guid"),
    }


def _audit_reverse_map(session: requests.Session, sleep: float) -> tuple[list[tuple[str, str]], dict]:
    """Audit the hand-curated AMO-GUID -> Chrome-ID table used by reverse mode.

    Returns ``(broken_entries, results_by_guid)``. An entry is broken when
    the AMO detail endpoint returns 404 or marks ``is_disabled=true`` for
    the GUID. Network errors are not treated as broken so a flaky run
    doesn't paper over real removals.
    """

    from foxport.migrate_reverse.extensions import AMO_GUID_TO_CHROME

    results: dict[str, dict] = {}
    broken: list[tuple[str, str]] = []
    detail_by_guid = f"{_AMO_DETAIL}"
    print(f"Auditing {len(AMO_GUID_TO_CHROME)} reverse-map GUIDs against AMO...")
    for i, (guid, chrome_id) in enumerate(sorted(AMO_GUID_TO_CHROME.items())):
        # AMO's detail endpoint accepts a GUID (URL-encoded) in the slug
        # position. The forward auditor uses slugs; for reverse we use
        # GUIDs because the curated table is keyed on them.
        from urllib.parse import quote
        encoded = quote(guid, safe="")
        try:
            resp = session.get(f"{detail_by_guid}/{encoded}/", timeout=10)
        except requests.RequestException as exc:
            results[guid] = {"chrome_id": chrome_id, "status": "network-error",
                              "error": str(exc)}
            continue
        if resp.status_code == 404:
            results[guid] = {"chrome_id": chrome_id, "status": "404"}
            broken.append((guid, "404"))
            print(f"  [BROKEN] guid={guid} -> chrome={chrome_id}: 404")
        elif resp.status_code != 200:
            results[guid] = {"chrome_id": chrome_id,
                              "status": f"http-{resp.status_code}"}
        else:
            try:
                data = resp.json()
            except ValueError:
                results[guid] = {"chrome_id": chrome_id, "status": "non-json"}
                continue
            is_disabled = bool(data.get("is_disabled", False))
            results[guid] = {
                "chrome_id": chrome_id,
                "status": "ok",
                "is_disabled": is_disabled,
                "slug": data.get("slug"),
                "users": data.get("average_daily_users"),
            }
            if is_disabled:
                broken.append((guid, "is_disabled"))
                print(f"  [DISABLED] guid={guid}: AMO marks is_disabled=true")
        if (i + 1) % 5 == 0:
            print(f"  ... {i + 1}/{len(AMO_GUID_TO_CHROME)} reverse-map entries checked")
        time.sleep(sleep)
    return broken, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path,
                        help="Write per-entry audit report as JSON to this path")
    parser.add_argument("--stale-months", type=int, default=24,
                        help="Flag entries with last_updated older than this many months (default 24)")
    parser.add_argument("--strict-stale", action="store_true",
                        help="Exit non-zero if any entry is stale (default: stale is informational)")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Seconds between AMO requests to avoid rate limiting (default 0.5)")
    parser.add_argument("--include-reverse", action="store_true",
                        help="Also audit the AMO-GUID -> Chrome-ID reverse table used by "
                             "migrate-reverse. A broken reverse entry exits non-zero just like "
                             "a broken forward entry.")
    args = parser.parse_args()

    map_path = data_file("curated_extension_map.json")
    if not map_path.is_file():
        print(f"error: curated map not found at {map_path}", file=sys.stderr)
        return 2
    raw = json.loads(map_path.read_text(encoding="utf-8"))
    flat = _flatten(raw)
    # Self-check meta against reality first — catches doc drift even when
    # the network half of the audit can't run. The v1.2 audit pass shipped
    # "67-entry" docs for a 63-entry map; this guard prevents that recurring.
    meta = raw.get("_meta", {}) if isinstance(raw.get("_meta"), dict) else {}
    declared_count = meta.get("entry_count")
    declared_cats = meta.get("category_count")
    actual_cats = sum(
        1 for k, v in raw.items()
        if not k.startswith("_") and isinstance(v, dict)
    )
    meta_errors: list[str] = []
    if declared_count is not None and declared_count != len(flat):
        meta_errors.append(
            f"_meta.entry_count={declared_count} but actual is {len(flat)}"
        )
    if declared_cats is not None and declared_cats != actual_cats:
        meta_errors.append(
            f"_meta.category_count={declared_cats} but actual is {actual_cats}"
        )
    if meta_errors:
        for err in meta_errors:
            print(f"  [META] {err}", file=sys.stderr)
        # Fail closed — fixing _meta is a docs-only patch and prevents the
        # README from drifting again silently.
        return 3
    print(f"Auditing {len(flat)} curated entries against AMO...")

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"})

    results: dict[str, dict] = {}
    broken: list[tuple[str, str, str]] = []
    stale: list[tuple[str, str, str]] = []
    stale_cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * args.stale_months)

    for i, (ext_id, (category, slug)) in enumerate(sorted(flat.items())):
        info = _check_slug(session, slug)
        results[ext_id] = {"category": category, "slug": slug, **info}
        if info["status"] != "ok":
            broken.append((ext_id, slug, info["status"]))
            print(f"  [BROKEN] {category}/{slug}: {info['status']}")
        elif info.get("is_disabled"):
            broken.append((ext_id, slug, "is_disabled"))
            print(f"  [DISABLED] {category}/{slug}: AMO marks is_disabled=true")
        else:
            last = info.get("last_updated")
            if last:
                try:
                    last_dt = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if last_dt < stale_cutoff:
                        stale.append((ext_id, slug, last))
                        print(f"  [STALE] {category}/{slug}: last_updated={last}")
                except (TypeError, ValueError):
                    pass
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{len(flat)} checked")
        time.sleep(args.sleep)

    reverse_broken: list[tuple[str, str]] = []
    reverse_results: dict[str, dict] = {}
    if args.include_reverse:
        print()
        reverse_broken, reverse_results = _audit_reverse_map(session, args.sleep)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"forward": results}
        if args.include_reverse:
            payload["reverse"] = reverse_results
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Report written to {args.json}")

    print()
    print(f"Forward summary: {len(flat)} total, {len(broken)} broken/disabled, "
          f"{len(stale)} stale (>{args.stale_months} months)")
    if args.include_reverse:
        print(f"Reverse summary: {len(reverse_results)} total, {len(reverse_broken)} broken/disabled")
    if broken or reverse_broken:
        return 1
    if stale and args.strict_stale:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
