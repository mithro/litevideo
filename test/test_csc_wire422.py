#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""4:2:2 wire packing and unpacking against the Python models."""

import random
import unittest

from migen import *

from litevideo.csc.wire422 import *


def lines(seed, lengths, gap=5):
    """A DE-annotated pixel stream: list of (de, (c0, c1, c2)) for lines of the given lengths."""
    random.seed(seed)
    stream, per_line = [], []
    for n in lengths:
        px = [tuple(random.randint(0, 255) for _ in range(3)) for _ in range(n)]
        per_line.append(px)
        stream += [(0, (0, 0, 0))] * gap + [(1, p) for p in px]
    stream += [(0, (0, 0, 0))] * gap
    return stream, per_line


def run(dut, stream):
    out = []

    def gen():
        for de, px in stream + [(0, (0, 0, 0))] * dut.latency:
            yield dut.sink.de.eq(de)
            yield dut.sink.c0.eq(px[0]); yield dut.sink.c1.eq(px[1]); yield dut.sink.c2.eq(px[2])
            yield
            if (yield dut.source.de):
                out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
    run_simulation(dut, gen())
    return out


class TestWire422(unittest.TestCase):
    LENGTHS = [8, 7, 2, 1, 16]

    def test_pack(self):
        stream, per_line = lines(1, self.LENGTHS)
        out = run(YCbCr444ToWire422(), stream)
        expected = sum((pack422(px) for px in per_line), [])
        self.assertEqual(out, expected)

    def test_unpack(self):
        stream, per_line = lines(2, self.LENGTHS)
        out = run(Wire422ToYCbCr444(), stream)
        expected = sum((unpack422(px) for px in per_line), [])
        self.assertEqual(out, expected)

    def test_round_trip_chroma_is_pair_mean(self):
        stream, per_line = lines(3, [12])
        words = run(YCbCr444ToWire422(), stream)
        back = run(Wire422ToYCbCr444(), [(0, (0, 0, 0))] * 3 + [(1, w) for w in words] + [(0, (0, 0, 0))] * 3)
        px = per_line[0]
        self.assertEqual([p[1] for p in back], [p[1] for p in px])          # luma exact
        for i in range(0, 12, 2):
            cb = (px[i][0] + px[i + 1][0] + 1) // 2
            cr = (px[i][2] + px[i + 1][2] + 1) // 2
            self.assertEqual(back[i], (cb, px[i][1], cr))
            self.assertEqual(back[i + 1], (cb, px[i + 1][1], cr))

    def test_models_agree_with_figure_6_2(self):
        # Pixel 0 carries Cb on channel 2, pixel 1 carries Cr; luma on channel 1; channel 0 zero for 8-bit.
        self.assertEqual(pack422([(10, 20, 30), (12, 21, 34)]), [(0, 20, 11), (0, 21, 32)])
        self.assertEqual(unpack422([(0, 20, 11), (0, 21, 32)]), [(11, 20, 32), (11, 21, 32)])


if __name__ == "__main__":
    unittest.main()
