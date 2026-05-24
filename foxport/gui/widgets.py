"""Reusable wizard widgets — step rail, tiles, banners, base page."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class StepRail(QFrame):
    """Vertical left-rail step indicator with active/completed/future states."""

    def __init__(self, step_names: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StepRail")
        self.setFixedWidth(220)
        self._labels: list[QLabel] = []
        self._names: list[str] = list(step_names)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 0, 18)
        layout.setSpacing(2)
        for i, name in enumerate(step_names, start=1):
            label = QLabel("")
            label.setObjectName("StepRailItem")
            self._labels.append(label)
            layout.addWidget(label)
        layout.addStretch(1)
        version_label = QLabel("FoxPort")
        version_label.setStyleSheet("color: #585b70; padding: 8px 14px; font-size: 11px;")
        layout.addWidget(version_label)
        self.set_current(0)

    def set_current(self, index: int) -> None:
        # Rebuild label text from the original name list each time so the
        # checkmark doesn't accumulate (and we don't have to parse our own
        # display string back out).
        for i, label in enumerate(self._labels):
            base = f"  {i + 1}.  {self._names[i]}"
            if i < index:
                label.setProperty("active", False)
                label.setProperty("completed", True)
                label.setText(f"{base}  ✓")
            elif i == index:
                label.setProperty("active", True)
                label.setProperty("completed", False)
                label.setText(base)
            else:
                label.setProperty("active", False)
                label.setProperty("completed", False)
                label.setText(base)
            label.style().unpolish(label)
            label.style().polish(label)


class Banner(QFrame):
    """Slim left-bordered banner. Variant chooses color: 'warn' (amber) or 'info' (blue)."""

    def __init__(self, text: str, variant: str = "warn", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner" if variant == "warn" else "BannerInfo")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("background: transparent; border: none; color: #f9e2af;" if variant == "warn"
                                  else "background: transparent; border: none; color: #cdd6f4;")
        layout.addWidget(self._label, 1)

    def set_text(self, text: str) -> None:
        self._label.setText(text)


class Tile(QFrame):
    """Clickable selector tile with title + subtitle. Optional drag-and-drop support."""

    clicked = pyqtSignal()
    fileDropped = pyqtSignal(str)

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        accept_drops: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setProperty("selected", False)
        self.setProperty("disabled", False)
        self.setProperty("dropTarget", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("TileTitle")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("TileSubtitle")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)

        if accept_drops:
            self.setAcceptDrops(True)

    # -- selection state -------------------------------------------------

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_disabled(self, disabled: bool, tooltip: str = "") -> None:
        self.setProperty("disabled", disabled)
        self.setCursor(Qt.CursorShape.ForbiddenCursor if disabled else Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)

    # -- events ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and not self.property("disabled"):
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self.setProperty("dropTarget", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dropTarget", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("dropTarget", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            self.fileDropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class CountBadge(QLabel):
    """Inline count badge used next to picker labels."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("CountBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class WizardPage(QWidget):
    """Base class for wizard pages — exposes a title + content area."""

    advanceRequested = pyqtSignal()
    backRequested = pyqtSignal()
    canAdvanceChanged = pyqtSignal(bool)

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 14)
        outer.setSpacing(10)
        self._title = QLabel(title)
        self._title.setStyleSheet("color: #f5c2e7; font-size: 20px; font-weight: 700;")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet("color: #a6adc8; font-size: 13px;")
        self._subtitle.setWordWrap(True)
        outer.addWidget(self._title)
        outer.addWidget(self._subtitle)
        self._content = QVBoxLayout()
        self._content.setSpacing(10)
        outer.addLayout(self._content, 1)

    def add_content(self, widget: QWidget, stretch: int = 0) -> None:
        self._content.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self._content.addLayout(layout)

    def add_stretch(self, stretch: int = 1) -> None:
        self._content.addStretch(stretch)

    def can_advance(self) -> bool:
        return True

    def on_enter(self) -> None:
        """Called when the wizard navigates onto this page. Override in subclasses."""

    def on_leave(self) -> None:
        """Called right before the wizard moves off this page."""


class FooterBar(QFrame):
    """Sticky bottom Back / Next bar."""

    backClicked = pyqtSignal()
    nextClicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        from PyQt6.QtWidgets import QPushButton  # local to keep imports tidy
        super().__init__(parent)
        self.setObjectName("FooterBar")
        self.setStyleSheet("QFrame#FooterBar { background: #181825; border-top: 1px solid #313244; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("PrimaryButton")
        self.next_btn.setDefault(True)
        layout.addStretch(1)
        layout.addWidget(self.back_btn)
        layout.addWidget(self.next_btn)
        self.back_btn.clicked.connect(self.backClicked.emit)  # type: ignore[arg-type]
        self.next_btn.clicked.connect(self.nextClicked.emit)  # type: ignore[arg-type]

    def set_next_label(self, label: str) -> None:
        self.next_btn.setText(label)

    def set_can_advance(self, can: bool) -> None:
        self.next_btn.setEnabled(can)

    def set_can_back(self, can: bool) -> None:
        self.back_btn.setEnabled(can)
