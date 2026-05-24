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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path,
                        help="Write per-entry audit report as JSON to this path")
    parser.add_argument("--stale-months", type=int, default=24,
                        help="Flag entries with last_updated older than this many months (default 24)")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Seconds between AMO requests to avoid rate limiting (default 0.5)")
    args = parser.parse_args()

    map_path = data_file("curated_extension_map.json")
    if not map_path.is_file():
        print(f"error: curated map not found at {map_path}", file=sys.stderr)
        return 2
    raw = json.loads(map_path.read_text(encoding="utf-8"))
    flat = _flatten(raw)
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

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Report written to {args.json}")

    print()
    print(f"Summary: {len(flat)} total, {len(broken)} broken/disabled, {len(stale)} stale (>{args.stale_months} months)")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
