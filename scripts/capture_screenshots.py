"""Capture DPI-aware screenshots of every wizard page.

Run manually from a real desktop session (the GUI must actually render):

    python scripts/capture_screenshots.py

Saves PNGs to ``assets/screenshots/``. Designed to be re-run after any UI
change — overwrites in place so the README screenshots stay current.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `foxport` importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from foxport.gui.main_window import MainWindow, STEP_NAMES, install_theme


OUT_DIR = Path(__file__).resolve().parents[1] / "assets" / "screenshots"


def _settle(app: QApplication, ms: int = 250) -> None:
    """Pump events for a bit so async detection finishes before snapping."""
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def main() -> int:
    app = QApplication(sys.argv)
    # DPI awareness so the captured PNG matches what the user actually sees.
    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
        app.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    install_theme(app)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    _settle(app, 800)            # wait for browser detection
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for idx, name in enumerate(STEP_NAMES):
        window._show_step(idx)   # noqa: SLF001 — fine in our own utility
        _settle(app, 300)
        pixmap = window.grab()
        out = OUT_DIR / f"{idx + 1}-{name.lower()}.png"
        pixmap.save(str(out), "PNG")
        print(f"saved {out}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
