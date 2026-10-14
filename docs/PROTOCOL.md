# Evision mouse protocol (AULA V9 / X9 families, AULA-8K Dongle)

This document describes the HID protocol that AULA HUB (https://hub.aulacn.com, a WebHID web app)
uses with the AULA V9/X9 mice. It was recovered from that app's JavaScript: the `vision` module of
the bundled Evision SDK. Device IDs there are `evision-device-ms-*`.

Statuses:
- **verified**: confirmed on hardware.
- **from SDK**: read from AULA HUB's code.
- **unknown**: not determined.

## Devices

USB vendor `0x320F`.

| PID | Product | Link |
|---|---|---|
| `0x22A0` | AULA-8K Dongle | 2.4G receiver |
| `0x22BA` | 2.4G dongle (older) | 2.4G receiver |
| `0x22B7` | V9+ / V9 Pro+ / V9 Ultra+ / V9 Max+ | wired |
| `0x22B8` | V9 / V9 Pro / V9 Ultra / V9 Max | wired |
| `0x22B6` | X9 / X9 Pro / X9 Ultra / X9 Max | wired |

Several models share a PID. The model comes from base-info byte 7, the **configId**:

| configId | Model | configId | Model |
|---|---|---|---|
| 0 | X9 Pro | 6 | V9 |
| 1 | X9 | 7 | V9 Pro |
| 2 | X9 Ultra | 8 | V9 Ultra |
| 3 | V9+ | 9 | V9 Max+ |
| 4 | V9 Pro+ | 10 | V9 Max |
| 5 | V9 Ultra+ | 11 | X9 Max |

X9 models have no body lighting.

## Interfaces

Each device exposes three HID interfaces. Wired and dongle have identical descriptors.

| Interface | Contents | Used for |
|---|---|---|
| 0 | mouse (report 1) | — |
| 1 | keyboard (7), vendor `0xFF01` (0x10), consumer (3), **vendor `0xFF1C` usage `0x92` (report 4, 63 bytes in and out)**, system control (2) | **configuration** |
| 2 | vendor `0xFF0B` usage `0x0104` (reports 0x2A–0x2D), `0xFF02` (feature 0x14) | firmware update only. Never touch it |

Find the config node by its report descriptor (application collection `0xFF1C/0x92`), not by
interface number.

## Framing

All configuration traffic is **report ID 4**. Offsets below index the 63 data bytes after the report
ID, as WebHID's `data` does. On hidraw, write `[0x04] + 63 bytes` and read `[0x04] + 63 bytes`.

Each link has a chunk size `L`:
- wired: `L = 56` (0x38)
- through the dongle: `L = 24` (0x18)

AULA HUB sends 31-byte packets on the dongle link. We zero-pad to 63 bytes, because the descriptor
declares 63 for both.

### Simple command

```
request: 00 00 CMD L 00 00 00 ...
reply:   next report-4 input report; value at data[7] (and data[8])
```

Timeout 2 s, 3 tries 100 ms apart.

### Block transfer (read or write)

```
cmd(0x01)                                   begin
for each chunk (offset += L):
  request: 00 00 CMD len offLo offHi 00 [payload...]   len = L, or the remainder on the last chunk
  reply:   data[3] = len, data[7 .. 7+len] = bytes (a write is echoed back)
cmd(0x02)                                   end
```

A 128-byte read is 3 chunks wired (56, 56, 16) and 6 through the dongle (5 × 24, then 8). There is no
checksum, no sequence number, and no encryption or handshake.

## Commands

| Cmd | Kind | Meaning |
|---|---|---|
| `0x01` / `0x02` | simple | begin / end a block transfer |
| `0x03` | read 10 | base info; `[7]` = configId |
| `0x03` | read 22 | `[20]`,`[21]` = mouse firmware version, shown as dotted hex digits (`0x10,0x05` → `1.0.0.5`) |
| `0x05` | read 128 | **config block** |
| `0x06` | write 128 | **config block** (full block, read-modify-write) |
| `0x07` / `0x08` | read 33 | default / current button matrix (11 × 3 bytes) |
| `0x09` | write 33 | button matrix |
| `0x0D` | simple | factory reset; re-read `0x05` about 300 ms later |
| `0x15` | write | macro blob |
| `0x1A` | simple | battery, `data[7]` = percent. No charging flag is known |
| `0xAA` | simple | through the dongle: is the mouse online? `data[7] != 0`. 0 or timeout means asleep or off |
| `0xB2` | simple | start receiver pairing (AULA HUB then polls `0xAA` for 30 s) |
| `0xB3` | simple | receiver firmware, `data[7]`,`data[8]` |

## Config block (128 bytes)

| Offset | Field | Values |
|---|---|---|
| 0 | profile index | 0 (only one profile on these models) |
| 1 | lighting effect | 0 Static, 1 Breathing, 2 Blink, 3 Spectrum, 4 Wave, 5 Off |
| 2 | lighting brightness | 0–4 (AULA HUB offers 0–3) |
| 3 | lighting speed | 0–4 (AULA HUB offers 0–3) |
| 4 | lighting direction | 1–2 (Wave) |
| 5 | colorful | 1 for Spectrum/Wave. AULA HUB never sets it, which is a bug |
| 6–8 | lighting R, G, B | |
| 9 | ? | unknown, keep as is |
| 10 | polling rate on 2.4G | index: 0=125, 1=250, 2=500, 3=1000, 4=2000, 5=4000, 6=8000 Hz |
| 11 | polling rate wired | same index |
| 12 | active DPI stage | 0–5 |
| 13 | lift-off distance | 0 = 1 mm, 1 = 2 mm |
| 14 + 9·i | DPI stage i (0–5) | `enabled, xySeparate, X lo, X hi, Y lo, Y hi, R, G, B`. DPI is u16 LE, 100–42000, step 50 |
| 68–69 | sleep time | u16 LE seconds: 180, 240, 300, 600, 900, 1200 |
| 70 | button debounce | ms: 1, 2, 4, 6, 8, 10 |
| 71 | motion sync | 0/1 |
| 72 | angle snapping ("linear calibration") | 0/1 |
| 73 | ? | unknown, keep as is |
| 74 | sensor rotation | int8, −30…+30 degrees |
| 75 | ? | unknown, keep as is |
| 76 | DPI indicator effect | 0 Off, 1 Static, 2 Breathing |
| 77 | DPI indicator brightness | 0–2 |
| 78 | DPI indicator speed | 0–2 |
| 79–127 | ? | unknown, keep as is |

## Events

The mouse sends input report **3** (normally consumer control) with these payloads:
- `01 04`: profile switched
- `02 04`: settings reset
- `FF FF`: connection error

Re-read the config block when one arrives. Pressing the DPI button changes byte 12 **without** an
event, so re-read the block when it might matter (for example on window focus).

## Button matrix (not used by Aulaar v1)

The matrix holds 11 slots of 3 bytes. Slots are identified by their factory value from command `0x07`.

| Bytes | Action |
|---|---|
| `10 BB 00` | mouse button: L 01, R 02, M 04, Back 08, Forward 10 |
| `13 0n 00` | DPI: + 01, − 02, cycle 03 |
| `20 MM UU` | keyboard: modifier mask + HID usage |
| `30 LL HH` | consumer usage |
| `70 id mode` / `71 id count` | macro |
| `14 interval count` | rapid fire |
| `A0 01 00` | Fn |

Macro blob (`0x15`):
- Header: `AA 55 82 00 05 00` + 10 × `00`.
- Then 5 u16 offsets.
- Each macro is `count u16, 00 00`, followed by its events.
- Each event is `delay u16 LE, (down<<7)|type, code`, where type is 0x0A key, 0x09 modifier, 0x01 mouse.
