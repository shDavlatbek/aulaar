"""Performance Settings: polling rate and the HUB's Office / Balanced / Gaming presets."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from ..manager import DeviceState
from ..protocol import evision
from .base import Page
from .widgets import Card, SettingRow, Segmented

MODES = (
    ("Office", 500, "Lowest power draw and the longest battery life. Plenty for desktop work."),
    ("Balanced", 2000, "Smooth, responsive tracking with good battery life."),
    ("Gaming", 8000, "8000 Hz for the lowest input latency. Uses the most battery and CPU."),
)


def mode_for(rate: int) -> int:
    for i, (_, top, _) in enumerate(MODES):
        if rate <= top:
            return i
    return len(MODES) - 1


class PerformancePage(Page):
    title = "Performance Settings"
    subtitle = "How often the mouse reports its position to the computer."

    def build(self) -> None:
        card = self.add(Card("Polling Rate"))
        self.rate = Segmented([(f"{hz}" if hz < 1000 else f"{hz // 1000}K", i) for i, hz in enumerate(evision.POLLING_RATES)])
        self.rate.valueChanged.connect(self._set_rate)
        self.rate_row = card.add(SettingRow("Report rate (Hz)", self.rate, stacked=True))
        self.rate_note = card.add(QLabel(objectName="Muted", wordWrap=True))

        card = self.add(Card("Performance Mode", "Presets for the polling rate of the current connection."))
        self.mode = Segmented([(name, i) for i, (name, _, _) in enumerate(MODES)])
        self.mode.valueChanged.connect(lambda i: self._set_rate(evision.POLLING_RATES.index(MODES[i][1])))
        card.add(self.mode)
        self.mode_text = card.add(QLabel(objectName="Muted", wordWrap=True))

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        idx = s.polling_index(state.link)
        self.rate.setValue(idx)
        other_idx = s.polling_wired if state.link == evision.WIRELESS else s.polling_wireless
        other = "wired" if state.link == evision.WIRELESS else "2.4G"
        other_rate = f"{evision.POLLING_RATES[other_idx]} Hz" if other_idx < len(evision.POLLING_RATES) else "unknown"
        self.rate_note.setText(
            f"This is the {state.link_name.lower() if state.link == evision.WIRED else '2.4G'} setting. "
            f"The mouse keeps a separate rate for the {other} connection ({other_rate})."
        )
        if idx < len(evision.POLLING_RATES):
            m = mode_for(evision.POLLING_RATES[idx])
            self.mode.setValue(m)
            self.mode_text.setText(MODES[m][2])
        else:
            self.mode.setValue(None)
            self.mode_text.setText("")

    def _set_rate(self, index: int) -> None:
        link = self.state.link if self.state else evision.WIRED
        hz = evision.POLLING_RATES[index]
        self.change(f"Setting polling rate to {hz} Hz", lambda s: setattr(
            s, "polling_wireless" if link == evision.WIRELESS else "polling_wired", index))
