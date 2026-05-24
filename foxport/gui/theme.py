"""Catppuccin Mocha QSS for FoxPort.

Corner radii are deliberately rectangular (6-8 px) — no stadium/pill shapes
on buttons, badges, or list items. Accents are pink/blue from the standard
Mocha palette.
"""

from __future__ import annotations

from PyQt6.QtGui import QPalette, QColor


# Catppuccin Mocha
BASE       = "#1e1e2e"
MANTLE     = "#181825"
CRUST      = "#11111b"
SURFACE0   = "#313244"
SURFACE1   = "#45475a"
SURFACE2   = "#585b70"
OVERLAY0   = "#6c7086"
OVERLAY1   = "#7f849c"
TEXT       = "#cdd6f4"
SUBTEXT0   = "#a6adc8"
SUBTEXT1   = "#bac2de"
ACCENT     = "#f5c2e7"   # pink
ACCENT2    = "#89b4fa"   # blue
GREEN      = "#a6e3a1"
YELLOW     = "#f9e2af"
RED        = "#f38ba8"


def apply_palette(app) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BASE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(MANTLE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE0))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE0))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT2))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(CRUST))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE1))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(SUBTEXT0))
    app.setPalette(palette)


STYLESHEET = f"""
QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {BASE};
}}
QLabel#TitleLabel {{
    color: {ACCENT};
    font-size: 22px;
    font-weight: 700;
    padding: 0;
}}
QLabel#SubtitleLabel {{
    color: {SUBTEXT0};
    font-size: 13px;
    padding: 0 0 6px 0;
}}
QLabel#SectionLabel {{
    color: {SUBTEXT1};
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 12px 0 4px 0;
}}
QFrame#Card {{
    background-color: {MANTLE};
    border: 1px solid {SURFACE0};
    border-radius: 8px;
}}
QComboBox {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 7px 10px;
    min-width: 220px;
}}
QComboBox:hover {{ border-color: {ACCENT2}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {MANTLE};
    color: {TEXT};
    selection-background-color: {SURFACE1};
    selection-color: {TEXT};
    border: 1px solid {SURFACE0};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QCheckBox {{
    color: {TEXT};
    spacing: 8px;
    padding: 4px 0;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {SURFACE2};
    border-radius: 4px;
    background-color: {SURFACE0};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT2}; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT2};
    border-color: {ACCENT2};
    image: none;
}}
QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: {SURFACE1}; }}
QPushButton:pressed {{ background-color: {SURFACE2}; }}
QPushButton:disabled {{ color: {OVERLAY0}; background-color: {SURFACE0}; }}
QPushButton#PrimaryButton {{
    background-color: {ACCENT2};
    color: {CRUST};
    border-color: {ACCENT2};
}}
QPushButton#PrimaryButton:hover {{ background-color: #a5c5ff; border-color: #a5c5ff; }}
QPushButton#PrimaryButton:pressed {{ background-color: {ACCENT}; border-color: {ACCENT}; }}
QPushButton#PrimaryButton:disabled {{
    background-color: {SURFACE0}; color: {OVERLAY0}; border-color: {SURFACE1};
}}
QPlainTextEdit, QTextEdit {{
    background-color: {CRUST};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    border-radius: 6px;
    padding: 8px;
    font-family: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;
    font-size: 12px;
}}
QProgressBar {{
    background-color: {SURFACE0};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    text-align: center;
    color: {TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT2};
    border-radius: 4px;
}}
QStatusBar {{
    background-color: {MANTLE};
    color: {SUBTEXT0};
    border-top: 1px solid {SURFACE0};
}}
QScrollBar:vertical {{
    background-color: {BASE};
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {SURFACE1};
    border-radius: 4px;
    min-height: 24px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {SURFACE2}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{
    background-color: {SURFACE1};
    color: {TEXT};
    border: 1px solid {SURFACE2};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""
