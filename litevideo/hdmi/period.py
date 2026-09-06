#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI period decoder: three TMDS characters per cycle in, the link period,
syncs, DE, pixel data and data island nibbles out.

The state machine follows HDMI 1.3 §5.2 (Figure 5-3): a Control Period ends
with an 8-character Preamble (Table 5-2) that says whether a Video Data
Period (2-character Video Guard Band, Table 5-5) or a Data Island (Leading
Guard Band, packets, Trailing Guard Band, Table 5-6) follows. HSYNC/VSYNC are
taken from channel 0's control value during Control Periods (§5.4.2 Table
5-34) and from channel 0 TERC4 bits 0 and 1 during islands and their guard
bands (§5.2.3.1); they hold during video. DE is 1 during Video Data Periods.

Convention: ``period`` reports the *new* period on the character that causes
the transition (the first preamble character is already VIDEO_PREAMBLE /
DATA_PREAMBLE, the first non-guard character after a guard band is already
VIDEO / DATA_ISLAND).

``dvi_mode`` bypasses the preamble tracking for DVI sources (which never send
preambles or guard bands): DE is then simply "channel 0 is not a control
character".

Latency: 2 cycles (character decode + registered outputs).
"""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.cores.video import video_data_layout

from litevideo.hdmi.common import *
from litevideo.hdmi.tmds import TMDSCharacterDecoder


class HDMIPeriodDecoder(LiteXModule):
    latency = 2

    def __init__(self):
        self.sink   = stream.Endpoint(raw_layout)
        self.source = stream.Endpoint(video_data_layout)
        self.dvi_mode = Signal()

        self.period        = Signal(3)
        self.island_active = Signal()   # a packet character (not a guard band) is on ``nibble*``
        self.island_first  = Signal()   # ... and it is the first character of the island
        self.nibble0       = Signal(4)
        self.nibble1       = Signal(4)
        self.nibble2       = Signal(4)
        self.error         = Signal()   # island ended by a control character instead of a guard band

        # # #

        self.comb += self.sink.ready.eq(1)

        self.dec0 = dec0 = TMDSCharacterDecoder(0)
        self.dec1 = dec1 = TMDSCharacterDecoder(1)
        self.dec2 = dec2 = TMDSCharacterDecoder(2)
        self.comb += [dec0.raw.eq(self.sink.c0), dec1.raw.eq(self.sink.c1), dec2.raw.eq(self.sink.c2)]

        all_control = dec0.control & dec1.control & dec2.control
        any_control = dec0.control | dec1.control | dec2.control
        preamble    = Cat(dec1.c, dec2.c)   # {ch2 D1, ch2 D0, ch1 D1, ch1 D0}
        video_pre   = all_control & (preamble == ((PREAMBLE_VIDEO[1] << 2) | PREAMBLE_VIDEO[0]))
        data_pre    = all_control & (preamble == ((PREAMBLE_DATA[1] << 2) | PREAMBLE_DATA[0]))
        all_video_gb = dec0.video_gb & dec1.video_gb & dec2.video_gb
        data_gb      = dec1.data_gb & dec2.data_gb

        period = Signal(3)
        in_island = Signal()
        first = Signal()
        error = Signal()

        self.fsm = fsm = FSM(reset_state="CONTROL")
        fsm.act("CONTROL",
            period.eq(Period.CONTROL),
            If(video_pre, period.eq(Period.VIDEO_PREAMBLE), NextState("VIDEO_PREAMBLE")),
            If(data_pre,  period.eq(Period.DATA_PREAMBLE),  NextState("DATA_PREAMBLE")),
        )
        fsm.act("VIDEO_PREAMBLE",
            period.eq(Period.VIDEO_PREAMBLE),
            If(all_video_gb, period.eq(Period.VIDEO_GUARD), NextState("VIDEO_GUARD"))
            .Elif(~video_pre, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("VIDEO_GUARD",
            period.eq(Period.VIDEO_GUARD),
            If(~all_video_gb, period.eq(Period.VIDEO), NextState("VIDEO")),
        )
        fsm.act("VIDEO",
            period.eq(Period.VIDEO),
            If(any_control, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("DATA_PREAMBLE",
            period.eq(Period.DATA_PREAMBLE),
            If(data_gb, period.eq(Period.DATA_LEADING_GUARD), NextState("DATA_LEADING_GUARD"))
            .Elif(~data_pre, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("DATA_LEADING_GUARD",
            period.eq(Period.DATA_LEADING_GUARD),
            If(~data_gb, period.eq(Period.DATA_ISLAND), in_island.eq(1), first.eq(1), NextState("DATA_ISLAND")),
        )
        fsm.act("DATA_ISLAND",
            period.eq(Period.DATA_ISLAND),
            in_island.eq(1),
            If(data_gb, period.eq(Period.DATA_TRAILING_GUARD), in_island.eq(0), NextState("DATA_TRAILING_GUARD"))
            .Elif(any_control, period.eq(Period.CONTROL), in_island.eq(0), error.eq(1), NextState("CONTROL")),
        )
        fsm.act("DATA_TRAILING_GUARD",
            period.eq(Period.DATA_TRAILING_GUARD),
            If(~data_gb, period.eq(Period.CONTROL), NextState("CONTROL")),
        )

        # Syncs: control value on channel 0 during control periods, TERC4 bits
        # 0/1 during islands and their guard bands, held during video.
        hsync = Signal()
        vsync = Signal()
        self.sync += [
            If(dec0.control,
                hsync.eq(dec0.c[0]), vsync.eq(dec0.c[1]),
            ).Elif(dec0.terc4_valid & (period >= Period.DATA_PREAMBLE),
                hsync.eq(dec0.terc4[0]), vsync.eq(dec0.terc4[1]),
            ),
        ]

        de = Signal()
        self.comb += de.eq(Mux(self.dvi_mode, ~dec0.control, period == Period.VIDEO))

        # Registered outputs.
        self.sync += [
            self.period.eq(period),
            self.island_active.eq(in_island & self.sink.valid),
            self.island_first.eq(first),
            self.nibble0.eq(dec0.terc4),
            self.nibble1.eq(dec1.terc4),
            self.nibble2.eq(dec2.terc4),
            self.error.eq(error),
            self.source.valid.eq(self.sink.valid),
            self.source.de.eq(de),
            self.source.hsync.eq(Mux(dec0.control, dec0.c[0], hsync)),
            self.source.vsync.eq(Mux(dec0.control, dec0.c[1], vsync)),
            self.source.b.eq(dec0.d),
            self.source.g.eq(dec1.d),
            self.source.r.eq(dec2.d),
        ]
