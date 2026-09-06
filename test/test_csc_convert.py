#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""PixelFormatConverter against the Python model for every format pair."""

import random
import unittest

from migen import *

from litevideo.csc.convert import *
from litevideo.csc import colorimetry as cm


def make_stream(seed, lengths, gap=4):
    random.seed(seed)
    stream, per_line = [], []
    for k, n in enumerate(lengths):
        px = [tuple(random.randint(0, 255) for _ in range(3)) for _ in range(n)]
        per_line.append(px)
        # hsync during the gap, vsync on the first line's gap
        stream += [(0, 1, k == 0, (0, 0, 0))] * gap + [(1, 0, 0, p) for p in px]
    stream += [(0, 1, 0, (0, 0, 0))] * gap
    return stream, per_line


def run(dut, stream, ctrl):
    out, syncs = [], []

    def gen():
        yield dut.fmt_in.eq(ctrl[0]); yield dut.fmt_out.eq(ctrl[1]); yield dut.colorimetry.eq(ctrl[2])
        yield dut.rgb_limited.eq(ctrl[3]); yield dut.ycc_limited.eq(ctrl[4])
        for de, hs, vs, px in stream + [(0, 1, 0, (0, 0, 0))] * dut.latency:
            yield dut.sink.de.eq(de); yield dut.sink.hsync.eq(hs); yield dut.sink.vsync.eq(vs)
            yield dut.sink.b.eq(px[0]); yield dut.sink.g.eq(px[1]); yield dut.sink.r.eq(px[2])
            yield
            syncs.append(((yield dut.source.de), (yield dut.source.hsync), (yield dut.source.vsync)))
            if (yield dut.source.de):
                out.append(((yield dut.source.b), (yield dut.source.g), (yield dut.source.r)))
    run_simulation(dut, gen())
    return out, syncs


class TestPixelFormatConverter(unittest.TestCase):
    LENGTHS = [6, 5, 8]

    def check(self, fmt_in, fmt_out, colorimetry=2, rgb_limited=0, ycc_limited=1):
        stream, per_line = make_stream(fmt_in * 3 + fmt_out, self.LENGTHS)
        dut = PixelFormatConverter()
        out, syncs = run(dut, stream, (fmt_in, fmt_out, colorimetry, rgb_limited, ycc_limited))
        expected = sum((convert_line(px, fmt_in, fmt_out, colorimetry, rgb_limited, ycc_limited) for px in per_line), [])
        self.assertEqual(out, expected, (fmt_in, fmt_out))
        # syncs and DE are delayed by exactly the latency
        for k, (de, hs, vs, _) in enumerate(stream):
            self.assertEqual(syncs[k + dut.latency], (de, hs, vs), k)

    def test_all_pairs(self):
        for fi in (PixelFormat.RGB, PixelFormat.YCBCR422, PixelFormat.YCBCR444):
            for fo in (PixelFormat.RGB, PixelFormat.YCBCR422, PixelFormat.YCBCR444):
                self.check(fi, fo)

    def test_ranges_and_colorimetry(self):
        for col in (1, 2):
            for rl in (0, 1):
                for yl in (0, 1):
                    self.check(PixelFormat.RGB, PixelFormat.YCBCR444, col, rl, yl)
                    self.check(PixelFormat.YCBCR422, PixelFormat.RGB, col, rl, yl)

    def test_identity_is_exact(self):
        stream, per_line = make_stream(9, [10])
        out, _ = run(PixelFormatConverter(), stream, (0, 0, 2, 0, 1))
        self.assertEqual(out, per_line[0])

    def test_wire_order(self):
        # RGB (255,0,0) on the wire is r=255 (channel 2); BT.709 full RGB -> limited YCbCr gives
        # Y=63 on channel 1 (g), Cb=102 on channel 0 (b), Cr=240 on channel 2 (r).
        stream = [(0, 1, 0, (0, 0, 0))] * 3 + [(1, 0, 0, (0, 0, 255))] + [(0, 1, 0, (0, 0, 0))] * 3
        out, _ = run(PixelFormatConverter(), stream, (PixelFormat.RGB, PixelFormat.YCBCR444, 2, 0, 1))
        self.assertEqual(out, [(102, 63, 240)])


if __name__ == "__main__":
    unittest.main()
