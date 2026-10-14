#!/usr/bin/env bash
# Install Aulaar's system pieces: Qt6 bindings, the hidraw udev rule and a launcher entry.
set -euo pipefail
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing PySide6 (Qt6), dbus-python and pyudev from apt"
sudo apt install -y python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork \
    python3-dbus python3-pyudev

echo "==> Installing udev rule (access to AULA hidraw nodes for the logged-in user)"
sudo install -m 0644 "$APPDIR/data/70-aulaar.rules" /etc/udev/rules.d/70-aulaar.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change

echo "==> Installing launcher entry"
mkdir -p "$HOME/.local/share/applications"
sed "s|@APPDIR@|$APPDIR|g" "$APPDIR/data/aulaar.desktop.in" > "$HOME/.local/share/applications/aulaar.desktop"

echo "Done. Start it from the app menu (Aulaar) or with: PYTHONPATH=$APPDIR python3 -m aulaar"
