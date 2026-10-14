"""Parameter Settings: sensor, buttons and power, device and DPI lighting."""

from __future__ import annotations

from ..manager import DeviceState
from ..protocol import evision
from .base import Page
from .widgets import Card, ColorButton, SettingRow, Segmented, Toggle, ValueSlider

FOUR_LEVELS_SPEED = ("Slowest", "Slow", "Fast", "Fastest")
FOUR_LEVELS_BRIGHT = ("Darkest", "Dark", "Bright", "Brightest")


class ParametersPage(Page):
    title = "Parameter Settings"
    subtitle = "Sensor behavior, power saving and lighting."

    def build(self) -> None:
        sensor = self.add(Card("Sensor"))
        self.angle = Toggle()
        self.angle.toggledByUser.connect(lambda on: self.change("Saving angle snapping", lambda s: setattr(s, "angle_snap", on)))
        sensor.add(SettingRow("Angle Snapping", self.angle, "Straightens slightly diagonal movement into horizontal or vertical lines."))
        self.sync = Toggle()
        self.sync.toggledByUser.connect(lambda on: self.change("Saving motion sync", lambda s: setattr(s, "motion_sync", on)))
        sensor.add(SettingRow("Motion Sync", self.sync, "Aligns sensor reads with USB polling for more consistent tracking (adds a tiny delay)."))
        self.lod = Segmented([(f"{mm} mm", i) for i, mm in enumerate(evision.LOD_MM)])
        self.lod.valueChanged.connect(lambda i: self.change("Saving lift-off distance", lambda s: setattr(s, "lod", i)))
        sensor.add(SettingRow("LOD (Lift-Off Distance)", self.lod, "Height at which the sensor stops tracking when you lift the mouse."))
        self.rotation = ValueSlider(evision.ROTATION_MIN, evision.ROTATION_MAX, 1, "°", 80)
        self.rotation.committed.connect(lambda v: self.change("Saving sensor rotation", lambda s: setattr(s, "sensor_rotation", v)))
        sensor.add(SettingRow("Sensor Rotation", self.rotation, "Compensates for holding the mouse at an angle (−30° … +30°).", stacked=True))

        power = self.add(Card("Buttons & Power"))
        self.debounce = Segmented([(f"{ms} ms", ms) for ms in evision.DEBOUNCE_MS])
        self.debounce.valueChanged.connect(lambda ms: self.change("Saving debounce", lambda s: setattr(s, "debounce_ms", ms)))
        power.add(SettingRow("Button Debounce Delay", self.debounce, "Lower is faster; raise it if a button double-clicks by itself.", stacked=True))
        self.sleep = Segmented([(f"{sec // 60} min", sec) for sec in evision.SLEEP_SECONDS])
        self.sleep.valueChanged.connect(lambda sec: self.change("Saving sleep time", lambda s: setattr(s, "sleep_seconds", sec)))
        power.add(SettingRow("Sleep Settings", self.sleep, "Idle time before the mouse goes to sleep to save battery.", stacked=True))

        self.light_card = self.add(Card("Device Lighting"))
        self.effect = Segmented([(name, i) for i, name in enumerate(evision.LIGHT_MODES)])
        self.effect.valueChanged.connect(self._set_effect)
        self.light_card.add(SettingRow("Effect", self.effect, stacked=True))
        self.color = ColorButton()
        self.color.colorPicked.connect(lambda rgb: self.change("Saving light color", lambda s: setattr(s.lighting, "color", tuple(rgb))))
        self.color_row = self.light_card.add(SettingRow("Color", self.color))
        self.brightness = Segmented([(n, i) for i, n in enumerate(FOUR_LEVELS_BRIGHT)])
        self.brightness.valueChanged.connect(lambda v: self.change("Saving brightness", lambda s: setattr(s.lighting, "brightness", v)))
        self.light_card.add(SettingRow("Brightness", self.brightness))
        self.speed = Segmented([(n, i) for i, n in enumerate(FOUR_LEVELS_SPEED)])
        self.speed.valueChanged.connect(lambda v: self.change("Saving speed", lambda s: setattr(s.lighting, "speed", v)))
        self.light_card.add(SettingRow("Speed", self.speed))
        self.direction = Segmented([("Forward", 1), ("Reverse", 2)])
        self.direction.valueChanged.connect(lambda v: self.change("Saving direction", lambda s: setattr(s.lighting, "direction", v)))
        self.direction_row = self.light_card.add(SettingRow("Direction", self.direction))

        dpi = self.add(Card("DPI Lighting", "The indicator that shows the active DPI stage color."))
        self.dpi_effect = Segmented([(n, i) for i, n in enumerate(evision.DPI_LIGHT_MODES)])
        self.dpi_effect.valueChanged.connect(lambda v: self.change("Saving DPI light", lambda s: setattr(s.dpi_lighting, "mode", v)))
        dpi.add(SettingRow("DPI Light Effect", self.dpi_effect))
        self.dpi_brightness = Segmented([(n, i) for i, n in enumerate(("Darkest", "Medium", "Brightest"))])
        self.dpi_brightness.valueChanged.connect(lambda v: self.change("Saving DPI light", lambda s: setattr(s.dpi_lighting, "brightness", v)))
        dpi.add(SettingRow("Brightness", self.dpi_brightness))
        self.dpi_speed = Segmented([(n, i) for i, n in enumerate(("Slowest", "Medium", "Fastest"))])
        self.dpi_speed.valueChanged.connect(lambda v: self.change("Saving DPI light", lambda s: setattr(s.dpi_lighting, "speed", v)))
        dpi.add(SettingRow("Speed", self.dpi_speed))

    def load(self, state: DeviceState, s: evision.Settings) -> None:
        self.angle.setChecked(s.angle_snap)
        self.sync.setChecked(s.motion_sync)
        self.lod.setValue(s.lod)
        self.rotation.setValue(max(evision.ROTATION_MIN, min(evision.ROTATION_MAX, s.sensor_rotation)))
        self.debounce.setValue(s.debounce_ms)
        self.sleep.setValue(s.sleep_seconds)

        self.light_card.setVisible(state.model is None or state.model.has_body_lighting)
        lt = s.lighting
        self.effect.setValue(lt.mode)
        self.color.setColor(lt.color)
        self.brightness.setValue(lt.brightness)
        self.speed.setValue(lt.speed)
        self.direction.setValue(lt.direction)
        off = lt.mode == evision.LIGHT_OFF
        self.color.setEnabled(not off and lt.mode not in evision.COLORFUL_LIGHT_MODES)
        self.brightness.setEnabled(not off)
        self.speed.setEnabled(lt.mode not in (evision.LIGHT_STATIC, evision.LIGHT_OFF))
        self.direction_row.setVisible(lt.mode == evision.LIGHT_WAVE)

        dl = s.dpi_lighting
        self.dpi_effect.setValue(dl.mode)
        self.dpi_brightness.setValue(dl.brightness)
        self.dpi_speed.setValue(dl.speed)
        self.dpi_brightness.setEnabled(dl.mode != evision.DPI_LIGHT_OFF)
        self.dpi_speed.setEnabled(dl.mode == evision.DPI_LIGHT_BREATHING)

    def _set_effect(self, mode: int) -> None:
        def f(s):
            s.lighting.mode = mode
            # AULA HUB never sets this flag, which leaves Spectrum and Wave without their colors.
            s.lighting.colorful = mode in evision.COLORFUL_LIGHT_MODES
            if s.lighting.direction not in (1, 2):
                s.lighting.direction = 1

        self.change(f"Setting lighting to {evision.LIGHT_MODES[mode]}", f)
