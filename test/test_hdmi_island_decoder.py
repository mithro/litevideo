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
from litevideo.hdmi.island.decoder import DataIslandDecoder


def random_packet(prng):
    return model.Packet([prng.randrange(256) for _ in range(3)],
                        [[prng.randrange(256) for _ in range(7)] for _ in range(4)])


def run_islands(islands):
    """islands: list of (packets, corrupt kwargs). Drives nibbles directly."""
    dut = DataIslandDecoder()
    out = []

    def drive():
        for packets, corrupt in islands:
            first = True
            for p in packets:
                for hbit, n1, n2 in model.packet_chars(p, **corrupt):
                    yield dut.active.eq(1)
                    yield dut.first.eq(first)
                    yield dut.nibble0.eq(((0 if first else 1) << 3) | (hbit << 2))
                    yield dut.nibble1.eq(n1)
                    yield dut.nibble2.eq(n2)
                    first = False
                    yield
            yield dut.active.eq(0)
            yield dut.first.eq(0)
            for _ in range(8):
                yield
        for _ in range(4):
            yield

    @passive
    def collect():
        while True:
            if (yield dut.source.valid):
                header = (yield dut.source.header)
                subs = []
                for k in range(4):
                    subs.append((yield getattr(dut.source, f"sub{k}")))
                out.append((model.Packet.from_words(header, subs), (yield dut.source.ecc_ok)))
            yield

    run_simulation(dut, [drive(), collect()])
    return dut, out


class TestDataIslandDecoder(unittest.TestCase):
    def test_single_and_multi_packet_islands(self):
        prng = random.Random(11)
        islands = [([random_packet(prng)], {}), ([random_packet(prng) for _ in range(18)], {}), ([model.Packet.null()], {})]
        _, out = run_islands(islands)
        expected = [p for packets, _ in islands for p in packets]
        self.assertEqual([p for p, _ in out], expected)
        self.assertTrue(all(ok for _, ok in out))

    def test_corrupted_ecc_is_flagged(self):
        prng = random.Random(12)
        p = random_packet(prng)
        _, out = run_islands([([p], {"corrupt_header_ecc": True}), ([p], {"corrupt_subpacket_ecc": 2}), ([p], {})])
        self.assertEqual([ok for _, ok in out], [0, 0, 1])
        self.assertEqual(out[2][0], p)

    def test_truncated_island_emits_nothing(self):
        prng = random.Random(13)
        p = random_packet(prng)
        dut = DataIslandDecoder()
        out = []

        def drive():
            for hbit, n1, n2 in model.packet_chars(p)[:20]:
                yield dut.active.eq(1); yield dut.nibble0.eq(hbit << 2); yield dut.nibble1.eq(n1); yield dut.nibble2.eq(n2)
                yield
            yield dut.active.eq(0)
            for _ in range(40):
                if (yield dut.source.valid):
                    out.append(1)
                yield

        run_simulation(dut, drive())
        self.assertEqual(out, [])
