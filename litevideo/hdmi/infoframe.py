#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""InfoFrame and General Control Packet generators.

An InfoFrame packet (HDMI 1.3 §5.3.5, Tables 5-14/5-15) has HB0 = type,
HB1 = version, HB2 = length and PB0 = checksum, chosen so that the byte-wise
sum of the three header bytes and all payload bytes is zero. The AVI
InfoFrame fields are CEA-861-D §6.4 Tables 7 to 12 (version 2, 13 bytes; the
YQ and CN bits of data byte 5 are CEA-861-E additions and are 0 for 861-D).
The General Control Packet (§5.3.6, Tables 5-16/5-17) carries AVMUTE and
colour depth in four identical subpackets.

Each generator emits one packet per ``trigger`` pulse and holds it valid
until the scheduler accepts it. A new trigger while a packet is pending
replaces it (InfoFrames describe the current state, so the latest wins).
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *

# AVI InfoFrame fields, CEA-861-D Table 8 to Table 12 order.
avi_fields_layout = [
    ("y",   2), ("a", 1), ("b", 2), ("s", 2),          # PB1
    ("c",   2), ("m", 2), ("r", 4),                    # PB2
    ("itc", 1), ("ec", 3), ("q", 2), ("sc", 2),        # PB3
    ("vic", 7),                                        # PB4
    ("yq",  2), ("cn", 2), ("pr", 4),                  # PB5 (YQ/CN are CEA-861-E additions, 0 in 861-D)
    ("bar_top", 16), ("bar_bottom", 16), ("bar_left", 16), ("bar_right", 16),   # PB6..PB13
]


class _PacketHolder(LiteXModule):
    """Latches the packet expressions on ``trigger`` and presents the packet
    on ``source`` until accepted."""
    def __init__(self, header, subs):
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        self.sync += [
            If(self.trigger,
                self.source.valid.eq(1),
                self.source.header.eq(header),
                *[getattr(self.source, f"sub{k}").eq(subs[k]) for k in range(4)],
            ).Elif(self.source.ready,
                self.source.valid.eq(0),
            ),
        ]


class AVIInfoFrameGenerator(LiteXModule):
    def __init__(self):
        self.fields  = Record(avi_fields_layout)
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        f = self.fields
        db = [
            Cat(f.s, f.b, f.a, f.y, C(0, 1)),          # PB1
            Cat(f.r, f.m, f.c),                        # PB2
            Cat(f.sc, f.q, f.ec, f.itc),               # PB3
            Cat(f.vic, C(0, 1)),                       # PB4
            Cat(f.pr, f.cn, f.yq),                     # PB5
            f.bar_top[:8], f.bar_top[8:], f.bar_bottom[:8], f.bar_bottom[8:],
            f.bar_left[:8], f.bar_left[8:], f.bar_right[:8], f.bar_right[8:],
        ]
        header_bytes = [C(PacketType.AVI_INFOFRAME, 8), C(2, 8), C(13, 8)]
        total = Signal(12)
        self.comb += total.eq(sum(header_bytes) + sum(db))
        checksum = Signal(8)
        self.comb += checksum.eq(-total)
        payload = [checksum] + db + [C(0, 8)] * (27 - 13)
        subs = [Cat(*payload[7 * k:7 * k + 7]) for k in range(4)]
        self.holder = _PacketHolder(Cat(*header_bytes), subs)
        self.comb += [self.holder.trigger.eq(self.trigger), self.holder.source.connect(self.source)]


class GCPGenerator(LiteXModule):
    def __init__(self):
        self.avmute  = Signal()
        self.cd      = Signal(4)     # colour depth, 0 = not indicated (24 bit)
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        avmute_d = Signal()
        set_mute = Signal()
        clear_mute = Signal()
        self.sync += If(self.trigger, avmute_d.eq(self.avmute))
        self.comb += [
            set_mute.eq(self.avmute),
            clear_mute.eq(~self.avmute & avmute_d),
        ]
        sb0 = Cat(set_mute, C(0, 3), clear_mute, C(0, 3))
        sb1 = Cat(self.cd, C(0, 4))
        sub = Cat(sb0, sb1, C(0, 40))
        self.holder = _PacketHolder(C(PacketType.GCP, 24), [sub] * 4)
        self.comb += [
            self.holder.trigger.eq(self.trigger & (set_mute | clear_mute)),
            self.holder.source.connect(self.source),
        ]
