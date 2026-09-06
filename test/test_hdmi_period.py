#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.period import HDMIPeriodDecoder


def run_lines(lines, dvi_mode=0):
    """Feed concatenated line token lists; return per-character output dicts
    for every line after the first (the first line is a warm-up: the decoder
    resets in CONTROL and only enters VIDEO after a preamble + guard band)."""
    dut = HDMIPeriodDecoder()
    tokens = [t for line in lines for t in line]
    out = []

    def gen():
        yield dut.dvi_mode.eq(dvi_mode)
        for t in tokens + [model.control_chars(0, 0)] * 3:
            yield dut.sink.c0.eq(t[0]); yield dut.sink.c1.eq(t[1]); yield dut.sink.c2.eq(t[2])
            yield dut.sink.valid.eq(1)
            yield
            out.append({
                "period": (yield dut.period), "de": (yield dut.source.de),
                "hsync": (yield dut.source.hsync), "vsync": (yield dut.source.vsync),
                "r": (yield dut.source.r), "g": (yield dut.source.g), "b": (yield dut.source.b),
                "island": (yield dut.island_active), "first": (yield dut.island_first),
                "n0": (yield dut.nibble0), "n1": (yield dut.nibble1), "n2": (yield dut.nibble2),
                "error": (yield dut.error),
            })

    run_simulation(dut, gen())
    # Drop the warm-up line (the first ``len(lines[0])`` characters) and the latency.
    start = dut.latency + len(lines[0])
    return out[start:start + len(tokens) - len(lines[0])]


class TestHDMIPeriodDecoder(unittest.TestCase):
    def test_periods_video_only(self):
        toks, periods = model.line_tokens(hactive=24, hblank=40)
        out = run_lines([toks] * 4)          # 1 warm-up + 3 compared
        self.assertEqual([o["period"] for o in out], periods * 3)
        self.assertEqual([o["de"] for o in out], [1 if p == Period.VIDEO else 0 for p in periods] * 3)

    def test_pixels_and_syncs(self):
        pixels = [(i, 255 - i, (i * 3) & 0xFF) for i in range(24)]
        toks, periods = model.line_tokens(hactive=24, hblank=40, pixels=pixels, hsync_start=4, hsync_len=8)
        out = run_lines([toks, toks])
        got = [(o["r"], o["g"], o["b"]) for o in out if o["de"]]
        self.assertEqual(got, pixels)
        hs = [o["hsync"] for o in out[24:64]]
        self.assertEqual(hs, [1 if 4 <= i < 12 else 0 for i in range(40)])

    def test_island_nibbles(self):
        p = model.Packet([0x82, 0x02, 0x0D], [[0x11 * k + i for i in range(7)] for k in range(4)])
        # blanking: 12 + (8+2+64+2) + 4 + 8 + 2 = 102 minimum
        toks, periods = model.line_tokens(hactive=16, hblank=112, packets=[p, p], hsync_start=4, hsync_len=4)
        out = run_lines([toks] * 3)          # 1 warm-up + 2 compared
        self.assertEqual([o["period"] for o in out], periods * 2)
        chars = model.packet_chars(p) * 2
        island = [o for o in out if o["island"]]
        self.assertEqual(len(island), 128)
        self.assertEqual([o["first"] for o in island[:64]], [1] + [0] * 63)
        for o, (hbit, n1, n2) in zip(island[:64], chars):
            self.assertEqual((o["n0"] >> 2) & 1, hbit)
            self.assertEqual(o["n1"], n1)
            self.assertEqual(o["n2"], n2)
        self.assertFalse(any(o["error"] for o in out))

    def test_dvi_mode(self):
        # DVI mode: DE is "channel 0 is not a control character", so the two
        # video guard band characters (not control tokens) also count as DE.
        toks, periods = model.line_tokens(hactive=24, hblank=40)
        out = run_lines([toks, toks], dvi_mode=1)
        expected = [1 if p in (Period.VIDEO, Period.VIDEO_GUARD) else 0 for p in periods]
        self.assertEqual([o["de"] for o in out], expected)

    def test_island_aborted_by_control(self):
        p = model.Packet.null()
        island = model.island_tokens([p])
        toks = [model.control_chars(0, 0)] * 12 + island[:20] + [model.control_chars(0, 0)] * 12
        out = run_lines([toks, toks])
        self.assertTrue(any(o["error"] for o in out))
        self.assertEqual(out[-1]["period"], Period.CONTROL)
