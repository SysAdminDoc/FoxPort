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
SURFACE3   = "#202033"
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
BLUE_SOFT  = "#1e2a3a"
GREEN_SOFT = "#20312b"
YELLOW_SOFT = "#3a3022"
RED_SOFT   = "#3a2630"


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
QLabel {{
    background: transparent;
}}
QMainWindow, QDialog {{
    background-color: {BASE};
}}
QMenuBar {{
    background-color: {MANTLE};
    color: {TEXT};
    border-bottom: 1px solid {SURFACE0};
    padding: 2px 8px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {SURFACE0};
}}
QMenu {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 28px 7px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {SURFACE0};
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
QFrame#StepRail {{
    background-color: {MANTLE};
    border: none;
    border-right: 1px solid {SURFACE0};
}}
QFrame#BannerWarn {{
    background-color: {YELLOW_SOFT};
    border: 1px solid #6e5b35;
    border-left: 4px solid {YELLOW};
    border-radius: 6px;
}}
QFrame#BannerInfo {{
    background-color: {BLUE_SOFT};
    border: 1px solid #2c425a;
    border-left: 4px solid {ACCENT2};
    border-radius: 6px;
}}
QFrame#BannerSuccess {{
    background-color: {GREEN_SOFT};
    border: 1px solid #3f6345;
    border-left: 4px solid {GREEN};
    border-radius: 6px;
}}
QFrame#BannerError {{
    background-color: {RED_SOFT};
    border: 1px solid #6a3c4a;
    border-left: 4px solid {RED};
    border-radius: 6px;
}}
QFrame#BannerWarn QLabel {{
    color: {YELLOW};
}}
QFrame#BannerInfo QLabel, QFrame#BannerSuccess QLabel, QFrame#BannerError QLabel {{
    color: {TEXT};
}}
QFrame#Tile {{
    background-color: {MANTLE};
    border: 1px solid {SURFACE0};
    border-radius: 8px;
}}
QFrame#Tile:hover {{
    background-color: {SURFACE3};
    border-color: {SURFACE1};
}}
QFrame#Tile[selected="true"] {{
    border: 2px solid {ACCENT2};
    background-color: {SURFACE0};
}}
QFrame#Tile[disabled="true"] {{
    background-color: {CRUST};
    border: 1px solid {SURFACE0};
}}
QFrame#Tile[dropTarget="true"] {{
    border: 2px dashed #b4befe;
    background-color: {SURFACE0};
}}
QFrame#Tile QLabel {{
    background: transparent;
}}
QFrame#Tile:focus {{
    /* Keyboard-only affordance — visible focus ring so Tab navigation
       isn't invisible. Sits inside the existing border instead of growing
       the box (no layout shift). */
    outline: none;
    border: 2px solid #b4befe;
}}
QFrame#Tile[selected="true"]:focus {{
    border: 2px solid {ACCENT};
}}
QFrame#OptionRow {{
    background-color: {SURFACE3};
    border: 1px solid transparent;
    border-radius: 6px;
}}
QFrame#OptionRow:hover {{
    background-color: {SURFACE3};
    border-color: {SURFACE0};
}}
QFrame#OptionRow[checked="true"] {{
    background-color: #20283a;
    border-color: #31435f;
}}
QFrame#OptionRow[disabled="true"] {{
    color: {OVERLAY0};
    background-color: transparent;
    border-color: transparent;
}}
QFrame#OptionRow[disabled="true"] QLabel {{
    color: {OVERLAY0};
}}
QFrame#OptionRow:focus {{
    border: 1px dashed {ACCENT2};
}}
QCheckBox:focus {{
    outline: 1px dashed {ACCENT2};
    outline-offset: 2px;
}}
QPushButton:focus {{
    outline: 1px dashed {ACCENT2};
    outline-offset: 2px;
}}
QLabel#StepRailItem {{
    color: {OVERLAY0};
    font-size: 13px;
    font-weight: 500;
    padding: 10px 16px 10px 14px;
    border-left: 4px solid transparent;
}}
QLabel#StepRailItem[active="true"] {{
    color: {TEXT};
    font-weight: 700;
    border-left: 4px solid #b4befe;
    background-color: {BASE};
}}
QLabel#StepRailItem[completed="true"] {{
    color: {GREEN};
    font-weight: 500;
    border-left: 4px solid {GREEN};
}}
QLabel#TileTitle {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#TileSubtitle {{
    color: {SUBTEXT0};
    font-size: 12px;
}}
QLabel#OptionTitle {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#OptionSubtitle {{
    color: {SUBTEXT0};
    font-size: 12px;
}}
QLabel#MutedText {{
    color: {SUBTEXT0};
    font-size: 12px;
}}
QLabel#CountBadge {{
    background-color: {SURFACE0};
    color: {SUBTEXT1};
    border: 1px solid {SURFACE1};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#DirectionToggle {{
    background-color: {MANTLE};
    color: {SUBTEXT0};
    border: 1px solid {SURFACE1};
    border-radius: 0;
    padding: 8px 18px;
    min-width: 150px;
}}
QPushButton#DirectionToggle:hover {{
    color: {TEXT};
    background-color: {SURFACE0};
}}
QPushButton#DirectionToggle:checked {{
    background-color: {ACCENT2};
    color: {CRUST};
    border-color: {ACCENT2};
}}
QPushButton#DirectionToggle:focus {{
    border-color: {ACCENT};
}}
QPushButton#QuietButton {{
    background-color: transparent;
    color: {SUBTEXT1};
    border-color: {SURFACE0};
}}
QPushButton#QuietButton:hover {{
    background-color: {SURFACE0};
    color: {TEXT};
    border-color: {SURFACE1};
}}
QTreeWidget {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QTreeWidget::item {{ padding: 4px 6px; }}
QTreeWidget::item:hover {{ background-color: {SURFACE0}; }}
QTreeWidget::item:selected {{ background-color: {SURFACE1}; color: {TEXT}; }}
QTableWidget {{
    background-color: {MANTLE};
    alternate-background-color: {SURFACE3};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    border-radius: 6px;
    gridline-color: {SURFACE0};
    outline: 0;
}}
QTableWidget::item {{
    padding: 5px 7px;
}}
QTableWidget::item:selected {{
    background-color: {SURFACE1};
    color: {TEXT};
}}
QHeaderView::section {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: none;
    border-right: 1px solid {MANTLE};
    padding: 6px 8px;
    font-weight: 600;
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
QComboBox:focus {{ border-color: {ACCENT}; }}
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
QLineEdit, QDateEdit {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {ACCENT2};
    selection-color: {CRUST};
}}
QLineEdit:hover, QDateEdit:hover {{
    border-color: {ACCENT2};
}}
QLineEdit:focus, QDateEdit:focus {{
    border-color: {ACCENT};
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
    image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'><path d='M2.5 6.5 L5 9 L9.5 3' stroke='%2311111b' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
}}
QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 18px;
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
QFrame#FooterBar {{
    background: {MANTLE};
    border-top: 1px solid {SURFACE0};
}}
QFrame#FooterBar QPushButton {{
    min-width: 88px;
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
QLabel#RunStatus {{
    color: {SUBTEXT1};
    font-size: 12px;
    font-weight: 600;
    padding: 0 0 2px 0;
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
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{
    background-color: {SURFACE1};
    color: {TEXT};
    border: 1px solid {SURFACE2};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""
