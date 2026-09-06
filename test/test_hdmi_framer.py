#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMIFramer: pixels + packets in, characters out, checked by feeding the
characters back into the phase-1 period and island decoders."""

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.framer import HDMIFramer
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder

from test.common import stream_inserter

# hsync + hback = 88 characters from the HSYNC edge to DE: room for one packet per
# island (88 - 12 - 4 - 10 - 12 - 2 = 48 -> 1). With hback=60 no island fits.
TIMING = dict(hactive=32, hfront=6, hsync=8, hback=80, vactive=3, vfront=1, vsync=1, vback=2)
LINE = sum(TIMING[k] for k in ("hactive", "hfront", "hsync", "hback"))
VTOTAL = sum(TIMING[k] for k in ("vactive", "vfront", "vsync", "vback"))


class DUT(Module):
    def __init__(self):
        self.submodules.framer = HDMIFramer()
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        self.comb += [
            self.framer.source.connect(self.period.sink),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
        ]


def video_beats(timing, nframes):
    """video_data_layout beats for ``nframes`` of ``timing`` with the same pixel
    pattern ``model.frame_tokens`` encodes."""
    frames = model.frame_tokens(timing, nframes=nframes)
    ha = timing["hactive"]
    vt = sum(timing[k] for k in ("vactive", "vfront", "vsync", "vback"))
    line = ha + timing["hfront"] + timing["hsync"] + timing["hback"]
    beats = []
    for i, (c0, c1, c2, de, hs, vs) in enumerate(frames):
        y = (i // line) % vt
        x = i % line
        b = {"de": de, "hsync": hs, "vsync": vs, "r": 0, "g": 0, "b": 0}
        if de:
            b["r"], b["g"], b["b"] = (((x + y) * 7) & 0xFF, ((x * 13) ^ y) & 0xFF, ((x + 2 * y) * 29) & 0xFF)
        beats.append(b)
    return beats


def run_framer(timing, nframes, packets, valid_rand_packets=0):
    dut = DUT()
    beats = video_beats(timing, nframes)
    pbeats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
    rx = {"video": [], "packets": [], "periods": [], "errors": 0, "max_packets": 0}

    @passive
    def collect():
        while True:
            if (yield dut.period.source.valid):
                rx["periods"].append((yield dut.period.period))
                if (yield dut.period.source.de):
                    rx["video"].append(((yield dut.period.source.r), (yield dut.period.source.g), (yield dut.period.source.b)))
            if (yield dut.period.error):
                rx["errors"] += 1
            if (yield dut.dec.source.valid):
                header = (yield dut.dec.source.header)
                subs = []
                for k in range(4):
                    subs.append((yield getattr(dut.dec.source, f"sub{k}")))
                rx["packets"].append((model.Packet.from_words(header, subs), (yield dut.dec.source.ecc_ok)))
            rx["max_packets"] = (yield dut.framer.max_packets)
            yield

    # The packet inserter is passive: if placement never happens the video
    # inserter still ends the simulation and the assertions report it, instead
    # of the test hanging on ``packet_sink.ready``.
    run_simulation(dut, [
        stream_inserter(dut.framer.sink, beats, drain=40),
        passive(stream_inserter)(dut.framer.packet_sink, pbeats, valid_rand=valid_rand_packets, drain=0),
        collect(),
    ])
    return dut, beats, rx


class TestHDMIFramer(unittest.TestCase):
    def test_video_only_roundtrip(self):
        dut, beats, rx = run_framer(TIMING, nframes=2, packets=[])
        expected = [(b["r"], b["g"], b["b"]) for b in beats if b["de"]]
        self.assertEqual(rx["video"], expected)
        self.assertEqual(rx["errors"], 0)
        self.assertNotIn(Period.DATA_ISLAND, rx["periods"])

    def test_islands_delivered_and_placed(self):
        prng = random.Random(41)
        # 3 frames x 7 lines = 21 island slots minus the first line (timing not
        # yet measured) and the 3 VSYNC lines: 12 packets fit, one per island.
        packets = [model.Packet([prng.randrange(256) for _ in range(3)],
                                [[prng.randrange(256) for _ in range(7)] for _ in range(4)]) for _ in range(12)]
        dut, beats, rx = run_framer(TIMING, nframes=3, packets=packets)
        self.assertEqual([p for p, _ in rx["packets"]], packets)
        self.assertTrue(all(ok for _, ok in rx["packets"]))
        self.assertEqual(rx["errors"], 0)
        # Video is untouched.
        expected = [(b["r"], b["g"], b["b"]) for b in beats if b["de"]]
        self.assertEqual(rx["video"], expected)
        periods = rx["periods"]
        # No island on the first line (timing not yet measured).
        self.assertNotIn(Period.DATA_ISLAND, periods[:LINE])
        # No island on the line where VSYNC rises (Extended Control Period, Table 5-4).
        vsync_line = TIMING["vactive"] + TIMING["vfront"]
        for f in range(3):
            start = (f * VTOTAL + vsync_line) * LINE
            self.assertNotIn(Period.DATA_ISLAND, periods[start:start + LINE], f"frame {f}")

    def test_control_period_rules(self):
        packets = [model.Packet.null() for _ in range(8)]      # fewer than the ~10 slots in 2 frames
        dut, beats, rx = run_framer(TIMING, nframes=2, packets=packets)
        periods = rx["periods"]
        self.assertEqual(len(rx["packets"]), 8)
        # Every run of CONTROL after a trailing guard band is >= 4, and every
        # CONTROL run before a data island preamble is >= 12.
        runs = []
        i = 0
        while i < len(periods):
            j = i
            while j < len(periods) and periods[j] == periods[i]:
                j += 1
            runs.append((periods[i], j - i))
            i = j
        for k, (p, n) in enumerate(runs):
            if p == Period.CONTROL:
                nxt = runs[k + 1][0] if k + 1 < len(runs) else None
                prv = runs[k - 1][0] if k > 0 else None
                if prv == Period.DATA_TRAILING_GUARD:
                    self.assertGreaterEqual(n, MIN_ISLAND_TO_PREAMBLE)
                if nxt == Period.DATA_PREAMBLE:
                    self.assertGreaterEqual(n, MIN_CONTROL_PERIOD)
        self.assertGreaterEqual(rx["max_packets"], 1)

    def test_dvi_mode_has_no_preambles(self):
        dut = DUT()
        beats = video_beats(TIMING, 2)
        periods = []

        @passive
        def collect():
            while True:
                if (yield dut.period.source.valid):
                    periods.append((yield dut.period.period))
                yield

        def setup():
            yield dut.framer.dvi_mode.eq(1)
            yield dut.period.dvi_mode.eq(1)

        run_simulation(dut, [setup(), stream_inserter(dut.framer.sink, beats, drain=40), collect()])
        self.assertNotIn(Period.VIDEO_PREAMBLE, periods)
        self.assertNotIn(Period.DATA_PREAMBLE, periods)
