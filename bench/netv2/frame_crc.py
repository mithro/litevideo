#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-frame CRC-32 over the active pixels of a video stream.

The standard reflected CRC-32 (polynomial 0x04C11DB7, reflected form
0xEDB88320, init 0xFFFFFFFF, final XOR 0xFFFFFFFF, bytes LSB first) over the
byte sequence R, G, B of every DE pixel, latched at each VSYNC leading edge
together with a frame counter. It equals ``zlib.crc32`` over the packed
RGB bytes of the frame, so a host can check a captured or generated frame
with the standard library. ``frame_crc`` is the Python reference. The core
takes plain input signals so it can tap any ``video_data_layout`` source
without a second stream connection.
"""

import zlib

from migen import *

from litex.gen import *

CRC_POLY_REFLECTED = 0xEDB88320


def _crc_step_expr(crc, data_bytes):
    """Migen expression: CRC state after the bytes in ``data_bytes`` (each LSB first)."""
    bits = [crc[i] for i in range(32)]
    for byte in data_bytes:
        for n in range(8):
            fb = bits[0] ^ byte[n]
            new = [None] * 32
            for i in range(32):
                nxt = bits[i + 1] if i < 31 else 0
                if (CRC_POLY_REFLECTED >> i) & 1:
                    new[i] = nxt ^ fb
                else:
                    new[i] = nxt
            bits = new
    return Cat(*bits)


def frame_crc(pixels):
    """Python reference: ``pixels`` is an iterable of (r, g, b) for one frame."""
    return zlib.crc32(b"".join(bytes((r, g, b)) for r, g, b in pixels))


class FrameCRC(LiteXModule):
    def __init__(self):
        self.de    = Signal()
        self.vsync = Signal()
        self.r     = Signal(8)
        self.g     = Signal(8)
        self.b     = Signal(8)

        self.crc   = Signal(32)     # CRC of the last complete frame
        self.frame = Signal(32)     # frames completed

        # # #

        state = Signal(32, reset=0xFFFFFFFF)
        vsync_r = Signal()
        self.sync += vsync_r.eq(self.vsync)
        self.sync += [
            If(self.vsync & ~vsync_r,
                self.crc.eq(state ^ 0xFFFFFFFF),
                self.frame.eq(self.frame + 1),
                state.eq(0xFFFFFFFF),
            ).Elif(self.de,
                state.eq(_crc_step_expr(state, [self.r, self.g, self.b])),
            ),
        ]
