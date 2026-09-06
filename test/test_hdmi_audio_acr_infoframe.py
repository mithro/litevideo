#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""ACRGenerator and AudioInfoFrameGenerator against the model."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.audio import model as am
from litevideo.hdmi.audio.acr import ACRGenerator
from litevideo.hdmi.audio.infoframe import AudioInfoFrameGenerator


def read_packet(src):
    header = (yield src.header)
    subs = []
    for k in range(4):
        subs.append((yield getattr(src, f"sub{k}")))
    return model.Packet.from_words(header, subs)


class TestACRGenerator(unittest.TestCase):
    def test_constant_mode_cadence_and_bytes(self):
        dut = ACRGenerator(n_reset=6144, cts_reset=74250)
        got = []

        @passive
        def collect():
            yield dut.source.ready.eq(1)
            while True:
                if (yield dut.source.valid):
                    got.append((yield from read_packet(dut.source)))
                yield

        def frames():
            for i in range(200):
                yield dut.frame_strobe.eq(1)
                yield
                yield dut.frame_strobe.eq(0)
                for _ in range(3):
                    yield
            for _ in range(8):
                yield

        run_simulation(dut, [frames(), collect()])
        # 200 frames, one ACR every N/128 = 48 frames -> 4 packets.
        self.assertEqual(len(got), 4)
        self.assertTrue(all(p == am.acr_packet(6144, 74250) for p in got))

    def test_measured_mode_cts(self):
        # N = 128 -> one ACR per 128 clk128 strobes; strobes every 12/13 cycles
        # (mean 12.0857, like 74.25 MHz / 6.144 MHz) -> CTS about 1547.
        dut = ACRGenerator(n_reset=128, cts_reset=0)
        got = []

        @passive
        def collect():
            yield dut.source.ready.eq(1)
            while True:
                if (yield dut.source.valid):
                    got.append(am.unpack_acr((yield from read_packet(dut.source))))
                yield

        def strobes():
            yield dut.measure.eq(1)
            period = 0
            for i in range(128 * 9):
                gap = 13 if (i % 35) < 3 else 12          # 3 of every 35 gaps are 13 cycles
                for _ in range(gap - 1):
                    yield
                yield dut.clk128_strobe.eq(1)
                yield
                yield dut.clk128_strobe.eq(0)
            for _ in range(8):
                yield

        run_simulation(dut, [strobes(), collect()])
        self.assertGreaterEqual(len(got), 8)
        cts_values = [c for n, c in got[1:]]              # the first wrap counts from reset
        mean_gap = (12 * 32 + 13 * 3) / 35
        expected = round(128 * mean_gap)
        for c in cts_values:
            self.assertLessEqual(abs(c - expected), 2, (cts_values, expected))
        self.assertTrue(all(n == 128 for n, c in got))


class TestAudioInfoFrameGenerator(unittest.TestCase):
    def test_matches_model(self):
        dut = AudioInfoFrameGenerator()
        got = []

        def gen():
            yield dut.fields.cc.eq(1); yield dut.fields.sf.eq(3); yield dut.fields.ss.eq(3)
            yield dut.fields.ca.eq(0x00); yield dut.fields.lsv.eq(2)
            yield dut.source.ready.eq(1)
            yield
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            for _ in range(6):
                if (yield dut.source.valid):
                    got.append((yield from read_packet(dut.source)))
                yield

        run_simulation(dut, gen())
        self.assertEqual(got, [am.audio_infoframe(cc=1, sf=3, ss=3, ca=0, lsv=2)])
