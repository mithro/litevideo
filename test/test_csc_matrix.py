#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""CSCMatrix against the colorimetry reference models."""

import random
import unittest

from migen import *

from litevideo.csc.colorimetry import *
from litevideo.csc.matrix import CSCMatrix


def run_pixels(dut, pixels, ce_pattern=None):
    out = []

    def gen():
        n = len(pixels)
        fed = cycle = 0
        while len(out) < n:
            ce = 1 if ce_pattern is None else ce_pattern(cycle)
            cycle += 1
            yield dut.ce.eq(ce)
            if fed < n:
                px = pixels[fed]
            else:
                px = (0, 0, 0)
            yield dut.sink.c0.eq(px[0]); yield dut.sink.c1.eq(px[1]); yield dut.sink.c2.eq(px[2])
            yield
            if ce:
                fed += 1
                if fed > dut.latency:
                    out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
    run_simulation(dut, gen())
    return out


class TestCSCMatrix(unittest.TestCase):
    def check(self, matrix, cw=12, n=400, ce_pattern=None):
        random.seed(hash((matrix.offsets[0], cw)) & 0xFFFF)
        pixels = [tuple(random.randint(0, 255) for _ in range(3)) for _ in range(n)]
        pixels[:4] = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255)]
        dut = CSCMatrix(dw=8, cw=cw, matrix=matrix)
        out = run_pixels(dut, pixels, ce_pattern)
        self.assertEqual(len(out), n)
        q = quantize(matrix, cw)
        for px, hw in zip(pixels, out):
            self.assertEqual(hw, apply_quantized(q, cw, px), px)             # bit-exact with the integer model
            ref = apply(matrix, px)
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(hw, ref)), (px, hw, ref))

    def test_bt709_rgb_to_ycbcr(self):
        self.check(rgb2ycbcr_matrix(BT709, FULL, LIMITED))

    def test_bt601_ycbcr_to_rgb(self):
        self.check(ycbcr2rgb_matrix(BT601, LIMITED, FULL))

    def test_bt601_full_to_full_and_back(self):
        self.check(rgb2ycbcr_matrix(BT601, FULL, FULL))
        self.check(ycbcr2rgb_matrix(BT601, FULL, FULL))

    def test_limited_rgb_clamps(self):
        # limited -> limited: output range is 16..235/240 and inputs outside the nominal range are clamped
        self.check(ycbcr2rgb_matrix(BT709, LIMITED, LIMITED))

    def test_ce_stalls(self):
        self.check(rgb2ycbcr_matrix(BT709, FULL, LIMITED), n=100, ce_pattern=lambda i: (i * 7) % 3 != 0)

    def test_runtime_coefficients(self):
        # No matrix given: drive the coefficient inputs, switch mid-stream.
        dut = CSCMatrix(dw=8, cw=12)
        mats = [quantize(rgb2ycbcr_matrix(BT709, FULL, LIMITED), 12), quantize(ycbcr2rgb_matrix(BT601, LIMITED, FULL), 12)]
        random.seed(5)
        pixels = [tuple(random.randint(0, 255) for _ in range(3)) for _ in range(60)]
        out = []

        def gen():
            for k, px in enumerate(pixels + [(0, 0, 0)] * dut.latency):
                q = mats[0 if k < 30 else 1]
                for i in range(3):
                    yield dut.offsets[i].eq(q.offsets[i]); yield dut.mins[i].eq(q.mins[i]); yield dut.maxs[i].eq(q.maxs[i])
                    for j in range(3):
                        yield dut.coefs[i][j].eq(q.m[i][j])
                yield dut.sink.c0.eq(px[0]); yield dut.sink.c1.eq(px[1]); yield dut.sink.c2.eq(px[2])
                yield
                if k >= dut.latency:
                    out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
        run_simulation(dut, gen())
        # Coefficients are sampled at different pipeline stages, so only check pixels well away from the switch.
        for k, (px, hw) in enumerate(zip(pixels, out)):
            if 26 <= k < 34:
                continue
            self.assertEqual(hw, apply_quantized(mats[0 if k < 30 else 1], 12, px), k)


if __name__ == "__main__":
    unittest.main()
