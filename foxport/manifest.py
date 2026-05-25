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
import os
import sys
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
# ``cards`` is "reveal" deliberately — the CSV contains plaintext PANs
# and default-launching it would hand them to Excel / the OS default
# CSV handler, which can pop import dialogs, embed it in a "recent
# files" list, or cache thumbnails. Forcing the user to open it
# explicitly is the safer default.
_DEFAULT_ACTION: dict[str, str] = {
    "passwords": "open",
    "hibp": "open",
    "bookmarks": "open",
    "extensions": "open",
    "cookies": "reveal",
    "history": "reveal",
    "autofill": "reveal",
    "cards": "reveal",
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

    ``direct_write_policy`` records which conflict-review policy was
    applied to this category when ``direct_write=True``:

    * ``"apply"`` — current v1.3 behavior (merge passwords / replace
      cookies+history+open_tabs after backup).
    * ``"skip"`` — target file was NOT modified; staging-only output.
    * ``"backup-only"`` — target file was copied to a timestamped
      sibling but the new content was NOT written.

    Empty string for categories that didn't go through the direct-write
    path (the field is additive on the v1.3.0 schema; readers are
    expected to default-to-apply when missing).
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
    direct_write_policy: str = ""


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
    direct_write_policy: str = "",
) -> RunArtifact:
    """Hash + size an emitted file and wrap it in a :class:`RunArtifact`.

    ``abs_path`` may be the same file or a sibling of ``out_dir`` (think
    ``search-engines/google.xml`` under the run's output folder). It must
    exist; callers that want manifest entries for missing files should
    catch the FileNotFoundError and decide whether the omission is fatal.

    ``direct_write_policy`` is the per-category policy chosen via the
    conflict-review dialog / CLI flag ("apply", "skip", or
    "backup-only"). Empty for categories that didn't go through the
    direct-write path; consumers should treat empty as ``"apply"`` for
    backward compatibility with v1.3.0–v1.3.2 manifests.
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
        direct_write_policy=direct_write_policy,
    )


_REDACTED = "<redacted>"


def _user_home_prefixes() -> list[str]:
    """Return a list of canonical strings that should be redacted from
    absolute paths when ``privacy_redact=True`` is requested.

    The list is built dynamically from the running user's home dir + a
    handful of per-platform conventions so a manifest uploaded for
    support doesn't leak the username inside ``backup_path`` strings.

    Lists are emitted longest-first so ``C:\\Users\\Alice\\AppData``
    matches before ``C:\\Users``.
    """

    candidates: set[str] = set()
    try:
        home = str(Path.home())
    except (RuntimeError, OSError):
        home = ""
    if home:
        candidates.add(home)
    # Per-platform canonical "user dir parent" — even if Path.home() points
    # somewhere unusual, these are the conventional roots we want to
    # collapse for privacy.
    if sys.platform == "win32":
        users_root = os.environ.get("SystemDrive", "C:") + "\\Users\\"
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            candidates.add(userprofile)
        # Add the entire \Users\<name> prefix for any path that happens
        # to start with the Windows convention even when USERPROFILE
        # disagrees (e.g. a service account migrating someone else's
        # profile).
        candidates.add(users_root)
    elif sys.platform == "darwin":
        candidates.add("/Users/")
    else:
        candidates.add("/home/")
    return sorted((c for c in candidates if c), key=len, reverse=True)


def _redact_path(value: str, prefixes: list[str]) -> str:
    """Return ``value`` with the longest matching prefix swapped for
    ``<redacted>``. Preserves the path beyond the username component.

    ``C:\\Users\\Alice\\AppData\\Roaming\\Mozilla\\...`` becomes
    ``<redacted>\\AppData\\Roaming\\Mozilla\\...``.
    """

    if not value:
        return value
    for prefix in prefixes:
        if value.startswith(prefix):
            # Strip the prefix, then strip ONE more path component
            # (the username) so the remainder begins after the user dir.
            tail = value[len(prefix):]
            # Find the next separator (Windows or POSIX) so we drop the
            # username segment that lives under \Users\ or /home/.
            for sep in ("\\", "/"):
                idx = tail.find(sep)
                if idx >= 0:
                    return _REDACTED + tail[idx:]
            # No further separator — the whole thing was the user dir.
            return _REDACTED
    return value


def redact_manifest(manifest: RunManifest) -> RunManifest:
    """Return a copy of ``manifest`` with backup_path / source_label /
    target_label scrubbed of the current user's home-dir prefix.

    Used by ``--privacy-redact`` so a manifest uploaded for support
    doesn't leak ``C:\\Users\\<username>`` (or its mac / Linux
    equivalents). The on-disk migration data is untouched — only the
    in-memory ``RunManifest`` that ``write_manifest`` then serializes.
    """

    prefixes = _user_home_prefixes()
    redacted_artifacts: list[RunArtifact] = []
    for art in manifest.artifacts:
        redacted_artifacts.append(RunArtifact(
            key=art.key,
            path=art.path,                       # always relative; never absolute
            size_bytes=art.size_bytes,
            sha256=art.sha256,
            sensitivity=art.sensitivity,
            action_kind=art.action_kind,
            count=art.count,
            direct_write=art.direct_write,
            backup_path=(_redact_path(art.backup_path, prefixes)
                         if art.backup_path else None),
            notes=art.notes,
            direct_write_policy=art.direct_write_policy,
        ))
    return RunManifest(
        schema_version=manifest.schema_version,
        foxport_version=manifest.foxport_version,
        created_iso=manifest.created_iso,
        # Profile labels are human-friendly strings like "Brave — Default";
        # they don't contain usernames today, but the redactor is a no-op
        # on them so it's still safe to apply.
        source_label=_redact_path(manifest.source_label, prefixes),
        target_label=_redact_path(manifest.target_label, prefixes),
        direction=manifest.direction,
        dry_run=manifest.dry_run,
        items_requested=list(manifest.items_requested),
        network=dict(manifest.network),
        artifacts=redacted_artifacts,
        warnings=list(manifest.warnings),
    )


def write_manifest(
    manifest: RunManifest,
    out_dir: Path,
    *,
    privacy_redact: bool = False,
) -> Path:
    """Write ``out_dir/manifest.json`` and return its path.

    When ``privacy_redact=True``, runs the in-memory manifest through
    :func:`redact_manifest` before serialization so ``backup_path``
    strings don't carry the current user's home-dir prefix. Default is
    ``False`` — the user-private manifest still keeps absolute paths
    so they can actually find their backups when something goes wrong.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / MANIFEST_FILENAME
    payload = asdict(redact_manifest(manifest) if privacy_redact else manifest)
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
