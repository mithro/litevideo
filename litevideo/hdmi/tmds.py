#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-channel TMDS character classification and decoding.

One 10-bit character per cycle in, one cycle later out: the 8-bit video data
(DVI 1.0 §3.3), the 2-bit control value and ``control`` flag (HDMI 1.3
§5.4.2), the guard band flags (Tables 5-5 and 5-6) and the TERC4 word with its
validity (§5.4.3). Which flag matters is decided by ``HDMIPeriodDecoder``.
"""

from migen import *

from litex.gen import *

from litevideo.hdmi.common import *


class TMDSCharacterDecoder(LiteXModule):
    def __init__(self, channel):
        assert channel in (0, 1, 2)
        self.raw = Signal(10)

        self.d           = Signal(8)
        self.c           = Signal(2)
        self.control     = Signal()
        self.video_gb    = Signal()
        self.data_gb     = Signal()
        self.terc4       = Signal(4)
        self.terc4_valid = Signal()

        # # #

        raw = self.raw

        # Video data: undo the optional inversion (bit 9) then the XOR/XNOR chain (bit 8).
        data = Signal(8)
        self.comb += data.eq(Mux(raw[9], ~raw[:8], raw[:8]))
        self.sync += self.d[0].eq(data[0])
        for i in range(1, 8):
            self.sync += self.d[i].eq(data[i] ^ data[i - 1] ^ ~raw[8])

        # Control characters.
        self.sync += self.control.eq(0)
        for i, token in enumerate(control_tokens):
            self.sync += If(raw == token, self.control.eq(1), self.c.eq(i))

        # Guard bands.
        self.sync += self.video_gb.eq(raw == video_gb_tokens[channel])
        self.sync += self.data_gb.eq(0 if channel == 0 else (raw == data_gb_token))

        # TERC4.
        self.sync += self.terc4_valid.eq(0)
        for n, token in enumerate(terc4_tokens):
            self.sync += If(raw == token, self.terc4_valid.eq(1), self.terc4.eq(n))
