#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI framer: pixels and packets in, TMDS characters out.

Turns a LiteX ``video_data_layout`` stream (one pixel per pixel clock; the
framer is always ready and expects ``valid`` to stay high while enabled) and
a ``packet_layout`` stream into the three 10-bit characters per clock of an
HDMI link:

* active pixels are TMDS encoded (channel 0 = B, 1 = G, 2 = R);
* blanking carries control characters with HSYNC/VSYNC on channel 0 (HDMI
  1.3 §5.4.2 Table 5-34);
* every Video Data Period is preceded by the 8-character video preamble
  (Table 5-2) and the 2-character video guard band (Table 5-5): the pixel
  stream is delayed by ``DELAY`` characters so the framer sees DE rise
  before the encoders do;
* data islands are placed ``MIN_CONTROL_PERIOD`` characters after each
  HSYNC leading edge, sized from the measured HSYNC-to-DE distance so that
  the island, four control characters, the video preamble and guard band
  always fit before DE (§5.2.3.2, Figure 5-3); the line on which VSYNC rises
  carries no island so its blanking is an Extended Control Period (Table 5-4);
* ``dvi_mode`` disables preambles, guard bands and islands for DVI sinks.

Overrides (guard bands, island characters) are aligned with the TMDS
encoders' latency and muxed over their outputs. Total latency from ``sink``
to ``source`` is ``DELAY + ENCODER_LATENCY`` characters.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.cores.video import video_data_layout

from litevideo.output.hdmi.encoder import Encoder
from litevideo.hdmi.common import *
from litevideo.hdmi.island.encoder import DataIslandEncoder

LOOKAHEAD = PREAMBLE_LENGTH + GUARD_BAND_LENGTH   # 10
DELAY = LOOKAHEAD + 1     # the preamble counter starts one cycle after the undelayed DE edge
ENCODER_LATENCY = 4       # litevideo.output.hdmi.encoder.Encoder: four registered stages


class HDMIFramer(LiteXModule):
    latency = DELAY + ENCODER_LATENCY

    def __init__(self):
        self.sink        = stream.Endpoint(video_data_layout)
        self.packet_sink = stream.Endpoint(packet_layout)
        self.source      = stream.Endpoint(raw_layout)
        self.enable_islands = Signal(reset=1)
        self.dvi_mode       = Signal()
        # Status
        self.hs2de        = Signal(16)   # measured HSYNC leading edge -> DE rise, characters
        self.hs2de_valid  = Signal()
        self.max_packets  = Signal(5)    # packets an island may carry on this timing
        self.island_count = Signal(32)

        # # #

        self.comb += self.sink.ready.eq(1)
        sink = self.sink

        # Delay line: undelayed sink -> delayed pixel/sync/DE (delayed time).
        names = ["de", "hsync", "vsync", "r", "g", "b"]
        stages = [Record([(n, len(getattr(sink, n))) for n in names]) for _ in range(DELAY)]
        prev = sink
        for st in stages:
            for n in names:
                self.sync += getattr(st, n).eq(getattr(prev, n))
            prev = st
        d = stages[-1]        # delayed by DELAY = 11: pre_cnt runs 1..10 on the 10 characters before d.de rises

        # Video preamble window: 8 characters starting when the undelayed DE rises,
        # then 2 guard band characters, then the delayed DE is high.
        de_u_r = Signal()
        self.sync += de_u_r.eq(sink.de)
        pre_cnt = Signal(4)
        pre_active = Signal()
        gb_active = Signal()
        self.sync += [
            If(sink.de & ~de_u_r & ~self.dvi_mode,
                pre_cnt.eq(1),
            ).Elif(pre_cnt != 0,
                pre_cnt.eq(pre_cnt + 1),
                If(pre_cnt == LOOKAHEAD, pre_cnt.eq(0)),
            ),
        ]
        self.comb += [
            pre_active.eq((pre_cnt >= 1) & (pre_cnt <= PREAMBLE_LENGTH)),
            gb_active.eq((pre_cnt > PREAMBLE_LENGTH) & (pre_cnt <= LOOKAHEAD)),
        ]

        # HSYNC-anchored island placement (delayed time).
        hsync_r = Signal()
        self.sync += hsync_r.eq(d.hsync)
        hs_edge = d.hsync & ~hsync_r
        since_hs = Signal(16)
        de_r = Signal()
        self.sync += de_r.eq(d.de)
        self.sync += [
            If(hs_edge, since_hs.eq(1)).Elif(since_hs != 0, since_hs.eq(since_hs + 1)),
            If(d.de & ~de_r & (since_hs != 0),
                self.hs2de.eq(since_hs),
                self.hs2de_valid.eq(1),
            ),
        ]
        room = Signal((17, True))
        self.comb += room.eq(self.hs2de - (MIN_CONTROL_PERIOD + MIN_ISLAND_TO_PREAMBLE + LOOKAHEAD + 12 + 2))
        npk = Signal((17, True))
        self.comb += npk.eq(room >> 5)
        self.comb += If(~self.hs2de_valid | (room < 0), self.max_packets.eq(0)
                     ).Elif(npk > MAX_PACKETS_PER_ISLAND, self.max_packets.eq(MAX_PACKETS_PER_ISLAND)
                     ).Else(self.max_packets.eq(npk))

        # Extended Control Period (Table 5-4): the first island slot after a
        # VSYNC leading edge is skipped. ``ecp_pending`` remembers the edge until
        # the next HSYNC edge, which arms ``ecp_line`` for that line's slot.
        vsync_r = Signal()
        self.sync += vsync_r.eq(d.vsync)
        vs_edge = d.vsync & ~vsync_r
        ecp_pending = Signal()
        ecp_line = Signal()
        self.sync += [
            If(vs_edge, ecp_pending.eq(1)),
            If(hs_edge,
                ecp_line.eq(ecp_pending | vs_edge),
                ecp_pending.eq(0),
            ),
        ]

        self.island = island = DataIslandEncoder()
        self.comb += [
            self.packet_sink.connect(island.sink),
            island.hsync.eq(d.hsync),
            island.vsync.eq(d.vsync),
            island.max_packets.eq(self.max_packets),
            island.start.eq((since_hs == MIN_CONTROL_PERIOD) & self.enable_islands & ~self.dvi_mode
                            & ~ecp_line & (self.max_packets != 0)),
        ]
        island_started = Signal()
        self.sync += island_started.eq(island.start & island.sink.valid)
        self.sync += If(island_started, self.island_count.eq(self.island_count + 1))

        # TMDS encoders on the delayed stream. Channel 1 carries CTL0/CTL1,
        # channel 2 CTL2/CTL3: the video preamble is CTL0=1.
        self.enc0 = enc0 = Encoder()
        self.enc1 = enc1 = Encoder()
        self.enc2 = enc2 = Encoder()
        self.comb += [
            enc0.d.eq(d.b), enc1.d.eq(d.g), enc2.d.eq(d.r),
            enc0.de.eq(d.de), enc1.de.eq(d.de), enc2.de.eq(d.de),
            enc0.c.eq(Cat(d.hsync, d.vsync)),
            enc1.c.eq(Mux(pre_active, PREAMBLE_VIDEO[0], 0)),
            enc2.c.eq(Mux(pre_active, PREAMBLE_VIDEO[1], 0)),
        ]

        # Overrides in delayed time, pipelined to output time.
        ovr_valid = Signal()
        ovr = Record(raw_layout)
        self.comb += [
            If(island.source.valid,
                ovr_valid.eq(1),
                ovr.c0.eq(island.source.c0), ovr.c1.eq(island.source.c1), ovr.c2.eq(island.source.c2),
            ).Elif(gb_active,
                ovr_valid.eq(1),
                ovr.c0.eq(video_gb_tokens[0]), ovr.c1.eq(video_gb_tokens[1]), ovr.c2.eq(video_gb_tokens[2]),
            ),
        ]
        pv = ovr_valid
        pr = ovr
        for _ in range(ENCODER_LATENCY):
            nv = Signal()
            nr = Record(raw_layout)
            self.sync += [nv.eq(pv), nr.c0.eq(pr.c0), nr.c1.eq(pr.c1), nr.c2.eq(pr.c2)]
            pv, pr = nv, nr

        self.comb += [
            self.source.valid.eq(1),
            If(pv,
                self.source.c0.eq(pr.c0), self.source.c1.eq(pr.c1), self.source.c2.eq(pr.c2),
            ).Else(
                self.source.c0.eq(enc0.out), self.source.c1.eq(enc1.out), self.source.c2.eq(enc2.out),
            ),
        ]
