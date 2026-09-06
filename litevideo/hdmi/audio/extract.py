#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio extraction from a received packet stream.

Consumes ``packet_rx_layout`` beats (from ``DataIslandDecoder``; packets with
a bad ECC are counted and dropped) and:

* Audio Sample Packets (HDMI 1.3 Tables 5-12/5-13, layout 0): each present
  subpacket yields two ``audio_sample_layout`` beats, channel 0 (left, SB0..2)
  then channel 1 (right, SB3..5), with V/U/C/P from SB6 and B from HB2;
* Audio Clock Regeneration (Table 5-11): N and CTS are latched;
* Audio InfoFrame (CEA-861-D Table 16): CC/CT/SF/SS/CA/LSV/DM_INH latched.

``sample_source`` has no back-pressure (one beat per cycle while a packet is
unpacked); an integrator that needs buffering adds a FIFO.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio.infoframe import audio_infoframe_fields_layout


class AudioExtract(LiteXModule):
    def __init__(self):
        self.sink = stream.Endpoint(packet_rx_layout)
        self.sample_source = stream.Endpoint(audio_sample_layout)

        self.n         = Signal(20)
        self.cts       = Signal(20)
        self.acr_valid = Signal()
        self.infoframe = Record(audio_infoframe_fields_layout)
        self.infoframe_valid = Signal()

        self.asp_count       = Signal(32)
        self.acr_count       = Signal(32)
        self.infoframe_count = Signal(32)
        self.sample_count    = Signal(32)
        self.dropped_count   = Signal(32)

        # # #

        sink = self.sink
        self.comb += sink.ready.eq(1)
        accept = sink.valid & sink.ecc_ok
        ptype = sink.header[0:8]
        hb1 = sink.header[8:16]
        hb2 = sink.header[16:24]
        s0 = sink.sub0

        self.sync += If(sink.valid & ~sink.ecc_ok, self.dropped_count.eq(self.dropped_count + 1))

        # ACR: SB1[3:0] = CTS[19:16], SB2 = CTS[15:8], SB3 = CTS[7:0], SB4[3:0] = N[19:16], SB5, SB6.
        self.sync += If(accept & (ptype == PacketType.ACR),
            self.cts.eq(Cat(s0[24:32], s0[16:24], s0[8:12])),
            self.n.eq(Cat(s0[48:56], s0[40:48], s0[32:36])),
            self.acr_valid.eq(1),
            self.acr_count.eq(self.acr_count + 1),
        )

        # Audio InfoFrame: PB1 = s0[8:16], PB2 = s0[16:24], PB4 = s0[32:40], PB5 = s0[40:48].
        f = self.infoframe
        self.sync += If(accept & (ptype == PacketType.AUDIO_INFOFRAME),
            f.cc.eq(s0[8:11]), f.ct.eq(s0[12:16]),
            f.ss.eq(s0[16:18]), f.sf.eq(s0[18:21]),
            f.ca.eq(s0[32:40]),
            f.lsv.eq(s0[43:47]), f.dm_inh.eq(s0[47]),
            self.infoframe_valid.eq(1),
            self.infoframe_count.eq(self.infoframe_count + 1),
        )

        # ASP: latch, then walk the 8 subframes.
        subs = [Signal(56) for _ in range(4)]
        present = Signal(4)
        bflags = Signal(4)
        pushing = Signal()
        idx = Signal(3)                      # subframe index: subpacket = idx[1:3], side = idx[0]
        self.sync += [
            self.sample_source.valid.eq(0),
            If(accept & (ptype == PacketType.ASP),
                *[subs[k].eq(getattr(sink, f"sub{k}")) for k in range(4)],
                present.eq(hb1[0:4]),
                bflags.eq(hb2[4:8]),
                pushing.eq(1),
                idx.eq(0),
                self.asp_count.eq(self.asp_count + 1),
            ).Elif(pushing,
                idx.eq(idx + 1),
                If(idx == 7, pushing.eq(0)),
            ),
        ]
        k = idx[1:3]
        side = idx[0]
        sub_sel = Signal(56)
        present_sel = Signal()
        b_sel = Signal()
        self.comb += [
            Case(k, {i: sub_sel.eq(subs[i]) for i in range(4)}),
            Case(k, {i: present_sel.eq(present[i]) for i in range(4)}),
            Case(k, {i: b_sel.eq(bflags[i]) for i in range(4)}),
        ]
        flags = sub_sel[48:56]               # VL UL CL PL VR UR CR PR
        out = self.sample_source
        self.sync += If(pushing & present_sel,
            out.valid.eq(1),
            out.sample.eq(Mux(side, sub_sel[24:48], sub_sel[0:24])),
            out.channel.eq(Cat(side, C(0, 2))),
            out.v.eq(Mux(side, flags[4], flags[0])),
            out.u.eq(Mux(side, flags[5], flags[1])),
            out.c.eq(Mux(side, flags[6], flags[2])),
            out.p.eq(Mux(side, flags[7], flags[3])),
            out.b.eq(b_sel),
            self.sample_count.eq(self.sample_count + 1),
        )
