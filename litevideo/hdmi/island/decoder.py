#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Data island packet reassembly with BCH ECC check.

Consumes the per-character island nibbles of ``HDMIPeriodDecoder`` and emits
one ``packet_rx_layout`` beat per 32-character packet (HDMI 1.3 §5.2.3.4):
channel 0 bit 2 carries the header (24 data bits then 8 ECC bits, LSB first);
channel 1 bit k and channel 2 bit k carry BCH block k (56 data bits then 8 ECC
bits, two bits per character, channel 1 first). The five ECCs are recomputed
serially with ``bch_step`` while the packet streams by and compared with the
received ones at character 31 (§5.2.3.5). The source has no back-pressure;
an integrator that cannot keep up drops packets and should count them.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_step


class DataIslandDecoder(LiteXModule):
    def __init__(self):
        self.active  = Signal()     # a packet character is present on the nibbles
        self.first   = Signal()     # ... and it is the first character of the island
        self.nibble0 = Signal(4)
        self.nibble1 = Signal(4)
        self.nibble2 = Signal(4)

        self.source = stream.Endpoint(packet_rx_layout)
        self.island_count    = Signal(32)
        self.packet_count    = Signal(32)
        self.ecc_error_count = Signal(32)

        # # #

        char = Signal(5)
        hbit = self.nibble0[2]

        self.sync += If(self.active & self.first, self.island_count.eq(self.island_count + 1))

        # Character counter: restarts at the first character of an island, wraps every 32.
        self.sync += If(~self.active, char.eq(0)).Elif(self.first, char.eq(1)).Else(char.eq(char + 1))
        index = Signal(5)
        self.comb += index.eq(Mux(self.first, 0, char))

        # Shift registers for received bits.
        header  = Signal(24)
        hecc_rx = Signal(8)
        subs    = [Signal(56) for _ in range(4)]
        secc_rx = [Signal(8) for _ in range(4)]
        self.sync += If(self.active,
            If(index < 24, header.eq(Cat(header[1:], hbit))).Else(hecc_rx.eq(Cat(hecc_rx[1:], hbit))),
        )
        for k in range(4):
            bits = Cat(self.nibble1[k], self.nibble2[k])
            self.sync += If(self.active,
                If(index < 28, subs[k].eq(Cat(subs[k][2:], bits))).Else(secc_rx[k].eq(Cat(secc_rx[k][2:], bits))),
            )

        # Serial ECC over the data bits (reset at character 0).
        hecc = Signal(8)
        secc = [Signal(8) for _ in range(4)]
        hbase = Mux(index == 0, 0, hecc)
        self.sync += If(self.active & (index < 24), hecc.eq(bch_step(hbase, hbit)))
        for k in range(4):
            base = Mux(index == 0, 0, secc[k])
            self.sync += If(self.active & (index < 28),
                secc[k].eq(bch_step(bch_step(base, self.nibble1[k]), self.nibble2[k])))

        # Emit at the cycle after character 31.
        done = Signal()
        self.sync += done.eq(self.active & (index == 31))
        ecc_ok = (hecc == hecc_rx)
        for k in range(4):
            ecc_ok = ecc_ok & (secc[k] == secc_rx[k])
        self.comb += [
            self.source.valid.eq(done),
            self.source.header.eq(header),
            self.source.ecc_ok.eq(ecc_ok),
        ]
        for k in range(4):
            self.comb += getattr(self.source, f"sub{k}").eq(subs[k])
        self.sync += If(done,
            self.packet_count.eq(self.packet_count + 1),
            If(~ecc_ok, self.ecc_error_count.eq(self.ecc_error_count + 1)),
        )
