#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Fixed-priority packet arbiter."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi.scheduler import PacketScheduler

from test.common import stream_inserter, stream_collector


class TestPacketScheduler(unittest.TestCase):
    def test_priority_and_completeness(self):
        dut = PacketScheduler(n=3)
        a = [{"header": 0xA0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        b = [{"header": 0xB0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        c = [{"header": 0xC0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sinks[0], a, valid_rand=50, seed=1),
            stream_inserter(dut.sinks[1], b, valid_rand=50, seed=2),
            stream_inserter(dut.sinks[2], c, valid_rand=50, seed=3),
            stream_collector(dut.source, ["header"], out, ready_rand=30),
        ])
        headers = [o["header"] for o in out]
        self.assertEqual(sorted(headers), sorted(x["header"] for x in a + b + c))
        # Within each source the order is preserved.
        for prefix in (0xA0, 0xB0, 0xC0):
            self.assertEqual([h for h in headers if h & 0xF0 == prefix], [prefix + i for i in range(4)])

    def test_highest_priority_wins_when_both_valid(self):
        dut = PacketScheduler(n=2)
        out = []

        def drive():
            yield dut.sinks[0].valid.eq(1); yield dut.sinks[0].header.eq(1)
            yield dut.sinks[1].valid.eq(1); yield dut.sinks[1].header.eq(2)
            yield dut.source.ready.eq(1)
            yield
            out.append((yield dut.source.header))
            out.append((yield dut.sinks[0].ready))
            yield

        run_simulation(dut, drive())
        self.assertEqual(out, [1, 1])
