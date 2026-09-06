#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Generic 3x3 fixed-point colour matrix.

    out[i] = clamp((sum_j coef[i][j] * in[j] + offset[i] + 2**(cw-1)) >> cw, min[i], max[i])

Coefficients have ``cw`` fractional bits and are signed with two integer
bits (magnitudes up to 4: the largest colour matrix entry, limited YCbCr to
full RGB for BT.601, is 1.402 * 255/224 = 1.60). Offsets are pre-scaled by
2**cw. With ``matrix`` given (a ``colorimetry.Matrix``) they are constants
and synthesis folds the multipliers; with ``matrix=None`` they are inputs
(``coefs``, ``offsets``, ``mins``, ``maxs``) so a wrapper can switch colour
spaces at run time (nine ``(dw+1) x (cw+3)`` signed multipliers, one DSP48
each on 7-series for dw=8, cw=12).

Latency is 4 clocks; ``ce`` gates the whole pipeline. Bit-exact with
``colorimetry.apply_quantized``.
"""

from migen import *

from litex.gen import *

from litevideo.csc.colorimetry import quantize


def matrix_layout(dw):
    return [("c0", dw), ("c1", dw), ("c2", dw)]


class CSCMatrix(LiteXModule):
    latency = 4

    def __init__(self, dw=8, cw=12, matrix=None):
        self.dw, self.cw = dw, cw
        self.sink   = Record(matrix_layout(dw))
        self.source = Record(matrix_layout(dw))
        self.ce     = Signal(reset=1)

        coef_w   = cw + 3           # signed, 2 integer bits
        offset_w = cw + dw + 3      # signed, |offset| < 2**(dw+2) codes
        self.coefs   = [[Signal((coef_w, True), name=f"coef{i}{j}") for j in range(3)] for i in range(3)]
        self.offsets = [Signal((offset_w, True), name=f"offset{i}") for i in range(3)]
        self.mins    = [Signal(dw, name=f"min{i}") for i in range(3)]
        self.maxs    = [Signal(dw, name=f"max{i}", reset=2**dw - 1) for i in range(3)]

        # # #

        if matrix is not None:
            q = quantize(matrix, cw)
            for i in range(3):
                self.comb += self.offsets[i].eq(q.offsets[i]), self.mins[i].eq(q.mins[i]), self.maxs[i].eq(q.maxs[i])
                for j in range(3):
                    assert abs(q.m[i][j]) < 2**(coef_w - 1), "coefficient out of range"
                    self.comb += self.coefs[i][j].eq(q.m[i][j])

        ins = [self.sink.c0, self.sink.c1, self.sink.c2]
        outs = [self.source.c0, self.source.c1, self.source.c2]

        # stage 1: register inputs (as signed so the multiplier sees the sign of the coefficient only)
        in_r = [Signal((dw + 1, True), name=f"in_r{j}") for j in range(3)]
        self.sync += If(self.ce, *[in_r[j].eq(ins[j]) for j in range(3)])

        # stage 2: products
        prod_w = dw + 1 + coef_w
        prods = [[Signal((prod_w, True), name=f"prod{i}{j}") for j in range(3)] for i in range(3)]
        self.sync += If(self.ce, *[prods[i][j].eq(in_r[j] * self.coefs[i][j]) for i in range(3) for j in range(3)])

        # stage 3: sum, offset, rounding
        acc_w = prod_w + 2
        accs = [Signal((acc_w, True), name=f"acc{i}") for i in range(3)]
        self.sync += If(self.ce, *[accs[i].eq(prods[i][0] + prods[i][1] + prods[i][2] + self.offsets[i] + (1 << (cw - 1)))
                                   for i in range(3)])

        # stage 4: shift and saturate
        for i in range(3):
            shifted = Signal((acc_w - cw, True))
            self.comb += shifted.eq(accs[i][cw:])
            self.sync += If(self.ce,
                If(shifted > self.maxs[i],
                    outs[i].eq(self.maxs[i])
                ).Elif(shifted < self.mins[i],
                    outs[i].eq(self.mins[i])
                ).Else(
                    outs[i].eq(shifted)
                )
            )
