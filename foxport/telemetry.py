"""Opt-in Glean telemetry for aggregate migration health.

This module is intentionally cold unless the user opted in. Importing it
does not import the Glean SDK, initialize network-capable code, or touch
disk. Callers pass ``enabled=False`` for the default no-telemetry path and
receive a no-op result.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from foxport import __version__
from foxport.config import config_dir


APPLICATION_ID = "foxport"
TELEMETRY_HOST = "incoming.telemetry.mozilla.org"
TELEMETRY_ENDPOINT = f"https://{TELEMETRY_HOST}"

_METRICS_FILE = "glean_metrics.yaml"
_PINGS_FILE = "glean_pings.yaml"

_ITEM_LABELS = {
    "passwords",
    "bookmarks",
    "extensions",
    "extension_settings",
    "cookies",
    "history",
    "autofill",
    "cards",
    "search_engines",
    "open_tabs",
    "downloads",
    "hibp",
}
_DIRECTIONS = {"forward", "reverse"}
_SURFACES = {"cli", "gui"}
_OUTCOMES = {"completed", "dry_run", "failed"}


@dataclass(frozen=True)
class MigrationTelemetryPayload:
    """Privacy-bounded telemetry payload for one migration attempt.

    The payload deliberately contains only enum values, booleans, selected
    item slugs, and aggregate counts. It must never carry filesystem paths,
    browser profile labels, URLs, usernames, hostnames, or secrets.
    """

    direction: str
    surface: str
    outcome: str
    dry_run: bool
    direct_write: bool
    items: list[str]
    counts: Mapping[str, int]


@dataclass(frozen=True)
class TelemetryResult:
    status: str
    message: str = ""

    @property
    def enabled(self) -> bool:
        return self.status not in {"disabled", "unavailable"}


@dataclass
class _Runtime:
    glean: object
    metrics: object
    pings: object


_runtime: _Runtime | None = None


def telemetry_data_dir() -> Path:
    return config_dir() / "glean"


def record_migration(
    payload: MigrationTelemetryPayload,
    *,
    enabled: bool,
    data_dir: Path | None = None,
) -> TelemetryResult:
    """Record and submit the aggregate ``migration`` ping when opted in.

    Any SDK import/initialization/recording failure is reported to the caller
    but never raised. Migration correctness cannot depend on telemetry.
    """

    if not enabled:
        return TelemetryResult("disabled")
    try:
        runtime = _ensure_runtime(data_dir=data_dir)
    except ModuleNotFoundError as exc:
        return TelemetryResult("unavailable", str(exc))
    except Exception as exc:  # noqa: BLE001 - telemetry must not stop a run
        return TelemetryResult("failed", str(exc))

    try:
        metrics = runtime.metrics.migration
        metrics.direction.set(_enum(payload.direction, _DIRECTIONS, "forward"))
        metrics.surface.set(_enum(payload.surface, _SURFACES, "cli"))
        metrics.outcome.set(_enum(payload.outcome, _OUTCOMES, "failed"))
        metrics.dry_run.set(bool(payload.dry_run))
        metrics.direct_write.set(bool(payload.direct_write))
        metrics.selected_items.set(_selected_items(payload.items))
        for key, value in _item_counts(payload.counts).items():
            metrics.item_counts[key].set(value)
        runtime.pings.migration.submit()
    except Exception as exc:  # noqa: BLE001 - telemetry must not stop a run
        return TelemetryResult("failed", str(exc))
    return TelemetryResult("submitted")


def _ensure_runtime(*, data_dir: Path | None = None) -> _Runtime:
    global _runtime
    if _runtime is not None:
        return _runtime

    from glean import Configuration, Glean, load_metrics, load_pings

    data_path = data_dir or telemetry_data_dir()
    data_path.mkdir(parents=True, exist_ok=True)
    config = Configuration(
        channel="release",
        server_endpoint=TELEMETRY_ENDPOINT,
        allow_multiprocessing=False,
    )
    if not Glean.is_initialized():
        Glean.initialize(
            application_id=APPLICATION_ID,
            application_version=__version__,
            upload_enabled=True,
            configuration=config,
            data_dir=data_path,
            application_build_id=__version__,
        )

    metrics_path, pings_path = _registry_paths()
    metrics = load_metrics([metrics_path, pings_path])
    pings = load_pings(pings_path)
    _runtime = _Runtime(glean=Glean, metrics=metrics, pings=pings)
    return _runtime


def _registry_paths() -> tuple[Path, Path]:
    data_dir = Path(__file__).with_name("data")
    return data_dir / _METRICS_FILE, data_dir / _PINGS_FILE


def _enum(value: str, allowed: set[str], fallback: str) -> str:
    value = (value or "").strip().lower().replace("-", "_")
    return value if value in allowed else fallback


def _selected_items(items: list[str]) -> list[str]:
    return sorted({
        item.strip().lower()
        for item in items
        if item.strip().lower() in _ITEM_LABELS
    })


def _item_counts(counts: Mapping[str, int]) -> dict[str, int]:
    clean: dict[str, int] = {}
    for key, value in counts.items():
        label = key.strip().lower()
        if label not in _ITEM_LABELS:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        clean[label] = max(0, number)
    return clean
