#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio InfoFrame generator (CEA-861-D §6.6, Tables 16 to 22; HDMI 1.3 §8.2.2).

HB0 = 0x84, HB1 = 1, HB2 = 10; PB1 = CT<<4 | CC, PB2 = SF<<2 | SS, PB3 = 0
(coding-type dependent, 0 for L-PCM), PB4 = CA (speaker allocation),
PB5 = DM_INH<<7 | LSV<<3, PB6..PB10 = 0; PB0 = checksum. One packet per
``trigger`` (the transmitter triggers once per frame while audio is on,
which meets "once per VSYNC period while digital audio is being sent").
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.infoframe import _PacketHolder

audio_infoframe_fields_layout = [
    ("cc", 3), ("ct", 4),          # PB1
    ("ss", 2), ("sf", 3),          # PB2
    ("ca", 8),                     # PB4
    ("lsv", 4), ("dm_inh", 1),     # PB5
]


class AudioInfoFrameGenerator(LiteXModule):
    def __init__(self):
        self.fields  = Record(audio_infoframe_fields_layout)
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        f = self.fields
        db = [
            Cat(f.cc, C(0, 1), f.ct),            # PB1
            Cat(f.ss, f.sf, C(0, 3)),            # PB2
            C(0, 8),                             # PB3
            f.ca,                                # PB4
            Cat(C(0, 3), f.lsv, f.dm_inh),       # PB5
            C(0, 8), C(0, 8), C(0, 8), C(0, 8), C(0, 8),
        ]
        header_bytes = [C(PacketType.AUDIO_INFOFRAME, 8), C(1, 8), C(10, 8)]
        total = Signal(12)
        self.comb += total.eq(sum(header_bytes) + sum(db))
        checksum = Signal(8)
        self.comb += checksum.eq(-total)
        payload = [checksum] + db + [C(0, 8)] * (27 - 10)
        subs = [Cat(*payload[7 * k:7 * k + 7]) for k in range(4)]
        self.holder = _PacketHolder(Cat(*header_bytes), subs)
        self.comb += [self.holder.trigger.eq(self.trigger), self.holder.source.connect(self.source)]
