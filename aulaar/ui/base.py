"""Common page scaffolding."""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ..manager import DeviceManager, DeviceState
from ..protocol import evision


def mutate(fn: Callable[[evision.Settings], None]) -> Callable[[evision.Settings], evision.Settings]:
    """Turn an in-place edit into the pure Settings -> Settings change the manager expects."""

    def change(settings: evision.Settings) -> evision.Settings:
        new = copy.deepcopy(settings)
        fn(new)
        return new

    return change


class Page(QScrollArea):
    title = ""
    subtitle = ""

    def __init__(self, manager: DeviceManager):
        super().__init__()
        self.manager = manager
        self.state: DeviceState | None = None
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

    def set_state(self, state: DeviceState) -> None:
        self.state = state
        if state.settings is None:
            return
        self._loading = True
        try:
            self.load(state, state.settings)
        finally:
            self._loading = False

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        raise NotImplementedError

    def change(self, what: str, fn: Callable[[evision.Settings], None]) -> None:
        """Send an edit to the mouse (ignored while the page is being filled from device state)."""
        if self._loading or self.state is None or self.state.settings is None:
            return
        self.manager.apply(self.state.key, mutate(fn), what)
