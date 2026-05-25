"""FoxPort application entry — sets up Qt, theme, and the main window."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from foxport import __app_name__
from foxport.config import load_settings
from foxport.crash_reporting import initialize_crash_reporting
from foxport.gui.main_window import MainWindow, install_theme


def resolve_app_icon_path() -> Path | None:
    """Return the path to ``assets/icon.ico`` across run layouts.

    Checked in order: PyInstaller's unpacked ``_MEIPASS`` (release
    builds), the repo's ``assets/`` next to the source tree (dev
    runs), and the legacy ``foxport/assets/`` layout in case the
    package ever ships the icon inside the wheel. Returns ``None`` when
    no icon file exists so callers can fall back to the OS default.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "icon.ico")
    package_dir = Path(__file__).resolve().parent
    candidates.append(package_dir.parent / "assets" / "icon.ico")
    candidates.append(package_dir / "assets" / "icon.ico")
    for path in candidates:
        if path.is_file():
            return path
    return None


def main() -> int:
    settings = load_settings()
    initialize_crash_reporting(enabled=settings.crash_reporting_opt_in)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    icon_path = resolve_app_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    install_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
