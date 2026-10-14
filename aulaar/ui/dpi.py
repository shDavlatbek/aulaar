"""DPI Settings: six stages, the active one is edited."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QWidget

from ..manager import DeviceState
from ..protocol import evision
from .base import Page
from .widgets import Card, ColorButton, SettingRow, Toggle, ValueSlider


class StageTile(QPushButton):
    def __init__(self, index: int):
        super().__init__(objectName="StageTile", checkable=True)
        self.index = index
        self.stage = evision.DpiStage()
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(QSize(120, 92))

    def set_stage(self, stage: evision.DpiStage) -> None:
        self.stage = stage
        self.setToolTip("" if stage.enabled else "This stage is disabled in the DPI cycle")
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(14, 12, -14, -12)
        st = self.stage
        dim = not st.enabled
        p.setPen(QColor("#8a93a6"))
        p.drawText(r, Qt.AlignTop | Qt.AlignLeft, f"Stage {self.index + 1}" + ("  (off)" if dim else ""))
        p.setBrush(QColor(*st.color))
        p.setPen(QColor("#3a4456"))
        p.drawEllipse(QRectF(r.right() - 12, r.top() + 2, 12, 12))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#4b5263") if dim else QColor("#e6e9ef"))
        text = f"{st.x}" if not st.xy_split else f"{st.x}/{st.y}"
        p.drawText(r, Qt.AlignBottom | Qt.AlignLeft, text)


class DpiPage(Page):
    title = "DPI Settings"
    subtitle = "Click a stage to make it active; the DPI button on the mouse cycles through them. Changes are saved to the mouse right away."

    def build(self) -> None:
        tiles = QWidget()
        grid = QGridLayout(tiles)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.tiles = [StageTile(i) for i in range(evision.NUM_STAGES)]
        self.group = QButtonGroup(self)
        for i, t in enumerate(self.tiles):
            self.group.addButton(t, i)
            grid.addWidget(t, i // 3, i % 3)
        self.group.idClicked.connect(self._activate)
        self.add(tiles)

        self.editor = Card("Stage 1", "Sensitivity and indicator color of the active stage.")
        self.color = ColorButton()
        self.color.colorPicked.connect(self._color)
        self.editor.add(SettingRow("DPI Lighting", self.color, "Color of the DPI indicator for this stage."))
        self.split = Toggle()
        self.split.toggledByUser.connect(self._split)
        self.editor.add(SettingRow("X/Y Axis Separate", self.split, "Use a different DPI for horizontal and vertical movement."))
        self.both = ValueSlider(evision.DPI_MIN, evision.DPI_MAX, evision.DPI_STEP, " DPI", 110)
        self.both.committed.connect(lambda v: self._dpi(x=v, y=v))
        self.row_both = self.editor.add(SettingRow("DPI", self.both, stacked=True))
        self.x = ValueSlider(evision.DPI_MIN, evision.DPI_MAX, evision.DPI_STEP, " DPI", 110)
        self.x.committed.connect(lambda v: self._dpi(x=v))
        self.row_x = self.editor.add(SettingRow("X Axis", self.x, stacked=True))
        self.y = ValueSlider(evision.DPI_MIN, evision.DPI_MAX, evision.DPI_STEP, " DPI", 110)
        self.y.committed.connect(lambda v: self._dpi(y=v))
        self.row_y = self.editor.add(SettingRow("Y Axis", self.y, stacked=True))
        self.add(self.editor)

    def _active(self) -> int:
        s = self.state.settings if self.state else None
        return s.active_stage if s and 0 <= s.active_stage < evision.NUM_STAGES else 0

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        for tile, stage in zip(self.tiles, s.stages):
            tile.set_stage(stage)
        i = self._active()
        self.tiles[i].setChecked(True)
        st = s.stages[i]
        self.editor.title_label.setText(f"Stage {i + 1}")
        self.color.setColor(st.color)
        self.split.setChecked(st.xy_split)
        self.row_both.setVisible(not st.xy_split)
        self.row_x.setVisible(st.xy_split)
        self.row_y.setVisible(st.xy_split)
        self.both.setValue(st.x)
        self.x.setValue(st.x)
        self.y.setValue(st.y)

    def _activate(self, index: int) -> None:
        def f(s):
            s.active_stage = index

        self.change(f"Switching to stage {index + 1}", f)

    def _stage_edit(self, what: str, edit) -> None:
        i = self._active()
        self.change(what, lambda s: edit(s.stages[i]))

    def _color(self, rgb) -> None:
        self._stage_edit("Saving stage color", lambda st: setattr(st, "color", tuple(rgb)))

    def _split(self, on: bool) -> None:
        def edit(st):
            st.xy_split = on
            if not on:
                st.y = st.x

        self.row_both.setVisible(not on)
        self.row_x.setVisible(on)
        self.row_y.setVisible(on)
        self._stage_edit("Saving X/Y mode", edit)

    def _dpi(self, x: int | None = None, y: int | None = None) -> None:
        def edit(st):
            if x is not None:
                st.x = evision.snap_dpi(x)
            if y is not None:
                st.y = evision.snap_dpi(y)

        self._stage_edit("Saving DPI", edit)
