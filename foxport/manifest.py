"""Per-run ``manifest.json`` writer.

Every non-dry-run migration emits a ``manifest.json`` next to the generated
``README.txt`` and the per-category artifacts. The manifest is the single
machine-readable registry of what shipped: schema version, app version,
direction, the source/target labels the user saw on screen, every artifact's
relative path + SHA-256 + size + count + sensitivity + import action, what
network calls the run *was allowed to* make, and any warnings the worker
surfaced.

It exists so the Done screen, generated README, snapshot bundle, future
``--json`` CLI output, and support diagnostics can all read from one
trustworthy source instead of duplicating per-key knowledge in five places.

**Never** write plaintext passwords, cookie values, card numbers, or any
other decrypted secret into the manifest — only metadata about the files
that contain those values. Use ``sensitivity`` so consumers can warn the
user about cleanup obligations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from foxport import __version__


MANIFEST_FILENAME = "manifest.json"
SCHEMA_VERSION = 1


# Sensitivity label per artifact key. Done UI / generated README / snapshot
# UX can show stronger cleanup copy for "sensitive" and "financial" buckets.
# Keep this in sync with new categories added to the worker.
_SENSITIVITY: dict[str, str] = {
    "passwords": "sensitive",       # plaintext logins.csv
    "hibp": "normal",               # site + username only, no plaintext
    "bookmarks": "normal",
    "extensions": "normal",
    "cookies": "sensitive",         # session-bearing
    "history": "sensitive",         # browsing URLs
    "autofill": "sensitive",        # may include addresses, names
    "cards": "financial",           # plaintext PAN
    "search_engines": "normal",
    "open_tabs": "normal",
    "downloads": "normal",
}

# Default action the Done screen wires for each key. "reveal" opens the
# containing folder (use for *.sqlite files that aren't meant to be
# launched); "open" launches the file with the registered handler.
_DEFAULT_ACTION: dict[str, str] = {
    "passwords": "open",
    "hibp": "open",
    "bookmarks": "open",
    "extensions": "open",
    "cookies": "reveal",
    "history": "reveal",
    "autofill": "reveal",
    "cards": "open",
    "search_engines": "open",
    "open_tabs": "reveal",
    "downloads": "open",
}


@dataclass
class RunArtifact:
    """One emitted file the run produced.

    ``path`` is always relative to the directory containing the manifest;
    callers reconstruct an absolute path by joining with the output dir.
    ``count`` is optional because not every category has a meaningful count
    (e.g. ``search_engines`` ships an inventory plus XML files).
    """

    key: str
    path: str
    size_bytes: int
    sha256: str
    sensitivity: str = "normal"
    action_kind: str = "open"
    count: int | None = None
    direct_write: bool = False
    backup_path: str | None = None
    notes: str | None = None


@dataclass
class RunManifest:
    """Schema-versioned per-migration registry. Consumers should ignore
    unknown keys and require ``schema_version`` to match expectations."""

    schema_version: int = SCHEMA_VERSION
    foxport_version: str = __version__
    created_iso: str = ""
    source_label: str = ""
    target_label: str = ""           # empty string = files-only run
    direction: str = "forward"       # forward | reverse
    dry_run: bool = False
    items_requested: list[str] = field(default_factory=list)
    network: dict[str, str] = field(default_factory=dict)
    artifacts: list[RunArtifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _digest_file(path: Path) -> str:
    """SHA-256 of ``path``, streamed in 64 KiB chunks."""

    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_artifact(
    key: str,
    abs_path: Path,
    out_dir: Path,
    *,
    count: int | None = None,
    direct_write: bool = False,
    backup_path: Path | None = None,
    notes: str | None = None,
) -> RunArtifact:
    """Hash + size an emitted file and wrap it in a :class:`RunArtifact`.

    ``abs_path`` may be the same file or a sibling of ``out_dir`` (think
    ``search-engines/google.xml`` under the run's output folder). It must
    exist; callers that want manifest entries for missing files should
    catch the FileNotFoundError and decide whether the omission is fatal.
    """

    rel = abs_path.relative_to(out_dir).as_posix()
    sensitivity = _SENSITIVITY.get(key, "normal")
    action = _DEFAULT_ACTION.get(key, "open")
    backup_str: str | None
    if backup_path is None:
        backup_str = None
    else:
        # Backups for direct-write live in the *target profile*, not in the
        # output dir. Record an absolute path so consumers can find them.
        backup_str = str(backup_path)
    return RunArtifact(
        key=key,
        path=rel,
        size_bytes=abs_path.stat().st_size,
        sha256=_digest_file(abs_path),
        sensitivity=sensitivity,
        action_kind=action,
        count=count,
        direct_write=direct_write,
        backup_path=backup_str,
        notes=notes,
    )


def write_manifest(manifest: RunManifest, out_dir: Path) -> Path:
    """Write ``out_dir/manifest.json`` and return its path."""

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / MANIFEST_FILENAME
    payload = asdict(manifest)
    # asdict() walks the dataclass tree; RunArtifact dataclasses become
    # nested dicts automatically.
    text = json.dumps(payload, indent=2, sort_keys=False)
    target.write_text(text, encoding="utf-8")
    return target


def load_manifest(path: Path) -> RunManifest:
    """Read a previously written manifest. Tolerates unknown top-level
    keys (forward compatibility) and missing optional fields (older
    schemas)."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    artifacts_raw = raw.pop("artifacts", []) or []
    artifacts = [
        RunArtifact(**{k: v for k, v in entry.items() if k in RunArtifact.__dataclass_fields__})
        for entry in artifacts_raw
    ]
    allowed = set(RunManifest.__dataclass_fields__)
    filtered = {k: v for k, v in raw.items() if k in allowed}
    manifest = RunManifest(**filtered)
    manifest.artifacts = artifacts
    return manifest


def now_iso() -> str:
    """UTC timestamp in the format the manifest uses everywhere."""

    return datetime.now(timezone.utc).isoformat()
