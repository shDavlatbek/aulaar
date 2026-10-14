"""Common page scaffolding."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ..manager import DeviceManager, DeviceState
from ..protocol import evision


class Page(QScrollArea):
    title = ""
    subtitle = ""

    def __init__(self, manager: DeviceManager):
        super().__init__()
        self.manager = manager
        self.state: DeviceState | None = None
        self.draft: evision.Settings | None = None  # device settings with pending edits on top
        self.on_edit: Callable[[Callable[[evision.Settings], None]], None] | None = None
        self._loading = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="PageBody")
        self.layout_ = QVBoxLayout(body)
        self.layout_.setContentsMargins(32, 28, 32, 32)
        self.layout_.setSpacing(18)
        self.layout_.addWidget(QLabel(self.title, objectName="PageTitle"))
        if self.subtitle:
            self.layout_.addWidget(QLabel(self.subtitle, objectName="PageSubtitle", wordWrap=True))
        self.setWidget(body)
        self.build()
        self.layout_.addStretch(1)

    def add(self, widget: QWidget) -> QWidget:
        self.layout_.addWidget(widget)
        return widget

    def build(self) -> None:
        raise NotImplementedError

    def set_state(self, state: DeviceState, draft: evision.Settings | None) -> None:
        self.state = state
        self.draft = draft
        if draft is None:
            return
        self._loading = True
        try:
            self.load(state, draft)
        finally:
            self._loading = False

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        raise NotImplementedError

    def change(self, what: str, fn: Callable[[evision.Settings], None]) -> None:
        """Stage an edit (applied to the mouse only when the user presses Apply)."""
        if self._loading or self.draft is None or self.on_edit is None:
            return
        self.on_edit(fn)
