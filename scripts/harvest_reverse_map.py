"""Harvest AMO GUID → Chrome ID pairs by querying every curated AMO slug.

For each ``(chrome_id, slug)`` in ``foxport/data/curated_extension_map.json``,
fetch ``https://addons.mozilla.org/api/v5/addons/addon/<slug>/`` and pull the
extension's GUID. Emit a Python dict literal that's a drop-in for
``foxport/migrate_reverse/extensions.py:AMO_GUID_TO_CHROME``.

Usage::

    python scripts/harvest_reverse_map.py                # print to stdout
    python scripts/harvest_reverse_map.py --write        # rewrite the module

Skips entries whose AMO listing is 404/disabled. Designed for monthly
runs alongside ``check_curated_map.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from foxport.data import data_file
from foxport.migrate.extensions import load_curated_map


_AMO_DETAIL = "https://addons.mozilla.org/api/v5/addons/addon"
_USER_AGENT = "FoxPort-ReverseHarvester/1.0 (+https://github.com/SysAdminDoc/FoxPort)"
_MODULE_PATH = ROOT / "foxport" / "migrate_reverse" / "extensions.py"


def _fetch_guid(session: requests.Session, slug: str) -> tuple[str | None, str | None]:
    """Return (guid, name) for the AMO slug, or (None, None) if the slug is
    broken / disabled / 404."""
    try:
        resp = session.get(f"{_AMO_DETAIL}/{slug}/", timeout=10)
    except requests.RequestException:
        return None, None
    if resp.status_code != 200:
        return None, None
    try:
        data = resp.json()
    except ValueError:
        return None, None
    if data.get("status") != "public" or data.get("is_disabled"):
        return None, None
    guid = data.get("guid")
    name_field = data.get("name")
    name = name_field.get("en-US") if isinstance(name_field, dict) else name_field
    return guid, name


def harvest(*, sleep: float = 0.5) -> dict[str, tuple[str, str]]:
    """Walk the curated forward map and return ``{guid: (chrome_id, name)}``."""
    curated = load_curated_map()
    print(f"Harvesting GUIDs for {len(curated)} curated entries...")
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"})

    out: dict[str, tuple[str, str]] = {}
    # We iterate by slug (deduping) so each AMO call only happens once.
    by_slug: dict[str, str] = {}
    for chrome_id, slug in curated.items():
        # First Chrome ID for each slug wins. The forward map has multiple
        # variants pointing to the same slug (uBO, Stylus); the reverse
        # only needs one.
        by_slug.setdefault(slug, chrome_id)

    for i, (slug, chrome_id) in enumerate(sorted(by_slug.items())):
        guid, name = _fetch_guid(session, slug)
        if guid:
            out[guid] = (chrome_id, name or slug)
            print(f"  [ok] {slug:36s} -> {guid}")
        else:
            print(f"  [skip] {slug}")
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{len(by_slug)}")
        time.sleep(sleep)
    return out


def render_module(harvest: dict[str, tuple[str, str]]) -> str:
    """Render the AMO_GUID_TO_CHROME dict literal for paste-in."""
    lines = ["AMO_GUID_TO_CHROME: dict[str, str] = {"]
    for guid in sorted(harvest):
        chrome_id, name = harvest[guid]
        # Be defensive about quote chars in GUIDs (some are {uuid} literals).
        lines.append(f'    {json.dumps(guid)}: {json.dumps(chrome_id)},  # {name}')
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="Rewrite AMO_GUID_TO_CHROME in foxport/migrate_reverse/extensions.py")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Seconds between AMO requests (default 0.5)")
    args = parser.parse_args()

    harvested = harvest(sleep=args.sleep)
    rendered = render_module(harvested)
    print()
    print(f"Harvested {len(harvested)} AMO GUIDs.")
    print()
    print(rendered)

    if args.write:
        module = _MODULE_PATH.read_text(encoding="utf-8")
        start = module.find("AMO_GUID_TO_CHROME: dict[str, str] = {")
        if start < 0:
            print("error: AMO_GUID_TO_CHROME assignment not found in module", file=sys.stderr)
            return 1
        end = module.index("}", start) + 1
        new_module = module[:start] + rendered + module[end:]
        _MODULE_PATH.write_text(new_module, encoding="utf-8")
        print(f"Rewrote {_MODULE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
