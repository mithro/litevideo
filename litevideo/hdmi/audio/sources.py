#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""PCM sources for the transmitter.

``ToneGenerator`` produces an ``audio_frame_layout`` stream (one left/right
pair per audio frame) at ``fs`` from the pixel clock with a 32-bit rate
accumulator (long-term rate exact to 2^-32) and a 256-entry sine ROM read by
a 32-bit phase accumulator, so a host can predict every sample
(``model.tone_sequence``). Both increments are inputs so a CSR can retune
them. If the consumer is not ready when a frame is due, the frame is dropped
and counted in ``overruns``.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio.model import tone_table, TONE_TABLE_BITS


def rate_increment(pix_clk_freq, fs):
    return round(fs / pix_clk_freq * (1 << 32))


def tone_increment(freq, fs):
    return round(freq / fs * (1 << 32))


class ToneGenerator(LiteXModule):
    def __init__(self, pix_clk_freq, fs=48000, freq=1000.0, amplitude=0.5):
        self.source = stream.Endpoint(audio_frame_layout)
        self.enable         = Signal(reset=1)
        self.rate_increment = Signal(32, reset=rate_increment(pix_clk_freq, fs))
        self.tone_increment = Signal(32, reset=tone_increment(freq, fs))
        self.overruns       = Signal(32)
        self.frames         = Signal(32)

        # # #

        table = tone_table(amplitude=amplitude)
        rom = Memory(24, len(table), init=table, name="tone_rom")
        port = rom.get_port()                       # synchronous read, 1 cycle
        self.specials += rom, port

        rate_acc = Signal(32)
        rate_carry = Signal()
        phase = Signal(32)
        self.sync += Cat(rate_acc, rate_carry).eq(rate_acc + self.rate_increment)

        due = Signal()                    # a frame is due this cycle
        self.comb += due.eq(rate_carry & self.enable)
        self.comb += port.adr.eq(phase[32 - TONE_TABLE_BITS:])

        # Pipeline: due -> (ROM read) -> load the output register.
        due_r = Signal()
        self.sync += [
            due_r.eq(due),
            If(due, phase.eq(phase + self.tone_increment)),
        ]
        src = self.source
        self.sync += [
            If(src.valid & src.ready, src.valid.eq(0)),
            If(due_r,
                If(src.valid & ~src.ready,
                    self.overruns.eq(self.overruns + 1),
                ).Else(
                    src.valid.eq(1),
                    src.left.eq(port.dat_r),
                    src.right.eq(port.dat_r),
                    self.frames.eq(self.frames + 1),
                ),
            ),
        ]
