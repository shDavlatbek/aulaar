"""Icons drawn with QPainter: a mouse silhouette that fills up with charge.

The tray icon is intentionally not battery-shaped, so it can't be mistaken for the laptop battery.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

ACCENT = QColor("#166dee")
WARN = QColor("#f5a524")
DANGER = QColor("#e5484d")
MUTED = QColor("#8a93a6")

LOW_BATTERY = 15


def level_color(level: int | None) -> QColor:
    if level is None:
        return MUTED
    if level <= LOW_BATTERY:
        return DANGER
    if level <= 30:
        return WARN
    return ACCENT


def _mouse_path(rect: QRectF) -> QPainterPath:
    """Top-down mouse body: rounded top, slightly wider rounded bottom."""
    w, h = rect.width(), rect.height()
    x, y = rect.x(), rect.y()
    path = QPainterPath()
    path.moveTo(x + w / 2, y)
    path.cubicTo(x + w * 0.02, y, x, y + h * 0.18, x, y + h * 0.42)
    path.lineTo(x, y + h * 0.66)
    path.cubicTo(x, y + h * 0.9, x + w * 0.2, y + h, x + w / 2, y + h)
    path.cubicTo(x + w * 0.8, y + h, x + w, y + h * 0.9, x + w, y + h * 0.66)
    path.lineTo(x + w, y + h * 0.42)
    path.cubicTo(x + w, y + h * 0.18, x + w * 0.98, y, x + w / 2, y)
    path.closeSubpath()
    return path


def paint_mouse(
    p: QPainter,
    rect: QRectF,
    level: int | None,
    *,
    body: QColor | None = None,
    outline: QColor | None = None,
    glow: QColor | None = None,
    asleep: bool = False,
) -> None:
    """Draw the mouse in `rect` (aspect ~0.62:1), filled from the bottom to `level` percent."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    path = _mouse_path(rect)
    stroke = max(1.0, rect.width() * 0.085)
    fill = level_color(level) if not asleep else MUTED
    outline = outline or (QColor("#e6e9ef") if not asleep else MUTED)

    if body is not None:
        p.fillPath(path, body)
    if level is not None and not asleep:
        frac = max(0.0, min(1.0, level / 100))
        clip = QRectF(rect.x(), rect.bottom() - rect.height() * frac, rect.width(), rect.height() * frac)
        p.save()
        p.setClipRect(clip)
        p.fillPath(path, fill)
        p.restore()
    if glow is not None:
        p.setPen(QPen(glow, stroke * 2.2))
        p.drawPath(path)
    p.setPen(QPen(outline, stroke))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    # button split and wheel
    top = rect.y()
    split = top + rect.height() * 0.38
    p.drawLine(QPointF(rect.center().x(), top + stroke * 0.5), QPointF(rect.center().x(), split))
    wheel_w = rect.width() * 0.16
    wheel = QRectF(rect.center().x() - wheel_w / 2, top + rect.height() * 0.1, wheel_w, rect.height() * 0.16)
    p.setBrush(outline)
    p.drawRoundedRect(wheel, wheel_w / 2, wheel_w / 2)
    p.restore()


def tray_image(size: int, level: int | None, asleep: bool = False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    h = size * 0.94
    w = h * 0.64
    rect = QRectF((size - w) / 2, (size - h) / 2, w, h)
    paint_mouse(p, rect, level, asleep=asleep, outline=QColor("#e6e9ef") if not asleep else MUTED)
    p.end()
    return img


def tray_icon(level: int | None, asleep: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        icon.addPixmap(QPixmap.fromImage(tray_image(size, level, asleep)))
    return icon
