#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.island.encoder import DataIslandEncoder

from test.common import stream_inserter


def random_packet(prng):
    return model.Packet([prng.randrange(256) for _ in range(3)],
                        [[prng.randrange(256) for _ in range(7)] for _ in range(4)])


def encode(packets, max_packets=18, hsync=0, vsync=1, valid_rand=0):
    dut = DataIslandEncoder()
    beats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
    out = []

    @passive
    def collect():
        while True:
            if (yield dut.source.valid):
                out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
            yield

    def control():
        yield dut.hsync.eq(hsync); yield dut.vsync.eq(vsync)
        yield dut.max_packets.eq(max_packets); yield dut.start.eq(1)
        for _ in range(len(packets) * 40 + 40):
            yield

    run_simulation(dut, [stream_inserter(dut.sink, beats, valid_rand=valid_rand), collect(), control()])
    return out


class TestDataIslandEncoder(unittest.TestCase):
    def test_single_packet_matches_model(self):
        p = model.Packet([0x82, 0x02, 0x0D], [[i + 7 * k for i in range(7)] for k in range(4)])
        self.assertEqual(encode([p]), model.island_tokens([p], hsync=0, vsync=1))

    def test_multi_packet_island(self):
        prng = random.Random(21)
        packets = [random_packet(prng) for _ in range(5)]
        self.assertEqual(encode(packets), model.island_tokens(packets, hsync=0, vsync=1))

    def test_max_packets_splits_islands(self):
        prng = random.Random(22)
        packets = [random_packet(prng) for _ in range(3)]
        expected = model.island_tokens(packets[:2], vsync=1) + model.island_tokens(packets[2:], vsync=1)
        self.assertEqual(encode(packets, max_packets=2), expected)

    def test_gap_in_sink_ends_island(self):
        prng = random.Random(23)
        packets = [random_packet(prng) for _ in range(4)]
        out = encode(packets, valid_rand=60)
        # Every emitted character must belong to a well-formed island; count islands by preambles.
        n_pre = sum(1 for t in out if t == model.control_chars(0, 1, PREAMBLE_DATA)) // PREAMBLE_LENGTH
        self.assertGreaterEqual(n_pre, 1)
        self.assertEqual((len(out) - n_pre * (PREAMBLE_LENGTH + 2 * GUARD_BAND_LENGTH)) % PACKET_LENGTH, 0)
