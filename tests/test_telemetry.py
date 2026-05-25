from __future__ import annotations

import sys
import types

from foxport import telemetry
from foxport.telemetry import MigrationTelemetryPayload, record_migration


def test_record_migration_disabled_does_not_require_glean(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_runtime", None)
    monkeypatch.delitem(sys.modules, "glean", raising=False)

    result = record_migration(
        MigrationTelemetryPayload(
            direction="forward",
            surface="cli",
            outcome="completed",
            dry_run=False,
            direct_write=False,
            items=["passwords"],
            counts={"passwords": 1},
        ),
        enabled=False,
        data_dir=tmp_path,
    )

    assert result.status == "disabled"


def test_record_migration_submits_sanitized_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_runtime", None)

    state = {
        "sets": {},
        "selected_items": [],
        "item_counts": {},
        "submitted": 0,
        "init": None,
        "metrics_paths": None,
        "pings_path": None,
    }

    class FakeMetric:
        def __init__(self, key: str) -> None:
            self.key = key

        def set(self, value) -> None:  # noqa: ANN001 - fake Glean surface
            state["sets"][self.key] = value

    class FakeSelectedItems:
        def set(self, value) -> None:  # noqa: ANN001 - fake Glean surface
            state["selected_items"] = list(value)

    class FakeLabeledQuantity:
        def __getitem__(self, key: str) -> FakeMetric:
            class _Label:
                def set(self, value: int) -> None:
                    state["item_counts"][key] = value

            return _Label()

    class FakeMigration:
        direction = FakeMetric("direction")
        surface = FakeMetric("surface")
        outcome = FakeMetric("outcome")
        dry_run = FakeMetric("dry_run")
        direct_write = FakeMetric("direct_write")
        selected_items = FakeSelectedItems()
        item_counts = FakeLabeledQuantity()

    fake_metrics = types.SimpleNamespace(migration=FakeMigration())

    class FakePings:
        class migration:
            @staticmethod
            def submit() -> None:
                state["submitted"] += 1

    class FakeConfiguration:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.kwargs = kwargs

    class FakeGlean:
        initialized = False

        @classmethod
        def is_initialized(cls) -> bool:
            return cls.initialized

        @classmethod
        def initialize(cls, **kwargs) -> None:  # noqa: ANN003
            cls.initialized = True
            state["init"] = kwargs

    def fake_load_metrics(paths):
        state["metrics_paths"] = [str(path) for path in paths]
        return fake_metrics

    def fake_load_pings(path):
        state["pings_path"] = str(path)
        return FakePings()

    fake_glean = types.SimpleNamespace(
        Configuration=FakeConfiguration,
        Glean=FakeGlean,
        load_metrics=fake_load_metrics,
        load_pings=fake_load_pings,
    )
    monkeypatch.setitem(sys.modules, "glean", fake_glean)

    result = record_migration(
        MigrationTelemetryPayload(
            direction="reverse",
            surface="gui",
            outcome="dry-run",
            dry_run=True,
            direct_write=True,
            items=["passwords", "../profile-path", "history", "history"],
            counts={"passwords": 3, "history": -7, "unknown": 99},
        ),
        enabled=True,
        data_dir=tmp_path,
    )

    assert result.status == "submitted"
    assert state["submitted"] == 1
    assert state["sets"] == {
        "direction": "reverse",
        "surface": "gui",
        "outcome": "dry_run",
        "dry_run": True,
        "direct_write": True,
    }
    assert state["selected_items"] == ["history", "passwords"]
    assert state["item_counts"] == {"passwords": 3, "history": 0}
    assert state["init"]["application_id"] == "foxport"
    assert state["init"]["upload_enabled"] is True
    assert state["init"]["data_dir"] == tmp_path
    assert any(path.endswith("glean_metrics.yaml") for path in state["metrics_paths"])
    assert state["pings_path"].endswith("glean_pings.yaml")
