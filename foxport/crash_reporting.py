"""Opt-in Sentry crash reporting with local path stripping.

Crash reporting stays cold unless the user opts in and a DSN is configured
via ``FOXPORT_SENTRY_DSN`` (preferred) or ``SENTRY_DSN``. The SDK is imported
only in that path.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from foxport import __version__


SENTRY_DSN_ENV = "FOXPORT_SENTRY_DSN"
SENTRY_ENABLE_ENV = "FOXPORT_CRASH_REPORTING"
SENTRY_HOST = "sentry.io"

_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"'<>|]+")
_UNC_PATH_RE = re.compile(r"\\\\[^\s\\/:*?\"<>|]+\\[^\s\\/:*?\"<>|]+(?:\\[^\s\"<>|]+)+")
_POSIX_PATH_RE = re.compile(r"(?<![\w:])/(?:Users|home|tmp|var|private|mnt|Volumes)/[^\s\"'<>]+")

_initialized = False
_last_status = "disabled"
_original_excepthook = None
_original_threading_excepthook = None


@dataclass(frozen=True)
class CrashReportingResult:
    status: str
    message: str = ""


def crash_reporting_env_enabled() -> bool:
    return os.environ.get(SENTRY_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def configured_dsn() -> str:
    return (os.environ.get(SENTRY_DSN_ENV) or os.environ.get("SENTRY_DSN") or "").strip()


def crash_reporting_network_host(dsn: str | None = None) -> str:
    parsed = urlparse((dsn or configured_dsn()).strip())
    return parsed.hostname or SENTRY_HOST


def current_crash_reporting_status(enabled: bool) -> str:
    if not enabled:
        return "disabled"
    if _last_status != "disabled":
        return _last_status
    return "unavailable" if not configured_dsn() else "enabled"


def initialize_crash_reporting(
    *,
    enabled: bool,
    dsn: str | None = None,
) -> CrashReportingResult:
    """Initialize Sentry and install crash hooks when explicitly opted in."""

    global _initialized, _last_status
    if not enabled:
        _last_status = "disabled"
        return CrashReportingResult("disabled")
    actual_dsn = (dsn or configured_dsn()).strip()
    if not actual_dsn:
        _last_status = "unavailable"
        return CrashReportingResult("unavailable", f"{SENTRY_DSN_ENV} is not set")
    if _initialized:
        _last_status = "initialized"
        return CrashReportingResult("initialized")

    try:
        import sentry_sdk
    except ModuleNotFoundError as exc:
        _last_status = "unavailable"
        return CrashReportingResult("unavailable", str(exc))
    except Exception as exc:  # noqa: BLE001 - crash reporting must not break startup
        _last_status = "failed"
        return CrashReportingResult("failed", str(exc))

    try:
        sentry_sdk.init(
            dsn=actual_dsn,
            release=f"foxport@{__version__}",
            environment="production",
            send_default_pii=False,
            include_local_variables=False,
            include_source_context=False,
            attach_stacktrace=True,
            auto_session_tracking=False,
            send_client_reports=False,
            default_integrations=False,
            auto_enabling_integrations=False,
            traces_sample_rate=None,
            server_name="",
            before_send=before_send,
            before_breadcrumb=before_breadcrumb,
        )
        _install_hooks(sentry_sdk)
    except Exception as exc:  # noqa: BLE001 - crash reporting must not break startup
        _last_status = "failed"
        return CrashReportingResult("failed", str(exc))

    _initialized = True
    _last_status = "initialized"
    return CrashReportingResult("initialized")


def before_send(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry ``before_send`` hook that strips paths and risky context."""

    event.pop("user", None)
    event.pop("request", None)
    event.pop("server_name", None)
    event.pop("modules", None)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        contexts.pop("device", None)
    _strip_frame_context(event)
    return _scrub_paths(event)


def before_breadcrumb(
    breadcrumb: dict[str, Any],
    hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _scrub_paths(breadcrumb)


def scrub_paths(value: Any) -> Any:
    """Public testable path scrubber used by the Sentry hooks."""

    return _scrub_paths(value)


def _install_hooks(sentry_sdk: object) -> None:
    global _original_excepthook, _original_threading_excepthook
    if _original_excepthook is None:
        _original_excepthook = sys.excepthook

    def excepthook(exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        try:
            sentry_sdk.capture_exception(exc_value)
            sentry_sdk.flush(timeout=2)
        finally:
            _original_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook

    if _original_threading_excepthook is None:
        _original_threading_excepthook = threading.excepthook

    def threading_hook(args) -> None:  # noqa: ANN001
        try:
            sentry_sdk.capture_exception(args.exc_value)
            sentry_sdk.flush(timeout=2)
        finally:
            _original_threading_excepthook(args)

    threading.excepthook = threading_hook


def _strip_frame_context(event: dict[str, Any]) -> None:
    values = event.get("exception", {}).get("values", [])
    if not isinstance(values, list):
        return
    for value in values:
        frames = value.get("stacktrace", {}).get("frames", []) if isinstance(value, dict) else []
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            for key in ("vars", "pre_context", "post_context", "context_line"):
                frame.pop(key, None)


def _scrub_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_paths(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_paths(v) for v in value)
    if isinstance(value, str):
        return _scrub_path_string(value)
    return value


def _scrub_path_string(value: str) -> str:
    scrubbed = value
    for pattern in (_UNC_PATH_RE, _WINDOWS_PATH_RE, _POSIX_PATH_RE):
        scrubbed = pattern.sub(lambda m: _path_placeholder(m.group(0)), scrubbed)
    for prefix in _known_path_prefixes():
        scrubbed = _replace_prefix(scrubbed, prefix)
    return scrubbed


def _known_path_prefixes() -> list[str]:
    prefixes: list[str] = []
    for path in (Path.home(), Path.cwd(), Path(__file__).resolve().parents[1]):
        text = str(path)
        if text and text not in prefixes:
            prefixes.append(text)
    return prefixes


def _replace_prefix(value: str, prefix: str) -> str:
    variants = {prefix, prefix.replace("\\", "/"), prefix.replace("/", "\\")}
    result = value
    for variant in variants:
        if variant:
            result = result.replace(variant, "<path>")
    return result


def _path_placeholder(path_text: str) -> str:
    normalized = path_text.rstrip("\\/")
    name = re.split(r"[\\/]", normalized)[-1] if normalized else ""
    return f"<path>/{name}" if name else "<path>"
