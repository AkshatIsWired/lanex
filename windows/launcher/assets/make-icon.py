#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Regenerate ``lanex.ico`` from the cockpit's own favicon.

    python3 windows/launcher/assets/make-icon.py

``lanex.ico`` is the Windows-side face of LanEx: the tray icon, the taskbar
icon of ``LanEx.exe``, the Start-menu shortcut, and the Setup wizard's icon.
Keeping it *generated* from ``lanex/server/static/vendor/favicon.png`` means the
Windows chrome can never drift from the UI's own brand mark — regenerate and
commit whenever the favicon changes.

Stdlib only (zlib), on purpose: no Pillow/ImageMagick in the build path, so CI
and any contributor's machine can reproduce the file byte-for-byte.

Why a multi-resolution ICO instead of one big image: Windows picks the nearest
size and scales the rest. The tray asks for 16x16, and a 16x16 produced by
*averaging* the 64x64 source here is visibly cleaner than one produced by
Windows' own on-the-fly shrink. Each entry is written as a 32-bit BGRA
BITMAPINFOHEADER DIB (the universally supported ICO encoding) rather than an
embedded PNG (Vista+ only, and Explorer still has PNG-entry quirks).
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

# Sizes Windows actually asks for: tray/menu 16, dialogs 24/32, Alt-Tab and
# large Explorer icons 48. Nothing above the 64x64 source — upscaling would only
# add blur and bytes.
SIZES = (64, 48, 32, 24, 16)

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "lanex" / "server" / "static" / "vendor" / "favicon.png"
DST = Path(__file__).resolve().parent / "lanex.ico"


def read_png_rgba(path: Path) -> tuple[int, int, bytearray]:
    """Decode *path* to (width, height, RGBA bytes). Minimal but strict."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    pos = 8
    width = height = depth = color = 0
    idat = bytearray()
    palette = b""
    trns = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length          # 4 len + 4 type + body + 4 CRC
        if kind == b"IHDR":
            width, height, depth, color, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body)
            if depth != 8:
                raise SystemExit(f"{path}: only 8-bit channels supported (got {depth})")
            if interlace:
                raise SystemExit(f"{path}: interlaced PNGs not supported")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if channels is None:
        raise SystemExit(f"{path}: unsupported PNG colour type {color}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    # Undo PNG's per-scanline filters (spec 9.2). `prev` is the reconstructed
    # line above; both are needed for the Paeth/Average predictors.
    out = bytearray(stride * height)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride
        if ftype == 1:      # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:    # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:    # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif ftype != 0:
            raise SystemExit(f"{path}: unknown scanline filter {ftype}")
        out[y * stride:(y + 1) * stride] = line
        prev = line

    # Normalise every colour type to straight RGBA.
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        if color == 6:
            rgba[i * 4:i * 4 + 4] = out[i * 4:i * 4 + 4]
        elif color == 2:
            rgba[i * 4:i * 4 + 3] = out[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
        elif color == 0:
            g = out[i]
            rgba[i * 4:i * 4 + 4] = bytes((g, g, g, 255))
        elif color == 4:
            g, a = out[i * 2], out[i * 2 + 1]
            rgba[i * 4:i * 4 + 4] = bytes((g, g, g, a))
        else:              # 3 — palette, optional tRNS alpha table
            idx = out[i]
            rgba[i * 4:i * 4 + 3] = palette[idx * 3:idx * 3 + 3]
            rgba[i * 4 + 3] = trns[idx] if idx < len(trns) else 255
    return width, height, rgba


def resize(src: bytearray, sw: int, sh: int, dw: int, dh: int) -> bytearray:
    """Area-average (box) downscale. Alpha-weighted so edge pixels stay clean.

    Averaging straight RGB across a transparent boundary drags the (arbitrary)
    colour of fully transparent pixels into the visible edge — the classic dark
    halo. Weighting each sample by its own alpha is what avoids it.
    """
    dst = bytearray(dw * dh * 4)
    for dy in range(dh):
        y0, y1 = dy * sh // dh, max(dy * sh // dh + 1, (dy + 1) * sh // dh)
        for dx in range(dw):
            x0, x1 = dx * sw // dw, max(dx * sw // dw + 1, (dx + 1) * sw // dw)
            r = g = b = a = 0
            n = 0
            for sy in range(y0, y1):
                row = sy * sw
                for sx in range(x0, x1):
                    p = (row + sx) * 4
                    pa = src[p + 3]
                    r += src[p] * pa
                    g += src[p + 1] * pa
                    b += src[p + 2] * pa
                    a += pa
                    n += 1
            o = (dy * dw + dx) * 4
            if a:
                dst[o], dst[o + 1], dst[o + 2] = r // a, g // a, b // a
            dst[o + 3] = a // n
    return dst


def dib(rgba: bytearray, size: int) -> bytes:
    """One ICO image: BITMAPINFOHEADER + bottom-up 32-bit BGRA + AND mask.

    The header lies about height on purpose (2x): every ICO DIB is defined as
    colour rows followed by a 1-bit mask of the same height. Modern Windows uses
    the alpha channel, but a mask of the right *size* must still be there or
    older shells (and some Inno Setup wizard paths) mis-parse the entry.
    """
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    px = bytearray()
    for y in range(size - 1, -1, -1):           # bottom-up
        row = y * size * 4
        for x in range(size):
            p = row + x * 4
            px += bytes((rgba[p + 2], rgba[p + 1], rgba[p], rgba[p + 3]))
    mask_stride = ((size + 31) // 32) * 4        # rows are 4-byte aligned
    return hdr + bytes(px) + bytes(mask_stride * size)


def main() -> int:
    if not SRC.exists():
        print(f"source icon missing: {SRC}", file=sys.stderr)
        return 1
    sw, sh, rgba = read_png_rgba(SRC)
    print(f"source: {SRC.name} {sw}x{sh}")

    images = []
    for size in SIZES:
        if size > sw or size > sh:
            print(f"  skip {size}px (larger than the source)")
            continue
        scaled = rgba if (size == sw and size == sh) else resize(rgba, sw, sh, size, size)
        images.append((size, dib(scaled, size)))
        print(f"  {size}x{size}: {len(images[-1][1])} bytes")

    # ICONDIR, then one ICONDIRENTRY per image, then the images themselves.
    # A width/height byte of 0 means 256 — irrelevant here, but keep the encoding
    # correct in case a 256px source ever lands.
    offset = 6 + 16 * len(images)
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for size, blob in images:
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                           len(blob), offset)
        offset += len(blob)
    for _size, blob in images:
        out += blob
    DST.write_bytes(bytes(out))
    print(f"wrote {DST} ({len(out)} bytes, {len(images)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
