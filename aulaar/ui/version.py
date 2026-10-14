"""Version Settings: firmware versions, backups and factory reset."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from .. import storage
from ..manager import DeviceState
from ..protocol import evision
from .base import Page
from .widgets import Card, SettingRow


class VersionPage(Page):
    title = "Version Settings"
    subtitle = "Firmware information and maintenance."

    def build(self) -> None:
        info = self.add(Card("Device"))
        self.values: dict[str, QLabel] = {}
        for key in ("Model", "Connection", "Mouse Firmware Version", "Receiver Firmware Version", "Interface"):
            label = QLabel("—", objectName="Muted")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.values[key] = label
            info.add(SettingRow(key, label))
        self.receiver_row = self.values["Receiver Firmware Version"].parentWidget()

        backup = self.add(Card("Settings Backup", "Aulaar saves a copy of the mouse's settings block the first time it connects."))
        open_btn = QPushButton("Open backup folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(storage.data_dir()))))
        backup.add(SettingRow(str(storage.data_dir()), open_btn))

        reset = self.add(Card("Factory Reset", "Restore every mouse setting (DPI, polling rate, lighting, …) to its factory state."))
        self.reset_btn = QPushButton("Factory Reset", objectName="Danger")
        self.reset_btn.clicked.connect(self._reset)
        reset.add(SettingRow("Reset the mouse", self.reset_btn, "This cannot be undone from the mouse itself."))

    def set_state(self, state: DeviceState) -> None:
        super().set_state(state)
        st = state.status
        self.values["Model"].setText(state.name + (f"  (config {st.config_id})" if st and st.config_id is not None else ""))
        self.values["Connection"].setText("2.4G via " + state.product_name if state.link == evision.WIRELESS else "USB cable")
        self.values["Mouse Firmware Version"].setText((st.mouse_firmware if st else None) or "—")
        self.values["Receiver Firmware Version"].setText((st.receiver_firmware if st else None) or "—")
        self.receiver_row.setVisible(state.link == evision.WIRELESS)
        self.values["Interface"].setText(state.key)

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        pass

    def _reset(self) -> None:
        if self.state is None:
            return
        answer = QMessageBox.warning(
            self,
            "Factory reset",
            f"Reset all settings of {self.state.name} to factory defaults?",
            QMessageBox.Reset | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Reset:
            self.manager.factory_reset(self.state.key)
