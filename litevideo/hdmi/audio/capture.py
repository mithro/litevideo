#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""CSR-readable one-shot capture of extracted audio subframes.

Software writes ``arm``: the FIFO is cleared and then fills once,
contiguously, with the next ``depth`` subframes from ``sink`` (``pix``
domain) and stops. Software drains it over ``sample_data`` /
``sample_valid`` / ``sample_pop`` (``sys`` domain). A free-running FIFO that
overflows lets single subframes in at every pop, so its content is not a
contiguous stream; the arm/stop discipline is what makes the captured block
analysable (channel alternation, IEC 60958 block structure, a tone FFT).

The clear is a reset of the asynchronous FIFO held for 16 ``sys`` cycles so
both clock domains see it.
"""

from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fifo import AsyncFIFO

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import *

from litevideo.hdmi.audio.common import audio_sample_layout


class AudioSampleCapture(LiteXModule):
    def __init__(self, depth=512):
        self.sink = stream.Endpoint(audio_sample_layout)

        self.arm          = CSRStorage(1, description="Write to clear the FIFO and capture the next block of subframes.")
        self.sample_data  = CSRStatus(32, description="Captured subframe: sample[23:0], channel[26:24], b[27], c[28], p[29], v[30], 1[31].")
        self.sample_valid = CSRStatus(1, description="The FIFO has data.")
        self.sample_pop   = CSRStorage(1, description="Write to pop the FIFO.")
        self.status       = CSRStatus(fields=[
            CSRField("armed", 1, description="Capture in progress (FIFO not yet full)."),
            CSRField("count", 16, description="Subframes captured since the last arm."),
        ])

        # # #

        # Reset held long enough for the pix side; arm follows the reset.
        rst_cnt = Signal(5)
        rst = Signal()
        self.sync += [
            If(self.arm.re, rst_cnt.eq(16)).Elif(rst_cnt != 0, rst_cnt.eq(rst_cnt - 1)),
            rst.eq(rst_cnt != 0),
        ]
        rst_pix = Signal()
        self.specials += MultiReg(rst, rst_pix, "pix")
        fifo = ClockDomainsRenamer({"write": "pix", "read": "sys"})(
            ResetInserter(["write", "read"])(AsyncFIFO(width=32, depth=depth)))
        self.fifo = fifo
        self.comb += [fifo.reset_write.eq(rst_pix), fifo.reset_read.eq(rst)]

        armed = Signal()
        count = Signal(16)
        rst_pix_r = Signal()
        self.sync.pix += rst_pix_r.eq(rst_pix)
        s = self.sink
        self.comb += [
            s.ready.eq(1),
            fifo.din.eq(Cat(s.sample, s.channel, s.b, s.c, s.p, s.v, C(1, 1))),
            fifo.we.eq(s.valid & armed & fifo.writable),
        ]
        self.sync.pix += [
            If(rst_pix_r & ~rst_pix,          # reset released: start capturing
                armed.eq(1),
                count.eq(0),
            ).Elif(armed & s.valid,
                If(fifo.writable,
                    count.eq(count + 1),
                ).Else(
                    armed.eq(0),
                ),
            ),
        ]
        self.comb += [
            self.sample_data.status.eq(fifo.dout),
            self.sample_valid.status.eq(fifo.readable),
            fifo.re.eq(self.sample_pop.re),
        ]
        self.specials += [
            MultiReg(armed, self.status.fields.armed),
            MultiReg(count, self.status.fields.count),
        ]
