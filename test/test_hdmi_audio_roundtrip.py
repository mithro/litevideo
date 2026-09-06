#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Transmitter with audio -> period decoder -> island decoder -> AudioExtract:
the tone comes back bit-exact, N/CTS and the Audio InfoFrame decode.

The pixel clock to sample rate ratio is reduced to 120 cycles per frame so the
simulation stays short; the blanking is widened to two packets per island so
the audio packets fit alongside the InfoFrames."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio import model as am
from litevideo.hdmi.transmitter import HDMITransmitter
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder
from litevideo.hdmi.audio.extract import AudioExtract
from litevideo.hdmi.audio.sources import tone_increment

from test.common import stream_inserter
from test.test_hdmi_framer import video_beats

FS = 48000
CYCLES_PER_FRAME = 120   # 1.3 frames per 158-character line; two island-free lines fit the 4-frame buffer
PIX = FS * CYCLES_PER_FRAME
TIMING = dict(hactive=32, hfront=6, hsync=8, hback=112, vactive=3, vfront=1, vsync=1, vback=2)


class DUT(Module):
    def __init__(self):
        self.submodules.tx = ClockDomainsRenamer({"pix": "sys"})(
            HDMITransmitter(default_vic=4, with_audio=True, pix_clk_freq=PIX, fs=FS, tone_freq=1000.0))
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        self.submodules.ext = AudioExtract()
        self.comb += [
            self.tx.source.connect(self.period.sink),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
            self.dec.source.connect(self.ext.sink),
        ]


class TestAudioRoundTrip(unittest.TestCase):
    def test_tone_roundtrip(self):
        dut = DUT()
        beats = video_beats(TIMING, 8)          # ~74 audio frames: at least one ACR (every 48)
        samples = []
        st = {}

        @passive
        def collect():
            while True:
                if (yield dut.ext.sample_source.valid):
                    samples.append(((yield dut.ext.sample_source.sample), (yield dut.ext.sample_source.channel),
                                    (yield dut.ext.sample_source.b)))
                yield

        def finish():
            for _ in range(len(beats) + 100):
                yield
            st["n"] = (yield dut.ext.n); st["cts"] = (yield dut.ext.cts)
            st["cc"] = (yield dut.ext.infoframe.cc); st["sf"] = (yield dut.ext.infoframe.sf)
            st["ss"] = (yield dut.ext.infoframe.ss)
            st["asp"] = (yield dut.ext.asp_count); st["acr"] = (yield dut.ext.acr_count)
            st["aif"] = (yield dut.ext.infoframe_count); st["dropped"] = (yield dut.ext.dropped_count)
            st["overruns"] = (yield dut.tx.tone.overruns)
            st["frames"] = (yield dut.tx.packetizer.frames_sent)

        run_simulation(dut, [stream_inserter(dut.tx.sink, beats, drain=120), collect(), finish()])

        self.assertEqual(st["dropped"], 0)
        self.assertEqual(st["overruns"], 0)
        self.assertGreater(st["asp"], 5)
        self.assertGreaterEqual(st["aif"], 3)
        # N from the "Other" row for this synthetic pixel clock; CTS 0 (not set).
        self.assertEqual((st["n"], st["cts"]), (N_DEFAULT[FS], 0))
        self.assertEqual((st["cc"], st["sf"], st["ss"]), (1, SF_CODE[FS], SS_24BIT))
        self.assertGreaterEqual(st["acr"], 1)
        # Samples: left/right alternate and equal the tone sequence from phase 0.
        left = [s for s, ch, b in samples if ch == 0]
        right = [s for s, ch, b in samples if ch == 1]
        self.assertEqual(len(left), len(right))
        self.assertEqual(len(left), st["frames"])
        expected = am.tone_sequence(len(left), tone_increment(1000.0, FS))
        self.assertEqual(left, [l for l, r in expected])
        self.assertEqual(right, [r for l, r in expected])
        self.assertEqual([b for s, ch, b in samples][:2], [1, 1])       # block start on frame 0
