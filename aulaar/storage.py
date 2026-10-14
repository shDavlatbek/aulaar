"""Per-user files: config block backups."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    path = Path(base) / "aulaar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_config(label: str, block: bytes) -> Path:
    """Save a raw config block, e.g. ~/.config/aulaar/backup-aula-v9-ultra-20261013-171500.bin."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "mouse"
    path = data_dir() / f"backup-{slug}-{time.strftime('%Y%m%d-%H%M%S')}.bin"
    path.write_bytes(block)
    return path


def has_backup(label: str) -> bool:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "mouse"
    return any(data_dir().glob(f"backup-{slug}-*.bin"))
