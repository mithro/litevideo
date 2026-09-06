#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Data island serialiser.

Turns a stream of packets into framed data islands (HDMI 1.3 §5.2.3): the
8-character Data Island Preamble (Table 5-2: CTL0=1, CTL2=1 on channels 1 and
2, HSYNC/VSYNC on channel 0), the 2-character Leading Guard Band (Table 5-6
on channels 1/2, TERC4(1,1,VSYNC,HSYNC) on channel 0, §5.2.3.3), one to
``max_packets`` packets of 32 TERC4 characters (§5.2.3.4: header bit on
channel 0 bit 2, BCH block k on bit k of channels 1 and 2, ECC generated
serially with ``bch_step``, §5.2.3.5), then the Trailing Guard Band.

* Channel 0 bit 3 is 0 on the first character of the island and 1 on every
  other packet character (HDMI 1.3 Figure 5-3, HDMI 1.4b CTS).
* The ``hsync``/``vsync`` inputs are carried live on every character
  (§5.2.3.1), so the caller must keep them aligned with the island.
* After the trailing guard band the encoder stays busy for
  ``MIN_ISLAND_TO_PREAMBLE`` characters and ignores ``start``, so two islands
  are always separated by at least 4 + 8 = 12 control characters
  (§5.2.3.2 tS,min). The caller still owns the placement relative to video:
  it raises ``start`` only where the island plus the following control period,
  video preamble and guard band fit before DE.
* ``max_packets`` is clamped to 18 (§5.2.3.2). ``source.ready`` is ignored:
  the island streams at one character per cycle once started.
"""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_step


class DataIslandEncoder(LiteXModule):
    def __init__(self):
        self.sink   = stream.Endpoint(packet_layout)
        self.source = stream.Endpoint(raw_layout)
        self.hsync       = Signal()
        self.vsync       = Signal()
        self.start       = Signal()
        self.max_packets = Signal(5, reset=MAX_PACKETS_PER_ISLAND)
        self.busy        = Signal()

        # # #

        # Packet registers (shifted out LSB first) and serial ECC accumulators.
        header = Signal(24)
        hecc   = Signal(8)
        subs   = [Signal(56) for _ in range(4)]
        secc   = [Signal(8) for _ in range(4)]
        count  = Signal(5)    # characters within the current phase
        npkt   = Signal(5)    # packets sent in this island
        first  = Signal()     # current character is the first of the island

        max_packets = Signal(5)
        self.comb += max_packets.eq(Mux(self.max_packets > MAX_PACKETS_PER_ISLAND,
                                        MAX_PACKETS_PER_ISLAND, self.max_packets))

        def load_packet():
            return [
                NextValue(header, self.sink.header), NextValue(hecc, 0),
                *[NextValue(subs[k], getattr(self.sink, f"sub{k}")) for k in range(4)],
                *[NextValue(secc[k], 0) for k in range(4)],
            ]

        # Current character contents.
        hbit = Mux(count < 24, header[0], hecc[0])
        n1 = Signal(4)
        n2 = Signal(4)
        for k in range(4):
            self.comb += [
                n1[k].eq(Mux(count < 28, subs[k][0], secc[k][0])),
                n2[k].eq(Mux(count < 28, subs[k][1], secc[k][1])),
            ]
        syncs = Cat(self.hsync, self.vsync)
        n0 = Cat(syncs, hbit, ~first)

        terc4 = Array(terc4_tokens)
        ctl0 = Array(control_tokens)[syncs]
        gb0  = Array(terc4_tokens[12:])[syncs]      # TERC4(1, 1, VSYNC, HSYNC), §5.2.3.3
        pre  = (ctl0, control_tokens[PREAMBLE_DATA[0]], control_tokens[PREAMBLE_DATA[1]])
        gb   = (gb0, data_gb_token, data_gb_token)

        def emit(c):
            return [self.source.valid.eq(1), self.source.c0.eq(c[0]), self.source.c1.eq(c[1]), self.source.c2.eq(c[2])]

        def shift():
            acts = [
                If(count < 24, NextValue(hecc, bch_step(hecc, header[0]))).Else(NextValue(hecc, Cat(hecc[1:], 0))),
                NextValue(header, Cat(header[1:], 0)),
            ]
            for k in range(4):
                acts += [
                    If(count < 28,
                        NextValue(secc[k], bch_step(bch_step(secc[k], subs[k][0]), subs[k][1])),
                    ).Else(
                        NextValue(secc[k], Cat(secc[k][2:], 0)),
                    ),
                    NextValue(subs[k], Cat(subs[k][2:], 0)),
                ]
            return acts

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(self.start & self.sink.valid & (max_packets != 0),
                self.sink.ready.eq(1),
                *load_packet(),
                NextValue(count, 0), NextValue(npkt, 1),
                NextState("PREAMBLE"),
            ),
        )
        fsm.act("PREAMBLE",
            self.busy.eq(1), *emit(pre),
            NextValue(count, count + 1),
            If(count == PREAMBLE_LENGTH - 1, NextValue(count, 0), NextState("LEADING_GUARD")),
        )
        fsm.act("LEADING_GUARD",
            self.busy.eq(1), *emit(gb),
            NextValue(count, count + 1),
            If(count == GUARD_BAND_LENGTH - 1, NextValue(count, 0), NextValue(first, 1), NextState("PACKET")),
        )
        fsm.act("PACKET",
            self.busy.eq(1), *emit((terc4[n0], terc4[n1], terc4[n2])),
            *shift(),
            NextValue(first, 0),
            NextValue(count, count + 1),
            If(count == PACKET_LENGTH - 1,
                NextValue(count, 0),
                If(self.sink.valid & (npkt < max_packets),
                    self.sink.ready.eq(1),
                    *load_packet(),
                    NextValue(npkt, npkt + 1),
                ).Else(
                    NextState("TRAILING_GUARD"),
                ),
            ),
        )
        fsm.act("TRAILING_GUARD",
            self.busy.eq(1), *emit(gb),
            NextValue(count, count + 1),
            If(count == GUARD_BAND_LENGTH - 1, NextValue(count, 0), NextState("GAP")),
        )
        fsm.act("GAP",                               # minimum control period after an island
            self.busy.eq(1),
            NextValue(count, count + 1),
            If(count == MIN_ISLAND_TO_PREAMBLE - 1, NextValue(count, 0), NextState("IDLE")),
        )
