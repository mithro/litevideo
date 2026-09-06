#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Pixel format converter over ``video_data_layout`` with run-time selection.

The three 8-bit channels of a LiteVideo stream carry whatever the AVI
InfoFrame declares, in the HDMI wire order (HDMI 1.3 §6.5.1): ``r`` is
channel 2, ``g`` channel 1, ``b`` channel 0, so RGB is (R, G, B) (Figure
6-1), YCbCr 4:4:4 is (Cr, Y, Cb) (Figure 6-3) and YCbCr 4:2:2 is the Figure
6-2 packing (``litevideo.csc.wire422``).

``PixelFormatConverter`` has a fixed pipeline (latency 8: 2 + 4 + 2):

    sink ─► [Wire422ToYCbCr444 | delay] ─► CSCMatrix(run-time) ─► [YCbCr444ToWire422 | delay] ─► source

and control inputs coded like the AVI InfoFrame (CEA-861-D Tables 8, 9, 11
and CEA-861-E's YQ): ``fmt_in``/``fmt_out`` (``PixelFormat``: 0 RGB, 1 YCbCr
4:2:2, 2 YCbCr 4:4:4), ``colorimetry`` (1 BT.601, 2 BT.709; 0 and 3 fall
back to BT.709), ``rgb_limited`` and ``ycc_limited`` quantization ranges.
The matrix coefficients come from a small constant table indexed by
(direction, colorimetry, ranges); the controls are quasi-static (change
them during blanking). DE/HSYNC/VSYNC ride along the pipeline.
"""

from migen import *

from litex.gen import *
from litex.soc.cores.video import video_data_layout

from litevideo.csc import colorimetry as cm
from litevideo.csc.matrix import CSCMatrix
from litevideo.csc.wire422 import YCbCr444ToWire422, Wire422ToYCbCr444, wire_layout, pack422, unpack422


class PixelFormat:
    RGB      = 0   # AVI Y1:Y0 = 00
    YCBCR422 = 1   # 01
    YCBCR444 = 2   # 10


_RGB_ORDER = [2, 1, 0]   # wire (c0, c1, c2) = (B, G, R) -> colorimetry (R, G, B) index
_YCC_ORDER = [1, 0, 2]   # wire (c0, c1, c2) = (Cb, Y, Cr) -> colorimetry (Y, Cb, Cr) index


def wire_matrix(matrix, in_order, out_order):
    """Permute a colorimetry matrix so it acts on wire-ordered channels."""
    return cm.Matrix([[matrix.m[out_order[i]][in_order[j]] for j in range(3)] for i in range(3)],
                     [matrix.offsets[out_order[i]] for i in range(3)],
                     [matrix.mins[out_order[i]] for i in range(3)],
                     [matrix.maxs[out_order[i]] for i in range(3)])


def select_matrix(fmt_in, fmt_out, colorimetry, rgb_limited, ycc_limited):
    """The wire-order matrix the converter applies for these controls."""
    col = cm.BT601 if colorimetry == 1 else cm.BT709
    rgb_range = cm.LIMITED if rgb_limited else cm.FULL
    ycc_range = cm.LIMITED if ycc_limited else cm.FULL
    in_rgb, out_rgb = fmt_in == PixelFormat.RGB, fmt_out == PixelFormat.RGB
    if in_rgb and not out_rgb:
        return wire_matrix(cm.rgb2ycbcr_matrix(col, rgb_range, ycc_range), _RGB_ORDER, _YCC_ORDER)
    if out_rgb and not in_rgb:
        return wire_matrix(cm.ycbcr2rgb_matrix(col, ycc_range, rgb_range), _YCC_ORDER, _RGB_ORDER)
    return cm.identity_matrix()


def convert_line(pixels, fmt_in, fmt_out, colorimetry, rgb_limited, ycc_limited, cw=12):
    """Reference model for one active line of wire-order (c0, c1, c2) pixels."""
    q = cm.quantize(select_matrix(fmt_in, fmt_out, colorimetry, rgb_limited, ycc_limited), cw)
    if fmt_in == PixelFormat.YCBCR422:
        pixels = unpack422(pixels)
    pixels = [cm.apply_quantized(q, cw, p) for p in pixels]
    if fmt_out == PixelFormat.YCBCR422:
        pixels = pack422(pixels)
    return pixels


class _Delay(LiteXModule):
    """Register chain with the wire layout: the bypass of a 4:2:2 stage, same latency."""
    def __init__(self, dw, latency):
        self.sink   = Record(wire_layout(dw))
        self.source = Record(wire_layout(dw))
        regs = [self.sink] + [Record(wire_layout(dw)) for _ in range(latency - 1)] + [self.source]
        self.sync += [b.raw_bits().eq(a.raw_bits()) for a, b in zip(regs, regs[1:])]


class PixelFormatConverter(LiteXModule):
    latency = Wire422ToYCbCr444.latency + CSCMatrix.latency + YCbCr444ToWire422.latency

    def __init__(self, dw=8, cw=12):
        self.sink   = Record(video_data_layout)
        self.source = Record(video_data_layout)
        self.fmt_in      = Signal(2)
        self.fmt_out     = Signal(2)
        self.colorimetry = Signal(2)
        self.rgb_limited = Signal()
        self.ycc_limited = Signal()

        # # #

        # Stage A: 4:2:2 unpack or delay.
        self.unpack = unpack = Wire422ToYCbCr444(dw)
        self.dly_a  = dly_a  = _Delay(dw, unpack.latency)
        for m in (unpack, dly_a):
            self.comb += [m.sink.de.eq(self.sink.de), m.sink.c0.eq(self.sink.b), m.sink.c1.eq(self.sink.g), m.sink.c2.eq(self.sink.r)]
        a = Record(wire_layout(dw))
        self.comb += If(self.fmt_in == PixelFormat.YCBCR422, a.raw_bits().eq(unpack.source.raw_bits())
                        ).Else(a.raw_bits().eq(dly_a.source.raw_bits()))

        # Stage B: matrix with run-time coefficients from the table.
        self.matrix = matrix = CSCMatrix(dw, cw)
        self.comb += [matrix.sink.c0.eq(a.c0), matrix.sink.c1.eq(a.c1), matrix.sink.c2.eq(a.c2)]
        de_b = Signal(matrix.latency)
        self.sync += de_b.eq(Cat(a.de, de_b))   # DE alongside the matrix

        sel = Signal(5)   # direction[4:3] (0 none, 1 rgb->ycc, 2 ycc->rgb), colorimetry[2], rgb_limited[1], ycc_limited[0]
        in_rgb, out_rgb = self.fmt_in == PixelFormat.RGB, self.fmt_out == PixelFormat.RGB
        self.comb += sel.eq(Cat(self.ycc_limited, self.rgb_limited, self.colorimetry == 1,
                                Mux(in_rgb & ~out_rgb, 1, Mux(out_rgb & ~in_rgb, 2, 0))))
        cases = {}
        for direction in range(3):
            for col in range(2):
                for rgb_l in range(2):
                    for ycc_l in range(2):
                        fmt_in, fmt_out = {0: (0, 0), 1: (0, 2), 2: (2, 0)}[direction]
                        q = cm.quantize(select_matrix(fmt_in, fmt_out, 1 if col else 2, rgb_l, ycc_l), cw)
                        stmts = []
                        for i in range(3):
                            stmts += [matrix.offsets[i].eq(q.offsets[i]), matrix.mins[i].eq(q.mins[i]), matrix.maxs[i].eq(q.maxs[i])]
                            stmts += [matrix.coefs[i][j].eq(q.m[i][j]) for j in range(3)]
                        cases[(direction << 3) | (col << 2) | (rgb_l << 1) | ycc_l] = stmts
        self.sync += Case(sel, cases)

        # Stage C: 4:2:2 pack or delay.
        self.pack  = pack  = YCbCr444ToWire422(dw)
        self.dly_c = dly_c = _Delay(dw, pack.latency)
        for m in (pack, dly_c):
            self.comb += [m.sink.de.eq(de_b[-1]), m.sink.c0.eq(matrix.source.c0), m.sink.c1.eq(matrix.source.c1), m.sink.c2.eq(matrix.source.c2)]
        c = Record(wire_layout(dw))
        self.comb += If(self.fmt_out == PixelFormat.YCBCR422, c.raw_bits().eq(pack.source.raw_bits())
                        ).Else(c.raw_bits().eq(dly_c.source.raw_bits()))

        # Syncs ride along; DE comes out of the last stage.
        hs, vs = Signal(self.latency), Signal(self.latency)
        self.sync += [hs.eq(Cat(self.sink.hsync, hs)), vs.eq(Cat(self.sink.vsync, vs))]
        self.comb += [
            self.source.de.eq(c.de), self.source.hsync.eq(hs[-1]), self.source.vsync.eq(vs[-1]),
            self.source.b.eq(c.c0), self.source.g.eq(c.c1), self.source.r.eq(c.c2),
        ]
