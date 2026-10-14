"""Small widgets shared by the pages."""

from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import icons


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(14)
        head = QVBoxLayout()
        head.setSpacing(2)
        self.title_label = QLabel(title, objectName="CardTitle")
        head.addWidget(self.title_label)
        if subtitle:
            s = QLabel(subtitle, objectName="Muted", wordWrap=True)
            head.addWidget(s)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(16)
        outer.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget


class SettingRow(QWidget):
    """Label and hint on the left, a control on the right (or below, if `stacked`)."""

    def __init__(self, label: str, control: QWidget, hint: str = "", stacked: bool = False):
        super().__init__()
        layout = QVBoxLayout(self) if stacked else QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8 if stacked else 16)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.label = QLabel(label, objectName="SettingLabel")
        text.addWidget(self.label)
        if hint:
            h = QLabel(hint, objectName="SettingHint", wordWrap=True)
            text.addWidget(h)
        layout.addLayout(text, 1)
        if stacked:
            layout.addWidget(control)
        else:
            layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.control = control


class Segmented(QWidget):
    """A row of mutually exclusive buttons. Emits `valueChanged` only on user clicks."""

    valueChanged = Signal(object)

    def __init__(self, options: Sequence[tuple[str, Any]], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.values = [v for _, v in options]
        for i, (text, _) in enumerate(options):
            b = QPushButton(text, objectName="Segment", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("first", i == 0)
            b.setProperty("last", i == len(options) - 1)
            self.group.addButton(b, i)
            layout.addWidget(b)
        self.group.idClicked.connect(lambda i: self.valueChanged.emit(self.values[i]))

    def setValue(self, value: Any) -> None:
        if value in self.values:
            self.group.button(self.values.index(value)).setChecked(True)
        else:  # unknown value from the device: show nothing selected
            self.group.setExclusive(False)
            for b in self.group.buttons():
                b.setChecked(False)
            self.group.setExclusive(True)

    def setOptionEnabled(self, value: Any, enabled: bool) -> None:
        if value in self.values:
            self.group.button(self.values.index(value)).setEnabled(enabled)


class Toggle(QAbstractButton):
    """iOS-style switch. `toggledByUser` fires only for clicks, not for setChecked()."""

    toggledByUser = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.clicked.connect(lambda checked: self.toggledByUser.emit(checked))

    def sizeHint(self) -> QSize:
        return QSize(44, 24)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt API)
        super().setChecked(checked)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = QColor("#166dee") if self.isEnabled() else QColor("#2a3550")
        off = QColor("#2a303c")
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.x() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor("#8a93a6"))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))


class ColorButton(QPushButton):
    colorPicked = Signal(tuple)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = (255, 255, 255)
        self.setFixedSize(QSize(72, 32))
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)

    def setColor(self, rgb: tuple[int, int, int]) -> None:
        self._color = tuple(rgb)
        self.update()

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._color), self, "Choose color")
        if c.isValid():
            self.setColor((c.red(), c.green(), c.blue()))
            self.colorPicked.emit(self._color)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        color = QColor(*self._color)
        if not self.isEnabled():
            color.setAlpha(60)
        p.setPen(QPen(QColor("#3a4456"), 1))
        p.setBrush(color)
        p.drawRoundedRect(r, 5, 5)


class ValueSlider(QWidget):
    """Slider plus spin box. `committed` fires on slider release or when the spin box is confirmed."""

    committed = Signal(int)

    def __init__(self, minimum: int, maximum: int, step: int, suffix: str = "", spin_width: int = 96):
        super().__init__()
        self.step = step
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum // step, maximum // step) if step > 1 else self.slider.setRange(minimum, maximum)
        self.slider.setPageStep(max(1, 1000 // step) if step > 1 else 5)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(spin_width)
        self.spin.setKeyboardTracking(False)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._commit)
        self.spin.editingFinished.connect(self._spin_done)
        self._last: int | None = None
        # wheel / keyboard / page clicks: commit once the value settles
        self._settle = QTimer(self, singleShot=True, interval=350)
        self._settle.timeout.connect(self._commit)

    def _to_slider(self, v: int) -> int:
        return v // self.step if self.step > 1 else v

    def _from_slider(self, v: int) -> int:
        return v * self.step if self.step > 1 else v

    def _slider_moved(self, v: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(self._from_slider(v))
        self.spin.blockSignals(False)
        if not self.slider.isSliderDown():
            self._settle.start()

    def _commit(self) -> None:
        self._settle.stop()
        v = self.value()
        if v != self._last:
            self._last = v
            self.committed.emit(v)

    def _spin_done(self) -> None:
        v = round(self.spin.value() / self.step) * self.step if self.step > 1 else self.spin.value()
        self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.slider.blockSignals(False)
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self._commit()

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:
        if self.slider.isSliderDown() or self._settle.isActive():
            return  # the user is mid-edit; their value wins and is committed shortly
        self._last = v
        for w in (self.slider, self.spin):
            w.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.spin.setValue(v)
        for w in (self.slider, self.spin):
            w.blockSignals(False)


class BatteryBadge(QWidget):
    """Four bars and a percentage, like AULA HUB's header (but honest about unknown values)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.level: int | None = None
        self.text = "—"
        self.setMinimumSize(96, 22)

    def setLevel(self, level: int | None, text: str | None = None) -> None:
        self.level = level
        self.text = text if text is not None else (f"{level}%" if level is not None else "—")
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(100, 22)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = icons.level_color(self.level)
        bars = 0 if self.level is None else max(1, min(4, round(self.level / 25)))
        h = self.height()
        for i in range(4):
            r = QRectF(i * 9, h * 0.25, 6, h * 0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(color if i < bars else QColor("#2a303c"))
            p.drawRoundedRect(r, 2, 2)
        p.setPen(QColor("#e6e9ef") if self.level is not None else QColor("#8a93a6"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(42, 0, self.width() - 42, h), Qt.AlignVCenter | Qt.AlignLeft, self.text)


class MouseHero(QWidget):
    """Large mouse illustration tinted with the active DPI color and charge level."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.level: int | None = None
        self.glow: QColor | None = None
        self.asleep = False
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set(self, level: int | None, glow: tuple[int, int, int] | None, asleep: bool) -> None:
        self.level, self.asleep = level, asleep
        self.glow = QColor(*glow, 110) if glow else None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        h = self.height() - 16
        w = h * 0.62
        rect = QRectF((self.width() - w) / 2, 8, w, h)
        icons.paint_mouse(
            p,
            rect,
            self.level,
            body=QColor("#1a1f28"),
            outline=QColor("#3a4456") if self.asleep else QColor("#c9d1de"),
            glow=None if self.asleep else self.glow,
            asleep=self.asleep,
        )
