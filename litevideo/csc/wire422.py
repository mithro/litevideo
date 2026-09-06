#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""YCbCr 4:2:2 in the HDMI wire mapping (HDMI 1.3 §6.5.1, Figure 6-2).

4:2:2 components are 12 bits on the wire. Per pixel pair (pixel 0 even,
pixel 1 odd, counted from the first active pixel of the line):

    channel 2: Cb[11:4] on pixel 0, Cr[11:4] on pixel 1
    channel 1: Y[11:4] of each pixel
    channel 0: {C[3:0], Y[3:0]}  (the low nibbles; zero for 8-bit components)

These free-running modules carry the pixel stream as ``c0/c1/c2`` with
``de``; parity restarts at every DE rise. ``YCbCr444ToWire422`` averages the
chroma of each pair (rounded); ``Wire422ToYCbCr444`` replicates the pair's
chroma into both pixels (no interpolation). Both have latency 1.
"""

from migen import *

from litex.gen import *

from litevideo.csc.matrix import matrix_layout


def wire_layout(dw):
    return [("de", 1)] + matrix_layout(dw)


class YCbCr444ToWire422(LiteXModule):
    """sink: c0 = Cb, c1 = Y, c2 = Cr (the 4:4:4 wire order of Figure 6-3);
    source: the 4:2:2 wire words."""
    latency = 1

    def __init__(self, dw=8):
        self.sink   = Record(wire_layout(dw))
        self.source = Record(wire_layout(dw))

        # # #

        odd = Signal()  # parity of the pixel at sink now
        self.sync += If(~self.sink.de, odd.eq(0)).Else(odd.eq(~odd))

        prev = Record(wire_layout(dw))
        self.sync += prev.raw_bits().eq(self.sink.raw_bits())

        # Even pixel (prev) leaves with the pair's mean Cb, using the odd pixel arriving now.
        cb_mean = Signal(dw)
        cr_mean = Signal(dw)
        cb_sum, cr_sum = Signal(dw + 1), Signal(dw + 1)
        self.comb += [
            If(odd & self.sink.de,
                cb_sum.eq(prev.c0 + self.sink.c0 + 1),
                cr_sum.eq(prev.c2 + self.sink.c2 + 1),
            ).Else(  # unpaired last pixel of an odd-length line
                cb_sum.eq(Cat(0, prev.c0)),
                cr_sum.eq(Cat(0, prev.c2)),
            ),
            cb_mean.eq(cb_sum[1:]),
            cr_mean.eq(cr_sum[1:]),
        ]
        cr_hold = Signal(dw)
        self.sync += [
            self.source.de.eq(prev.de),
            self.source.c1.eq(prev.c1),
            self.source.c0.eq(0),
            If(odd,  # prev is even
                self.source.c2.eq(cb_mean),
                cr_hold.eq(cr_mean),
            ).Else(
                self.source.c2.eq(cr_hold),
            ),
        ]


class Wire422ToYCbCr444(LiteXModule):
    """sink: 4:2:2 wire words; source: c0 = Cb, c1 = Y, c2 = Cr per pixel."""
    latency = 1

    def __init__(self, dw=8):
        self.sink   = Record(wire_layout(dw))
        self.source = Record(wire_layout(dw))

        # # #

        odd = Signal()
        self.sync += If(~self.sink.de, odd.eq(0)).Else(odd.eq(~odd))

        prev = Record(wire_layout(dw))
        self.sync += prev.raw_bits().eq(self.sink.raw_bits())

        cb_hold = Signal(dw)
        self.sync += [
            self.source.de.eq(prev.de),
            self.source.c1.eq(prev.c1),
            If(odd,  # prev is even: its Cb, the odd pixel's Cr arriving now
                self.source.c0.eq(prev.c2),
                self.source.c2.eq(Mux(self.sink.de, self.sink.c2, 0)),  # unpaired last pixel: no Cr
                cb_hold.eq(prev.c2),
            ).Else(  # prev is odd: the pair's Cb held, its own Cr
                self.source.c0.eq(cb_hold),
                self.source.c2.eq(prev.c2),
            ),
        ]


# Python reference models (one line of pixels as (Cb, Y, Cr) tuples).

def pack422(pixels):
    """Wire words (c0, c1, c2) for a line of (Cb, Y, Cr) pixels."""
    out = []
    for i in range(0, len(pixels), 2):
        pair = pixels[i:i + 2]
        cb = (sum(p[0] for p in pair) + len(pair) - 1) // len(pair)
        cr = (sum(p[2] for p in pair) + len(pair) - 1) // len(pair)
        out.append((0, pair[0][1], cb))
        if len(pair) == 2:
            out.append((0, pair[1][1], cr))
    return out


def unpack422(words):
    """(Cb, Y, Cr) pixels for a line of wire words."""
    out = []
    for i in range(0, len(words), 2):
        pair = words[i:i + 2]
        cb = pair[0][2]
        cr = pair[1][2] if len(pair) == 2 else 0
        for w in pair:
            out.append((cb, w[1], cr))
    return out
