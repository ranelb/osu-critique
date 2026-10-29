"""Home-screen icons, drawn with zlib instead of an image library.

A phone that adds the page to its home screen wants a PNG or two. The
alternative to twenty lines here is Pillow as a dependency of a tool that
otherwise needs only numpy and the pinned slider — for one pink disc.

The art is the favicon: a pink disc on the page background, inset to 34 % of the
width so it survives Android's maskable crop (which keeps the middle 80 %).
Icons are generated on first request and cached for the life of the process;
nothing is written to disk, so a wheel install has no asset step.
"""
from __future__ import annotations

import struct
import zlib

BG = (10, 12, 18)
PINK = (255, 102, 170)
RADIUS = 0.34          # fraction of the icon's width
_cache: dict[int, bytes] = {}


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def png(size: int) -> bytes:
    """An RGBA PNG of ``size`` x ``size``: a pink disc on the page background."""
    if size in _cache:
        return _cache[size]
    centre = size / 2.0
    radius = size * RADIUS
    rows = bytearray()
    for y in range(size):
        rows.append(0)                      # filter type 0 for every scanline
        dy = y + 0.5 - centre
        for x in range(size):
            dx = x + 0.5 - centre
            # distance to the disc edge in pixels, clamped: one-pixel soft edge
            cover = radius + 0.5 - (dx * dx + dy * dy) ** 0.5
            if cover <= 0:
                rows += bytes((*BG, 255))
            elif cover >= 1:
                rows += bytes((*PINK, 255))
            else:
                mix = [round(b + (p - b) * cover) for b, p in zip(BG, PINK)]
                rows += bytes((*mix, 255))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    body = (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + _chunk(b"IEND", b""))
    _cache[size] = body
    return body
