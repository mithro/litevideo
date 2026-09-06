#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Encoder -> period decoder -> island decoder, all gateware."""

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandEncoder, DataIslandDecoder

from test.common import stream_inserter


class DUT(Module):
    def __init__(self):
        self.submodules.enc = DataIslandEncoder()
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        idle = model.control_chars(0, 0)
        self.comb += [
            self.period.sink.valid.eq(1),
            If(self.enc.source.valid,
                self.period.sink.c0.eq(self.enc.source.c0),
                self.period.sink.c1.eq(self.enc.source.c1),
                self.period.sink.c2.eq(self.enc.source.c2),
            ).Else(
                self.period.sink.c0.eq(idle[0]), self.period.sink.c1.eq(idle[1]), self.period.sink.c2.eq(idle[2]),
            ),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
        ]


class TestIslandRoundTrip(unittest.TestCase):
    def test_roundtrip(self):
        prng = random.Random(31)
        packets = [model.Packet([prng.randrange(256) for _ in range(3)],
                                [[prng.randrange(256) for _ in range(7)] for _ in range(4)]) for _ in range(30)]
        dut = DUT()
        beats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
        out = []

        @passive
        def collect():
            while True:
                if (yield dut.dec.source.valid):
                    header = (yield dut.dec.source.header)
                    subs = []
                    for k in range(4):
                        subs.append((yield getattr(dut.dec.source, f"sub{k}")))
                    out.append((model.Packet.from_words(header, subs), (yield dut.dec.source.ecc_ok)))
                yield

        def control():
            yield dut.enc.max_packets.eq(7)
            yield dut.enc.start.eq(1)
            for _ in range(len(packets) * 40 + 100):
                yield

        run_simulation(dut, [stream_inserter(dut.enc.sink, beats, valid_rand=30), collect(), control()])
        self.assertEqual([p for p, _ in out], packets)
        self.assertTrue(all(ok for _, ok in out))
