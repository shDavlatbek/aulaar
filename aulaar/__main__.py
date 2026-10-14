"""Entry point: `python3 -m aulaar` starts the GUI; `--probe` prints what the mice report."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__, storage
from .device import Mouse
from .devices import find
from .hidraw import enumerate_nodes
from .protocol import evision


def _print_settings(s: evision.Settings, link: int) -> None:
    rate = lambda i: f"{evision.POLLING_RATES[i]} Hz" if i < len(evision.POLLING_RATES) else f"? ({i})"
    print(f"    polling        : wired {rate(s.polling_wired)}, 2.4G {rate(s.polling_wireless)}"
          f"  (active link uses {rate(s.polling_index(link))})")
    for i, st in enumerate(s.stages):
        mark = "*" if i == s.active_stage else " "
        dpi = f"{st.x}x{st.y}" if st.xy_split else f"{st.x}"
        print(f"    DPI stage {i + 1} {mark} : {dpi:>11} enabled={int(st.enabled)} color=#{bytes(st.color).hex()}")
    lod = f"{evision.LOD_MM[s.lod]} mm" if s.lod < 2 else f"? ({s.lod})"
    print(f"    LOD            : {lod}")
    print(f"    motion sync    : {s.motion_sync}   angle snapping: {s.angle_snap}")
    print(f"    debounce       : {s.debounce_ms} ms   sleep: {s.sleep_seconds} s   rotation: {s.sensor_rotation}°")
    lt = s.lighting
    mode = evision.LIGHT_MODES[lt.mode] if lt.mode < len(evision.LIGHT_MODES) else f"? ({lt.mode})"
    print(f"    lighting       : {mode} brightness={lt.brightness} speed={lt.speed} direction={lt.direction}"
          f" colorful={int(lt.colorful)} color=#{bytes(lt.color).hex()}")
    dl = s.dpi_lighting
    dmode = evision.DPI_LIGHT_MODES[dl.mode] if dl.mode < 3 else f"? ({dl.mode})"
    print(f"    DPI lighting   : {dmode} brightness={dl.brightness} speed={dl.speed}")
    problems = evision.validate(s)
    if problems:
        print(f"    out of range   : {', '.join(problems)}")


def probe() -> int:
    """Read-only dump of every AULA config interface."""
    aula = [n for n in enumerate_nodes() if n.vid == 0x320F]
    print("AULA hidraw nodes:")
    for n in aula:
        cols = ", ".join(f"{c.usage_page:#06x}/{c.usage:#04x}" for c in n.collections)
        access = "rw" if os.access(n.path, os.R_OK | os.W_OK) else "NO ACCESS"
        print(f"  {n.path:<14} {n.vid:04x}:{n.pid:04x} if{n.interface} {access:<9} {n.name!r}  [{cols}]")
    found = find()
    if not found:
        print("No supported AULA config interface found.")
        return 1
    rc = 0
    for f in found:
        print(f"\n== {f.product.name} via {f.node.path} ({'2.4G receiver' if f.product.is_receiver else 'wired'})")
        if not os.access(f.node.path, os.R_OK | os.W_OK):
            print("   no permission: run ./install.sh (udev rule), then replug or log out/in")
            rc = 1
            continue
        mouse = Mouse(f)
        try:
            online = mouse.is_online()
            print(f"    online         : {online}")
            if not online:
                print("    (mouse asleep or off: move it and probe again)")
                continue
            level, raw = mouse.battery()
            print(f"    battery        : {level if level is not None else '?'}%   raw reply: {evision.hex_bytes(raw[:16])}")
            cid = mouse.config_id()
            from .devices import model_for
            model = model_for(cid)
            print(f"    model          : {model.name if model else 'unknown'} (configId {cid})")
            print(f"    mouse firmware : {mouse.mouse_firmware()}")
            if f.product.is_receiver:
                print(f"    receiver fw    : {mouse.receiver_firmware()}")
            block = mouse.read_config()
            print("    config block   :")
            for off in range(0, len(block), 16):
                print(f"      {off:3d}: {evision.hex_bytes(block[off:off + 16])}")
            _print_settings(evision.decode_config(block), mouse.link)
        except (evision.ProtocolError, OSError) as e:
            print(f"    ERROR: {e}")
            rc = 1
        finally:
            mouse.close()
    return rc


def set_polling(hz: int, path: str | None) -> int:
    """Write test: change the polling rate of the active link (backup first, verify by re-reading)."""
    if hz not in evision.POLLING_RATES:
        print(f"polling rate must be one of {evision.POLLING_RATES}")
        return 2
    candidates = [f for f in find() if path in (None, f.node.path)]
    if len(candidates) != 1:
        print("Pick exactly one interface with --device:", ", ".join(f.node.path for f in candidates) or "none found")
        return 2
    mouse = Mouse(candidates[0])
    try:
        if not mouse.is_online():
            print("mouse is asleep or off")
            return 1
        block = mouse.read_config()
        print("backup:", storage.backup_config(mouse.product.name, block))
        before = evision.decode_config(block).polling_index(mouse.link)
        index = evision.POLLING_RATES.index(hz)
        mouse.apply(lambda s: s.with_polling(mouse.link, index))
        after = mouse.read_settings().polling_index(mouse.link)
        print(f"polling ({mouse.link_name}): {evision.POLLING_RATES[before]} Hz -> {evision.POLLING_RATES[after]} Hz")
        return 0 if after == index else 1
    finally:
        mouse.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aulaar", description="Settings and battery for AULA mice")
    parser.add_argument("--version", action="version", version=f"aulaar {__version__}")
    parser.add_argument("--probe", action="store_true", help="print device info and settings (read-only)")
    parser.add_argument("--set-polling", type=int, metavar="HZ", help="set the polling rate of the active link")
    parser.add_argument("--device", metavar="PATH", help="hidraw node to use with --set-polling")
    parser.add_argument("--fake-battery", type=int, metavar="PCT", help="GUI testing: pretend the battery is PCT%%")
    parser.add_argument("--debug", action="store_true", help="log raw HID packets")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.probe:
        return probe()
    if args.set_polling is not None:
        return set_polling(args.set_polling, args.device)
    from .app import run

    return run(fake_battery=args.fake_battery)


if __name__ == "__main__":
    sys.exit(main())
