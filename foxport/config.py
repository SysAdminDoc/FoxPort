"""Persistent FoxPort settings.

Settings live in a single JSON file under the platform's config dir:

* Windows: ``%APPDATA%\\FoxPort\\config.json``
* macOS:   ``~/Library/Application Support/FoxPort/config.json``
* Linux:   ``$XDG_CONFIG_HOME/FoxPort/config.json`` (or ``~/.config/FoxPort/...``)

The Settings dialog reads/writes this file. CLI flags always win — config
values are defaults, not enforcement.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Settings:
    """User-facing FoxPort settings.

    ``output_dir`` is stored as a string so it survives JSON round-tripping.
    """

    output_dir: str = ""                     # empty = ~/Documents/FoxPort
    mask_passwords_in_preview: bool = True
    allow_online_amo_lookup: bool = True
    default_dry_run: bool = False
    hibp_scan_default: bool = False
    telemetry_opt_in: bool = False           # for the v1.3 Glean wiring
    crash_reporting_opt_in: bool = False     # for the v1.3 Sentry wiring


def config_dir() -> Path:
    """Per-platform FoxPort settings directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "FoxPort"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FoxPort"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "FoxPort"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_settings() -> Settings:
    """Read settings from disk. Missing fields/file fall back to defaults."""
    path = config_path()
    if not path.is_file():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    valid_keys = {f.name for f in fields(Settings)}
    kwargs = {k: v for k, v in data.items() if k in valid_keys}
    try:
        return Settings(**kwargs)
    except TypeError:
        return Settings()


def save_settings(settings: Settings) -> Path:
    """Write settings to disk, creating the parent dir if needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
