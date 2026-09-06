#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Colour-space conversion tests: the Migen cores against the Python models in
``test/csc_model.py`` on a 32x32 crop of the classic test image."""

import os
import random
import unittest

from migen import *

from litevideo.csc.rgb2ycbcr import rgb2ycbcr_coefs, RGB2YCbCr
from litevideo.csc.ycbcr2rgb import ycbcr2rgb_coefs, YCbCr2RGB
from litevideo.csc.ycbcr444to422 import YCbCr444to422
from litevideo.csc.ycbcr422to444 import YCbCr422to444

from test.common import stream_inserter, stream_collector
from test.csc_model import RAWImage

LENA = os.path.join(os.path.dirname(__file__), "data", "lena.png")
SIZE = 32


def max_abs_diff(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


class TestRGB2YCbCr(unittest.TestCase):
    def test_against_model(self):
        image = RAWImage(rgb2ycbcr_coefs(8), LENA, SIZE)
        ref = RAWImage(rgb2ycbcr_coefs(8), LENA, SIZE)
        ref.rgb2ycbcr_model()

        dut = RGB2YCbCr()
        beats = [{"r": r, "g": g, "b": b} for r, g, b in zip(image.r, image.g, image.b)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=20),
            stream_collector(dut.source, ["y", "cb", "cr"], out, ready_rand=20),
        ])
        self.assertEqual(len(out), len(beats))
        for name in ("y", "cb", "cr"):
            diff = max_abs_diff([o[name] for o in out], getattr(ref, name))
            # 8-bit fixed-point coefficients: the datapath rounds differently
            # from the float model by at most a couple of LSB (measured: 1).
            self.assertLessEqual(diff, 3, f"{name}: max |hw - model| = {diff}")


class TestYCbCr2RGB(unittest.TestCase):
    def test_against_model(self):
        image = RAWImage(ycbcr2rgb_coefs(8), LENA, SIZE)
        image.rgb2ycbcr()                      # Wikipedia reference to get YCbCr inputs
        ref = RAWImage(ycbcr2rgb_coefs(8), LENA, SIZE)
        ref.rgb2ycbcr()
        ref.ycbcr2rgb_model()

        dut = YCbCr2RGB()
        beats = [{"y": y, "cb": cb, "cr": cr} for y, cb, cr in zip(image.y, image.cb, image.cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=20),
            stream_collector(dut.source, ["r", "g", "b"], out, ready_rand=20),
        ])
        self.assertEqual(len(out), len(beats))
        for name in ("r", "g", "b"):
            hw = [o[name] for o in out]
            model = [min(255, max(0, v)) for v in getattr(ref, name)]
            diff = max_abs_diff(hw, model)
            self.assertLessEqual(diff, 3, f"{name}: max |hw - model| = {diff}")


class TestYCbCr422to444(unittest.TestCase):
    def test_upsampling(self):
        prng = random.Random(42)
        y = [prng.randrange(256) for _ in range(32)]
        cb_cr = [prng.randrange(20, 200) for _ in range(32)]
        exp_cb = [cb_cr[2 * (i // 2)] for i in range(32)]
        exp_cr = [cb_cr[2 * (i // 2) + 1] for i in range(32)]

        dut = YCbCr422to444()
        beats = [{"y": yy, "cb_cr": c} for yy, c in zip(y, cb_cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=30),
            stream_collector(dut.source, ["y", "cb", "cr"], out, ready_rand=30),
        ])
        self.assertEqual([o["y"] for o in out], y)
        self.assertEqual([o["cb"] for o in out], exp_cb)
        self.assertEqual([o["cr"] for o in out], exp_cr)


class TestYCbCrResampling(unittest.TestCase):
    """444 -> 422 -> 444: Y survives exactly and chroma comes back in equal
    pairs. Which two input pixels each pair averages depends on the
    ``YCbCr444to422Datapath.first`` alignment strobe, which only
    ``FrameExtraction`` drives (litevideo/input/analysis.py); this port of the
    old bench therefore checks pairing, not the mean. Phase 4 (pixel formats)
    reworks the 4:2:2 path and its tests."""
    def test_chain(self):
        prng = random.Random(7)
        n = 64
        y = [prng.randrange(256) for _ in range(n)]
        cb = [prng.randrange(256) for _ in range(n)]
        cr = [prng.randrange(256) for _ in range(n)]

        class DUT(Module):
            def __init__(self):
                self.submodules.down = YCbCr444to422()
                self.submodules.up = YCbCr422to444()
                self.comb += self.down.source.connect(self.up.sink)

        dut = DUT()
        beats = [{"y": a, "cb": b, "cr": c} for a, b, c in zip(y, cb, cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.down.sink, beats),
            stream_collector(dut.up.source, ["y", "cb", "cr"], out),
        ])
        self.assertEqual(len(out), n)
        self.assertEqual([o["y"] for o in out], y)
        for i in range(0, n, 2):
            for name in ("cb", "cr"):
                self.assertEqual(out[i][name], out[i + 1][name])
