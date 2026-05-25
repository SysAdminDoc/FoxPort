from __future__ import annotations

import sys
import threading
import types

from foxport import crash_reporting
from foxport.crash_reporting import (
    before_send,
    current_crash_reporting_status,
    initialize_crash_reporting,
    scrub_paths,
)


def test_initialize_disabled_does_not_import_sentry(monkeypatch):
    monkeypatch.setattr(crash_reporting, "_initialized", False)
    monkeypatch.setattr(crash_reporting, "_last_status", "disabled")
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)

    result = initialize_crash_reporting(enabled=False, dsn="https://example@sentry.io/1")

    assert result.status == "disabled"


def test_initialize_requires_dsn(monkeypatch):
    monkeypatch.setattr(crash_reporting, "_initialized", False)
    monkeypatch.setattr(crash_reporting, "_last_status", "disabled")
    monkeypatch.delenv("FOXPORT_SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    result = initialize_crash_reporting(enabled=True)

    assert result.status == "unavailable"
    assert "FOXPORT_SENTRY_DSN" in result.message
    assert current_crash_reporting_status(True) == "unavailable"


def test_cli_global_crash_reporting_flag_parses():
    from foxport.cli import build_parser

    args = build_parser().parse_args(["--crash-reporting", "list"])

    assert args.crash_reporting is True
    assert args.command == "list"


def test_initialize_configures_sentry_with_privacy_options(monkeypatch):
    monkeypatch.setattr(crash_reporting, "_initialized", False)
    monkeypatch.setattr(crash_reporting, "_last_status", "disabled")
    monkeypatch.setattr(crash_reporting, "_original_excepthook", None)
    monkeypatch.setattr(crash_reporting, "_original_threading_excepthook", None)
    original_excepthook = sys.excepthook
    original_threading_hook = threading.excepthook
    state = {"init": None, "captured": 0, "flushed": 0}

    def fake_init(**kwargs):
        state["init"] = kwargs

    fake_sentry = types.SimpleNamespace(
        init=fake_init,
        capture_exception=lambda _exc: state.__setitem__("captured", state["captured"] + 1),
        flush=lambda timeout=0: state.__setitem__("flushed", state["flushed"] + 1),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)

    try:
        result = initialize_crash_reporting(
            enabled=True,
            dsn="https://public@example.ingest.sentry.io/123",
        )
    finally:
        sys.excepthook = original_excepthook
        threading.excepthook = original_threading_hook
        crash_reporting._initialized = False
        crash_reporting._last_status = "disabled"
        crash_reporting._original_excepthook = None
        crash_reporting._original_threading_excepthook = None

    assert result.status == "initialized"
    assert state["init"]["send_default_pii"] is False
    assert state["init"]["include_local_variables"] is False
    assert state["init"]["include_source_context"] is False
    assert state["init"]["default_integrations"] is False
    assert state["init"]["auto_enabling_integrations"] is False
    assert state["init"]["before_send"] is before_send


def test_scrub_paths_removes_absolute_paths_and_usernames():
    payload = {
        "win": r"C:\Users\Alice\AppData\Local\FoxPort\profile.sqlite:20",
        "unc": r"\\vmware-host\Shared Folders\repos\FoxPort\foxport\app.py",
        "posix": "/Users/alice/Library/Application Support/FoxPort/config.json",
    }

    scrubbed = scrub_paths(payload)
    blob = repr(scrubbed)

    assert "Alice" not in blob
    assert "alice" not in blob
    assert "vmware-host" not in blob
    assert "Shared Folders" not in blob
    assert "C:\\Users" not in blob
    assert "/Users/" not in blob
    assert "<path>" in blob


def test_before_send_drops_sensitive_context_and_scrubs_frames():
    event = {
        "user": {"username": "Alice"},
        "request": {"url": "file:///C:/Users/Alice/profile"},
        "server_name": "workstation",
        "modules": {"foxport": "1.0"},
        "contexts": {"device": {"name": "workstation"}, "os": {"name": "Windows"}},
        "exception": {
            "values": [{
                "stacktrace": {
                    "frames": [{
                        "filename": r"C:\Users\Alice\repo\foxport\cli.py",
                        "abs_path": r"C:\Users\Alice\repo\foxport\cli.py",
                        "vars": {"secret": "value"},
                        "pre_context": ["password = 'x'"],
                        "context_line": "raise boom",
                        "post_context": ["cleanup()"],
                    }]
                }
            }]
        },
    }

    scrubbed = before_send(event)
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]

    assert "user" not in scrubbed
    assert "request" not in scrubbed
    assert "server_name" not in scrubbed
    assert "modules" not in scrubbed
    assert "device" not in scrubbed["contexts"]
    assert "vars" not in frame
    assert "pre_context" not in frame
    assert "context_line" not in frame
    assert "post_context" not in frame
    assert "Alice" not in repr(scrubbed)
    assert frame["filename"].startswith("<path>")
