"""FoxPort application entry — sets up Qt, theme, and the main window."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from foxport import __app_name__
from foxport.gui.main_window import MainWindow, install_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    install_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
