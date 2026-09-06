#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Fixed-priority arbiter for data island packets.

``sinks[0]`` has the highest priority. A packet is handed to ``source`` whole
(one beat per packet, ``packet_layout``); the selected sink stays selected
until the beat is accepted, so a packet is never split or dropped. Priority
order in ``HDMITransmitter`` follows HDMI §7.8.2: Audio Sample Packets first,
then Audio Clock Regeneration, then General Control, then InfoFrames.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *


class PacketScheduler(LiteXModule):
    def __init__(self, n):
        self.sinks  = [stream.Endpoint(packet_layout) for _ in range(n)]
        self.source = stream.Endpoint(packet_layout)

        # # #

        sel = Signal(max=max(n, 2))
        locked = Signal()
        # Pick the highest-priority valid sink while not locked on one.
        for i in reversed(range(n)):
            self.comb += If(~locked & self.sinks[i].valid, sel.eq(i))
        self.sync += [
            If(self.source.valid & ~self.source.ready, locked.eq(1)),
            If(self.source.valid & self.source.ready, locked.eq(0)),
        ]
        sel_r = Signal(max=max(n, 2))
        self.sync += If(~locked, sel_r.eq(sel))
        current = Signal(max=max(n, 2))
        self.comb += current.eq(Mux(locked, sel_r, sel))
        cases = {}
        for i in range(n):
            cases[i] = self.sinks[i].connect(self.source)
        self.comb += Case(current, cases)
