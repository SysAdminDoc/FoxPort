"""Allowlisted extension settings export.

FoxPort does not attempt to clone arbitrary WebExtension state. Browser
extension storage can include auth tokens, encrypted vault blobs, cached
remote data, and implementation-private keys that are unsafe to copy across
extension IDs. This module is deliberately narrow: it recognizes a few stable
settings surfaces for high-value extensions and writes only those fields into
an auditable JSON artifact.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from foxport.browsers.chromium import ExtensionInfo, read_extensions
from foxport.browsers.detect import ChromiumProfile
from foxport.fileops import write_text_atomic


@dataclass(frozen=True)
class ExtensionSettingsSpec:
    key: str
    label: str
    extension_ids: tuple[str, ...]
    storage_dirs: tuple[str, ...]
    notes: str


@dataclass
class ExtensionSettingsExport:
    key: str
    label: str
    extension_id: str
    extension_name: str
    data: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtensionSettingsResult:
    json_path: Path
    exported: list[ExtensionSettingsExport] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.exported)


# Chrome IDs already present in curated_extension_map.json. Multiple IDs map
# to the same AMO add-on for forks / old-channel packages.
SUPPORTED_EXTENSION_SETTINGS: dict[str, ExtensionSettingsSpec] = {
    "ublock": ExtensionSettingsSpec(
        key="ublock",
        label="uBlock Origin",
        extension_ids=(
            "cjpalhdlnbpafiamejdnhcphjbkeiagm",
            "ddkjiahejlhfcafbddmgiahcphecmpfh",
            "fdoeckjeapimfjeoddjlpdkogdfnighb",
        ),
        storage_dirs=("Local Extension Settings/{id}",),
        notes="Selected filter lists, user filters, trusted sites, and dynamic rules.",
    ),
    "stylus": ExtensionSettingsSpec(
        key="stylus",
        label="Stylus",
        extension_ids=(
            "clngdbkpkpeebahjckkjfobafhncgmne",
            "ikenrfhkjjdpjnpldmonkadbnkgmgcco",
        ),
        storage_dirs=(
            "IndexedDB/chrome-extension_{id}_0.indexeddb.leveldb",
            "Local Extension Settings/{id}",
        ),
        notes="User styles recovered from Stylus' IndexedDB JSON records where possible.",
    ),
    "bitwarden": ExtensionSettingsSpec(
        key="bitwarden",
        label="Bitwarden",
        extension_ids=("nngceckbapebfimnlniiiahkandclblb",),
        storage_dirs=("Local Extension Settings/{id}",),
        notes="Self-hosted server / environment URL settings only; no vault data.",
    ),
}

_UBLOCK_KEYS = (
    "selectedFilterLists",
    "externalLists",
    "userFilters",
    "netWhitelist",
    "dynamicFilteringString",
    "urlFilteringString",
    "hostnameSwitchesString",
    "userSettings",
    "hiddenSettingsString",
)

_BITWARDEN_URL_KEYS = (
    "base",
    "baseUrl",
    "baseEnvironmentUrl",
    "webVault",
    "webVaultUrl",
    "api",
    "apiUrl",
    "identity",
    "identityUrl",
    "icons",
    "iconsUrl",
    "notifications",
    "notificationsUrl",
    "events",
    "eventsUrl",
)

_MAX_STORAGE_BYTES = 20 * 1024 * 1024
_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)


def parse_extension_settings_selection(value: str | None) -> set[str]:
    """Parse CLI/UI selection text into supported settings keys."""

    if not value:
        return set()
    selected: set[str] = set()
    for token in value.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "all":
            selected.update(SUPPORTED_EXTENSION_SETTINGS)
            continue
        if token not in SUPPORTED_EXTENSION_SETTINGS:
            allowed = ", ".join(sorted(SUPPORTED_EXTENSION_SETTINGS))
            raise ValueError(f"unknown extension settings key '{token}'; pick from {allowed},all")
        selected.add(token)
    return selected


def installed_supported_settings(
    extensions: Iterable[ExtensionInfo],
) -> dict[str, ExtensionInfo]:
    """Return allowlisted settings keys that are installed in the source."""

    by_id = {ext.extension_id: ext for ext in extensions}
    installed: dict[str, ExtensionInfo] = {}
    for key, spec in SUPPORTED_EXTENSION_SETTINGS.items():
        for ext_id in spec.extension_ids:
            if ext_id in by_id:
                installed[key] = by_id[ext_id]
                break
    return installed


def migrate_extension_settings(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    selected: set[str],
    dry_run: bool = False,
) -> ExtensionSettingsResult:
    """Export selected allowlisted extension settings to JSON."""

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "extension-settings.json"
    result = ExtensionSettingsResult(json_path=json_path)
    if not selected:
        return result

    extensions = read_extensions(profile)
    installed = installed_supported_settings(extensions)
    for key in sorted(selected):
        spec = SUPPORTED_EXTENSION_SETTINGS.get(key)
        if spec is None:
            result.failures.append(f"unsupported extension settings key: {key}")
            continue
        ext = installed.get(key)
        if ext is None:
            result.skipped.append(f"{spec.label}: extension not installed in source profile")
            continue
        try:
            export = _export_one(profile, spec, ext)
        except Exception as exc:  # noqa: BLE001 - non-fatal per extension
            result.failures.append(f"{spec.label}: {exc}")
            continue
        if export is None:
            result.skipped.append(f"{spec.label}: no supported settings found")
        else:
            result.exported.append(export)

    if not dry_run and (result.exported or result.skipped or result.failures):
        payload = {
            "schema_version": 1,
            "supported_keys": sorted(SUPPORTED_EXTENSION_SETTINGS),
            "exported": [
                {
                    "key": item.key,
                    "label": item.label,
                    "extension_id": item.extension_id,
                    "extension_name": item.extension_name,
                    "data": item.data,
                    "warnings": item.warnings,
                }
                for item in result.exported
            ],
            "skipped": list(result.skipped),
            "failures": list(result.failures),
        }
        write_text_atomic(json_path, json.dumps(payload, indent=2, sort_keys=True))
    return result


def _export_one(
    profile: ChromiumProfile,
    spec: ExtensionSettingsSpec,
    ext: ExtensionInfo,
) -> ExtensionSettingsExport | None:
    blobs = _read_storage_blobs(profile, spec, ext.extension_id)
    if not blobs:
        return None
    values = _collect_values(blobs)
    data: dict
    warnings: list[str] = []
    if spec.key == "ublock":
        data = _extract_ublock(values)
    elif spec.key == "stylus":
        data = _extract_stylus(values)
        if data.get("styles"):
            warnings.append(
                "Import through Stylus' manager JSON import; raw browser storage is not copied."
            )
    elif spec.key == "bitwarden":
        data = _extract_bitwarden(values)
        if data:
            warnings.append("Only server URL settings are exported; vault contents are intentionally omitted.")
    else:
        data = {}
    if not data:
        return None
    return ExtensionSettingsExport(
        key=spec.key,
        label=spec.label,
        extension_id=ext.extension_id,
        extension_name=ext.name,
        data=data,
        warnings=warnings,
    )


def _read_storage_blobs(
    profile: ChromiumProfile,
    spec: ExtensionSettingsSpec,
    extension_id: str,
) -> list[str]:
    blobs: list[str] = []
    for template in spec.storage_dirs:
        root = profile.profile_dir / template.format(id=extension_id)
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            try:
                if path.stat().st_size > _MAX_STORAGE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            text = data.decode("utf-8", errors="ignore")
            if text.strip():
                blobs.append(text)
    return blobs


def _collect_values(blobs: Iterable[str]) -> dict[str, object]:
    """Best-effort extraction from JSON-ish extension storage files.

    Chrome's on-disk extension storage is LevelDB, not a stable JSON file.
    Values and keys are still often visible as UTF-8 fragments in .log/.ldb
    files. This collector handles explicit JSON exports, object fragments,
    and key/value fragments without ever returning raw, unallowlisted blobs.
    """

    values: dict[str, object] = {}
    for text in blobs:
        for obj in _iter_json_values(text):
            _collect_from_json(obj, values)
        for key in _UBLOCK_KEYS + _BITWARDEN_URL_KEYS + ("environmentUrls", "styles"):
            if key not in values:
                found = _find_value_after_key(text, key)
                if found is not None:
                    values[key] = found
    return values


def _iter_json_values(text: str):
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(text[idx:])
        except ValueError:
            continue
        yield value


def _collect_from_json(value: object, out: dict[str, object]) -> None:
    if isinstance(value, dict):
        # Chrome-storage exports may be either {"key": value} or
        # {"key": "selectedFilterLists", "value": [...]}. Support both.
        key = value.get("key")
        if isinstance(key, str) and "value" in value:
            out.setdefault(key, value["value"])
        for k, v in value.items():
            if isinstance(k, str):
                out.setdefault(k, v)
            _collect_from_json(v, out)
    elif isinstance(value, list):
        for item in value:
            _collect_from_json(item, out)


def _find_value_after_key(text: str, key: str) -> object | None:
    decoder = json.JSONDecoder()
    start = 0
    while True:
        idx = text.find(key, start)
        if idx < 0:
            return None
        window = text[idx + len(key): idx + len(key) + 8192]
        for offset, ch in enumerate(window):
            if ch not in "{[\"-0123456789tfn":
                continue
            try:
                value, _end = decoder.raw_decode(window[offset:])
            except ValueError:
                continue
            return value
        start = idx + len(key)


def _extract_ublock(values: dict[str, object]) -> dict:
    data: dict[str, object] = {}
    for key in _UBLOCK_KEYS:
        if key in values:
            data[key] = values[key]
    return data


def _extract_stylus(values: dict[str, object]) -> dict:
    styles = []
    if isinstance(values.get("styles"), list):
        styles.extend(
            _normalize_stylus_style(s)
            for s in values["styles"]
            if isinstance(s, dict) and _looks_like_stylus_style(s)
        )
    for value in values.values():
        if isinstance(value, dict) and _looks_like_stylus_style(value):
            styles.append(_normalize_stylus_style(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _looks_like_stylus_style(item):
                    styles.append(_normalize_stylus_style(item))
    deduped: list[dict] = []
    seen: set[str] = set()
    for style in styles:
        marker = json.dumps(style, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            deduped.append(style)
    return {"styles": deduped, "count": len(deduped)} if deduped else {}


def _looks_like_stylus_style(value: dict) -> bool:
    return "sections" in value and ("name" in value or "customName" in value)


def _normalize_stylus_style(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    keep = {
        "id",
        "name",
        "customName",
        "enabled",
        "sections",
        "updateUrl",
        "url",
        "md5Url",
        "originalMd5",
        "usercssData",
    }
    return {k: v for k, v in value.items() if k in keep}


def _extract_bitwarden(values: dict[str, object]) -> dict:
    urls: dict[str, str] = {}
    env = values.get("environmentUrls")
    if isinstance(env, dict):
        for key, value in env.items():
            if isinstance(key, str) and isinstance(value, str) and _is_url(value):
                urls[key] = value
    for key in _BITWARDEN_URL_KEYS:
        value = values.get(key)
        if isinstance(value, str) and _is_url(value):
            urls[key] = value
    # Last-resort recovery for LevelDB fragments where the key is visible but
    # not parseable as a JSON object. Keep only URL-looking strings.
    for value in values.values():
        if isinstance(value, str):
            for url in _URL_RE.findall(value):
                urls.setdefault("detected", url.rstrip(".,;"))
    return {"environment_urls": urls} if urls else {}


def _is_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))
