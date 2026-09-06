#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio Clock Regeneration packet generator (HDMI 1.3 §5.3.3, §7.2, §7.8.2).

The sink regenerates the audio clock as 128·fs = f_TMDS · N / CTS. Packets
are sent at the rate 128·fs/N, that is once per N/128 audio frames
(§7.8.2), carrying N and CTS in four identical subpackets (Table 5-11).

Two modes:

* constant (``measure`` = 0): N and CTS are the coherent-clock values of
  Tables 7-1 to 7-3, given on ``n``/``cts``; the packet cadence is derived
  from ``frame_strobe`` (one pulse per audio frame sent);
* measured (``measure`` = 1, Figure 7-1): ``clk128_strobe`` pulses once per
  128·fs cycle; a divide-by-N counter on it defines the ACR cadence and CTS
  is the number of pixel clocks counted between two counter wraps.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.infoframe import _PacketHolder


class ACRGenerator(LiteXModule):
    def __init__(self, n_reset=6144, cts_reset=74250):
        self.n   = Signal(20, reset=n_reset)
        self.cts = Signal(20, reset=cts_reset)
        self.frame_strobe  = Signal()
        self.clk128_strobe = Signal()
        self.measure       = Signal()
        self.source    = stream.Endpoint(packet_layout)
        self.acr_count = Signal(32)
        self.cts_measured = Signal(20)

        # # #

        # Constant mode: one packet every N/128 frames.
        frames = Signal(13)
        frames_per_acr = Signal(13)
        self.comb += frames_per_acr.eq(self.n[7:])
        const_trigger = Signal()
        self.sync += [
            const_trigger.eq(0),
            If(self.frame_strobe & ~self.measure,
                If(frames >= frames_per_acr - 1,
                    frames.eq(0),
                    const_trigger.eq(1),
                ).Else(
                    frames.eq(frames + 1),
                ),
            ),
        ]

        # Measured mode: divide clk128_strobe by N, count pixel clocks per wrap.
        div = Signal(20)
        cycles = Signal(20)
        meas_trigger = Signal()
        self.sync += [
            meas_trigger.eq(0),
            If(self.measure,
                cycles.eq(cycles + 1),
                If(self.clk128_strobe,
                    If(div >= self.n - 1,
                        div.eq(0),
                        self.cts_measured.eq(cycles + 1),
                        cycles.eq(0),
                        meas_trigger.eq(1),
                    ).Else(
                        div.eq(div + 1),
                    ),
                ),
            ).Else(
                div.eq(0), cycles.eq(0),
            ),
        ]

        cts = Signal(20)
        self.comb += cts.eq(Mux(self.measure, self.cts_measured, self.cts))
        sub = Cat(C(0, 8), cts[16:20], C(0, 4), cts[8:16], cts[0:8], self.n[16:20], C(0, 4), self.n[8:16], self.n[0:8])
        self.holder = _PacketHolder(C(PacketType.ACR, 24), [sub] * 4)
        trigger = Signal()
        self.comb += [
            trigger.eq(Mux(self.measure, meas_trigger, const_trigger)),
            self.holder.trigger.eq(trigger),
            self.holder.source.connect(self.source),
        ]
        self.sync += If(trigger, self.acr_count.eq(self.acr_count + 1))
