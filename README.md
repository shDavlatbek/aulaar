# Aulaar

A Linux settings app for AULA gaming mice, in the spirit of [Solaar](https://github.com/pwr-Solaar/Solaar),
that does what the AULA HUB web driver does without Chrome or WebHID.

Supported mice:
- AULA **V9 Ultra+** (the main target)
- V9 / V9+ / V9 Pro / V9 Pro+ / V9 Ultra / V9 Max / V9 Max+
- X9 / X9 Pro / X9 Ultra / X9 Max

They work over the USB cable or through the **AULA-8K Dongle**.

## Features

- **Status**:
  - battery %
  - connection (Wired / 2.4G), with asleep detection through the dongle
  - mouse and receiver firmware versions
- **DPI Settings**:
  - six stages, 100–42000 DPI in steps of 50
  - separate X/Y DPI
  - per-stage indicator color
  - active stage
- **Performance Settings**:
  - polling rate 125–8000 Hz, kept separately for wired and 2.4G
  - Office / Balanced / Gaming presets
- **Parameter Settings**:
  - sensor: angle snapping, motion sync, lift-off distance (1/2 mm), sensor rotation (±30°)
  - buttons & power: debounce (1–10 ms), sleep time (3–20 min)
  - device lighting: Static / Breathing / Blink / Spectrum / Wave / Off, with color, brightness, speed and direction
  - DPI-indicator lighting
- **Version Settings**: firmware info, settings backup folder, factory reset.
- **Tray**:
  - The icon is a mouse that fills with charge, so it never looks like the laptop battery.
  - On KDE it stays in the hidden part of the system tray and only pops out when the battery is
    15% or lower.
  - Closing the window keeps Aulaar in the tray; *Quit* in the tray menu exits.

Changes are written to the mouse immediately, like AULA HUB. Before the first write, Aulaar saves the
mouse's original 128-byte settings block to `~/.config/aulaar/`. Firmware updating is deliberately not
implemented.

## Install

```sh
./install.sh
```

This needs sudo. It installs PySide6, dbus-python and pyudev from apt, installs a udev rule that gives
the logged-in user access to AULA's hidraw nodes, and adds an "Aulaar" launcher. Replug the dongle or
cable afterwards if the app reports a permission problem.

## Run

```sh
python3 -m aulaar              # GUI
python3 -m aulaar --probe      # read-only dump of everything the mouse reports
python3 -m aulaar --debug      # GUI with raw HID packets in the log
```

Run these from this folder, or with `PYTHONPATH` pointing at it.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

The protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

Copyright (C) 2026 Davlatbek

Aulaar is free software: you can redistribute it and/or modify it under the terms of the GNU General
Public License as published by the Free Software Foundation, either version 2 of the License, or (at
your option) any later version (`GPL-2.0-or-later`). See [LICENSE](LICENSE).

Aulaar is an independent project and is not affiliated with, endorsed by, or supported by AULA.
