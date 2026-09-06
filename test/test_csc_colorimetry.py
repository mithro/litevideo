#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""The colorimetry model against hand-computed vectors from the standards."""

import random
import unittest

from litevideo.csc.colorimetry import *


class TestMatrices(unittest.TestCase):
    def test_bt709_full_rgb_to_limited(self):
        m = rgb2ycbcr_matrix(BT709, FULL, LIMITED)
        # BT.709-6 item 3.4: white -> 235, black -> 16, colour difference at 128.
        self.assertEqual(apply(m, (255, 255, 255)), (235, 128, 128))
        self.assertEqual(apply(m, (0, 0, 0)), (16, 128, 128))
        # Red: E'Y = 0.2126 -> 219*0.2126+16 = 62.56 -> 63; E'CR = 0.7874/1.5748 = 0.5 -> 240;
        # E'CB = -0.2126/1.8556 = -0.11457 -> 224*-0.11457+128 = 102.34 -> 102.
        self.assertEqual(apply(m, (255, 0, 0)), (63, 102, 240))
        # Blue: E'Y = 0.0722 -> 31.8 -> 32; E'CB = 0.5 -> 240; E'CR = -0.0722/1.5748 = -0.04585 -> 117.7 -> 118.
        self.assertEqual(apply(m, (0, 0, 255)), (32, 240, 118))

    def test_bt601_full_rgb_to_full_ycc_is_jfif(self):
        m = rgb2ycbcr_matrix(BT601, FULL, FULL)
        # JFIF: Y = 0.299R + 0.587G + 0.114B, Cb = -0.1687R - 0.3313G + 0.5B + 128, Cr = 0.5R - 0.4187G - 0.0813B + 128.
        self.assertAlmostEqual(m.m[0][0], 0.299, places=6)
        self.assertAlmostEqual(m.m[1][0], -0.299 / 1.772, places=6)   # -0.16874
        self.assertAlmostEqual(m.m[1][2], 0.5, places=6)
        self.assertAlmostEqual(m.m[2][0], 0.5, places=6)
        self.assertAlmostEqual(m.m[2][1], -0.587 / 1.402, places=6)   # -0.41869
        self.assertEqual(apply(m, (255, 0, 0)), (76, 85, 255))       # Cr = 255.5 clamps to 255
        self.assertEqual(apply(m, (255, 255, 255)), (255, 128, 128))

    def test_bt601_limited_rgb_offset_cancels(self):
        # BT.601-7 §2.5.4: with quantized limited RGB inputs, Y = 0.299 R_D + 0.587 G_D + 0.114 B_D directly.
        m = rgb2ycbcr_matrix(BT601, LIMITED, LIMITED)
        self.assertAlmostEqual(m.m[0][0], 0.299, places=9)
        self.assertAlmostEqual(m.offsets[0], 0.0, places=9)
        self.assertAlmostEqual(m.m[1][2], 224 / 219 * 0.886 / 1.772, places=9)
        self.assertEqual(apply(m, (235, 235, 235)), (235, 128, 128))
        self.assertEqual(apply(m, (16, 16, 16)), (16, 128, 128))

    def test_inverse_round_trip(self):
        random.seed(1)
        for col in (BT601, BT709):
            for rgb_range in (FULL, LIMITED):
                for ycc_range in (FULL, LIMITED):
                    fwd = rgb2ycbcr_matrix(col, rgb_range, ycc_range)
                    inv = ycbcr2rgb_matrix(col, ycc_range, rgb_range)
                    # Matrices are exact inverses.
                    for i in range(3):
                        for j in range(3):
                            prod = sum(inv.m[i][k] * fwd.m[k][j] for k in range(3))
                            self.assertAlmostEqual(prod, 1.0 if i == j else 0.0, places=9)
                    # Quantized round trip: the chroma quantization step loses up to ~1 code
                    # in RGB, the luma another, so allow 2 either side, and clamping at the edges.
                    for _ in range(500):
                        px = tuple(random.randint(rgb_range.ymin, rgb_range.ymax) for _ in range(3))
                        back = apply(inv, apply(fwd, px))
                        for a, b in zip(px, back):
                            self.assertLessEqual(abs(a - b), 2, (col.name, rgb_range.name, ycc_range.name, px, back))

    def test_quantized_matches_float_within_one(self):
        random.seed(2)
        for cw in (10, 12):
            for col in (BT601, BT709):
                for mat in (rgb2ycbcr_matrix(col, FULL, LIMITED), ycbcr2rgb_matrix(col, LIMITED, FULL),
                            rgb2ycbcr_matrix(col, LIMITED, FULL), ycbcr2rgb_matrix(col, FULL, LIMITED)):
                    q = quantize(mat, cw)
                    for _ in range(300):
                        px = tuple(random.randint(0, 255) for _ in range(3))
                        f, h = apply(mat, px), apply_quantized(q, cw, px)
                        for a, b in zip(f, h):
                            self.assertLessEqual(abs(a - b), 1, (cw, col.name, px, f, h))


if __name__ == "__main__":
    unittest.main()
