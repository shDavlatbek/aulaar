"""Pending edits: settings changed in the UI but not yet applied to the mouse.

Changes are kept as {field path: value}, e.g. ("stages", 1, "x"): 1600, so they can be re-applied
on top of whatever the mouse reports later (a battery refresh or a DPI-button press must not wipe
them, and applying them must not overwrite fields the user didn't touch).
"""

from __future__ import annotations

import copy
from dataclasses import fields, is_dataclass
from typing import Any

from ..protocol import evision

Path = tuple
Changes = dict[Path, Any]

_LABELS = {
    "profile": "Profile",
    "lighting": "Device lighting",
    "polling_wireless": "Polling rate",
    "polling_wired": "Polling rate",
    "active_stage": "Active DPI stage",
    "lod": "Lift-off distance",
    "sleep_seconds": "Sleep time",
    "debounce_ms": "Debounce",
    "motion_sync": "Motion sync",
    "angle_snap": "Angle snapping",
    "sensor_rotation": "Sensor rotation",
    "dpi_lighting": "DPI lighting",
}


def leaves(obj: Any, prefix: Path = ()) -> Changes:
    """Flatten nested dataclasses and lists into {path: value}; tuples (colors) are values."""
    out: Changes = {}
    if is_dataclass(obj):
        for f in fields(obj):
            out.update(leaves(getattr(obj, f.name), prefix + (f.name,)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(leaves(v, prefix + (i,)))
    else:
        out[prefix] = obj
    return out


def diff(base: evision.Settings, new: evision.Settings) -> Changes:
    old = leaves(base)
    return {p: v for p, v in leaves(new).items() if old.get(p) != v}


def apply_changes(settings: evision.Settings, changes: Changes) -> evision.Settings:
    s = copy.deepcopy(settings)
    for path, value in changes.items():
        target: Any = s
        for step in path[:-1]:
            target = target[step] if isinstance(step, int) else getattr(target, step)
        last = path[-1]
        if isinstance(last, int):
            target[last] = value
        else:
            setattr(target, last, value)
    return s


def prune(settings: evision.Settings, changes: Changes) -> Changes:
    """Drop changes the mouse already has (e.g. after a successful apply)."""
    return diff(settings, apply_changes(settings, changes))


def labels(changes: Changes) -> list[str]:
    out: list[str] = []
    for path in changes:
        label = f"DPI stage {path[1] + 1}" if path[0] == "stages" else _LABELS.get(path[0], path[0])
        if label not in out:
            out.append(label)
    return out
