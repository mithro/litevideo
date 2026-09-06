#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Period decoder edge cases: guard band spoofing by pixel values, sync edges
inside islands, minimum spacing, and stream validity gaps."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.period import HDMIPeriodDecoder

from test.test_hdmi_period import run_lines


class TestPeriodDecoderEdges(unittest.TestCase):
    def test_video_guard_band_values_as_pixels(self):
        # (B,G,R) = (0xAB,0x55,0xAB) TMDS-encodes to the video guard band characters
        # at any running disparity; the decoder must count the guard band, not match it.
        pixels = [(0xAB, 0x55, 0xAB)] * 3 + [(i, 2 * i, 3 * i) for i in range(21)]
        toks, periods = model.line_tokens(hactive=24, hblank=40, pixels=pixels)
        self.assertEqual(toks[0], tuple(video_gb_tokens))       # the spoof really happens
        out = run_lines([toks, toks])
        got = [(o["r"], o["g"], o["b"]) for o in out if o["de"]]
        self.assertEqual(got, pixels)
        self.assertEqual([o["period"] for o in out], periods)

    def test_sync_edge_inside_island(self):
        # HSYNC pulse of 16 characters starting 8 into blanking: it ends inside the
        # island that starts 12 characters into blanking. Every character must carry
        # the live HSYNC (HDMI 1.3 §5.2.3.1).
        p = model.Packet.null()
        toks, periods, syncs = model.line_tokens(hactive=16, hblank=80, packets=[p],
                                                 hsync_start=8, hsync_len=16, return_syncs=True)
        out = run_lines([toks, toks])
        self.assertEqual([o["period"] for o in out], periods)
        self.assertEqual([o["hsync"] for o in out], [h for h, v in syncs])
        self.assertEqual([o["vsync"] for o in out], [v for h, v in syncs])

    def test_minimum_blanking(self):
        # 12 control + island(44) + 4 control + 8 preamble + 2 guard band = 70: the
        # tightest legal layout still decodes with no error.
        p = model.Packet.null()
        toks, periods = model.line_tokens(hactive=16, hblank=70, packets=[p], hsync_start=2, hsync_len=4)
        out = run_lines([toks, toks])
        self.assertEqual([o["period"] for o in out], periods)
        self.assertFalse(any(o["error"] for o in out))
        self.assertEqual(sum(o["island"] for o in out), 32)

    def test_valid_gap_discards_island(self):
        p = model.Packet.null()
        toks, periods = model.line_tokens(hactive=16, hblank=80, packets=[p], hsync_start=4, hsync_len=4)
        dut = HDMIPeriodDecoder()
        out = []
        gap_at = 16 + 12 + 8 + 2 + 10     # 10 characters into the packet

        def gen():
            for n, t in enumerate(toks + toks + [model.control_chars(0, 0)] * 3):
                yield dut.sink.c0.eq(t[0]); yield dut.sink.c1.eq(t[1]); yield dut.sink.c2.eq(t[2])
                yield dut.sink.valid.eq(0 if n == gap_at else 1)
                yield
                out.append({"period": (yield dut.period), "island": (yield dut.island_active),
                            "first": (yield dut.island_first), "valid": (yield dut.source.valid)})

        run_simulation(dut, gen())
        L = len(toks)
        first_line = out[2:2 + L]
        second_line = out[2 + L:2 + 2 * L]
        # First line: the island is cut at the gap and never resumes.
        self.assertEqual(sum(o["island"] for o in first_line), 10)
        self.assertEqual(first_line[gap_at]["valid"], 0)
        self.assertEqual(first_line[gap_at]["period"], Period.CONTROL)
        # Second line: a full island again, with exactly one 'first'.
        self.assertEqual(sum(o["island"] for o in second_line), 32)
        self.assertEqual(sum(o["first"] for o in second_line), 1)
        self.assertEqual([o["period"] for o in second_line], periods)
