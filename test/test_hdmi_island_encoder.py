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


def beats_of(packets):
    return [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]


def encode(packets, max_packets=18, hsync=0, vsync=1, valid_rand=0, every_cycle=False):
    """Run the encoder; return the emitted characters (only valid cycles, or
    every cycle as (valid, c0, c1, c2) with ``every_cycle``)."""
    dut = DataIslandEncoder()
    out = []

    @passive
    def collect():
        while True:
            v = (yield dut.source.valid)
            if every_cycle:
                out.append((v, (yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
            elif v:
                out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
            yield

    def control():
        yield dut.hsync.eq(hsync); yield dut.vsync.eq(vsync)
        yield dut.max_packets.eq(max_packets); yield dut.start.eq(1)
        for _ in range(len(packets) * 40 + 40):
            yield

    run_simulation(dut, [stream_inserter(dut.sink, beats_of(packets), valid_rand=valid_rand), collect(), control()])
    return out


def split_islands(every_cycle):
    """Split an every-cycle record into (islands, gaps): islands are lists of
    characters, gaps the number of idle cycles between consecutive islands."""
    islands, gaps = [], []
    cur, idle = None, 0
    for v, c0, c1, c2 in every_cycle:
        if v:
            if cur is None:
                if islands:
                    gaps.append(idle)
                cur = []
            cur.append((c0, c1, c2))
            idle = 0
        else:
            if cur is not None:
                islands.append(cur)
                cur = None
            idle += 1
    if cur is not None:
        islands.append(cur)
    return islands, gaps


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
        islands, gaps = split_islands(encode(packets, max_packets=2, every_cycle=True))
        self.assertEqual(islands, [model.island_tokens(packets[:2], vsync=1), model.island_tokens(packets[2:], vsync=1)])
        self.assertTrue(all(g >= MIN_ISLAND_TO_PREAMBLE for g in gaps), gaps)

    def test_max_packets_clamped_to_18(self):
        prng = random.Random(25)
        packets = [random_packet(prng) for _ in range(20)]
        islands, _ = split_islands(encode(packets, max_packets=31, every_cycle=True))
        self.assertEqual([len(i) for i in islands], [model.island_length(18), model.island_length(2)])

    def test_gap_in_sink_ends_island_and_islands_are_well_formed(self):
        prng = random.Random(23)
        packets = [random_packet(prng) for _ in range(6)]
        # valid_rand=97: gaps of ~33 cycles on average, longer than a packet, so
        # the encoder cannot always chain packets and must close islands.
        islands, gaps = split_islands(encode(packets, valid_rand=97, every_cycle=True))
        # Each island is exactly the model's rendering of the packets it carried,
        # and islands are separated by at least the minimum control period.
        got = []
        for isl in islands:
            n = (len(isl) - PREAMBLE_LENGTH - 2 * GUARD_BAND_LENGTH) // PACKET_LENGTH
            self.assertEqual(isl, model.island_tokens(packets[len(got):len(got) + n], vsync=1))
            got += packets[len(got):len(got) + n]
        self.assertEqual(got, packets)
        self.assertGreaterEqual(len(islands), 2)
        self.assertTrue(all(g >= MIN_ISLAND_TO_PREAMBLE for g in gaps), gaps)

    def test_live_syncs_inside_island(self):
        prng = random.Random(24)
        p = random_packet(prng)
        dut = DataIslandEncoder()
        out = []

        @passive
        def collect():
            while True:
                if (yield dut.source.valid):
                    out.append(((yield dut.source.c0), (yield dut.hsync), (yield dut.vsync)))
                yield

        def control():
            yield dut.start.eq(1)
            yield dut.hsync.eq(1)
            for i in range(80):
                if i == 20:
                    yield dut.vsync.eq(1)   # changes inside the packet
                if i == 30:
                    yield dut.hsync.eq(0)   # sync ends during the packet
                yield

        run_simulation(dut, [stream_inserter(dut.sink, beats_of([p])), collect(), control()])
        self.assertEqual(len(out), model.island_length(1))
        seen_edges = len({hs for _, hs, _ in out}) == 2 and len({vs for _, _, vs in out}) == 2
        self.assertTrue(seen_edges, "test setup: both syncs must change inside the island")
        for c0, hs, vs in out:
            n = model.terc4_decode(c0)
            if n is None:            # preamble control character
                self.assertEqual(c0, control_tokens[(vs << 1) | hs])
            else:
                self.assertEqual(n & 0b11, (vs << 1) | hs)
