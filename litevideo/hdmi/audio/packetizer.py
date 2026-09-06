#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio Sample Packet packetizer (HDMI 1.3 §5.3.4, §7.6, layout 0).

Buffers up to four IEC 60958 frames (one left/right pair per ``sink`` beat)
and offers an Audio Sample Packet on ``source`` as soon as at least one
frame is buffered (§7.8.1). When the scheduler accepts the packet it carries
every buffered frame, ``sample_present`` filled contiguously from subpacket
0 (Table 7-7). Each subframe gets its IEC 60958-3 flags: V = 0 (valid),
U = 0, C from the consumer channel status block (192 frames, left and right
differ in the channel number field), P = even parity over the sample and
V/U/C; the B header bits mark the frame at block position 0 (Table 5-12).
``frame_strobe`` pulses once per frame taken from ``sink`` (for the ACR
generator).
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.audio.common import *


class AudioSamplePacketizer(LiteXModule):
    def __init__(self, fs=48000):
        self.sink   = stream.Endpoint(audio_frame_layout)
        self.source = stream.Endpoint(packet_layout)
        self.enable       = Signal(reset=1)
        self.frame_strobe = Signal()
        self.frames_sent  = Signal(32)

        # # #

        # Channel status ROMs, one bit per block position (Migen has no
        # signal-indexed bit select, so use an Array of constants).
        sl = channel_status_block(fs, IEC_CHANNEL_LEFT)
        sr = channel_status_block(fs, IEC_CHANNEL_RIGHT)
        status_l = Array([C((sl >> i) & 1, 1) for i in range(CHANNEL_STATUS_BITS)])
        status_r = Array([C((sr >> i) & 1, 1) for i in range(CHANNEL_STATUS_BITS)])
        bidx = Signal(max=CHANNEL_STATUS_BITS)      # IEC 60958 block position of the next frame

        left  = [Signal(24) for _ in range(4)]
        right = [Signal(24) for _ in range(4)]
        cl    = [Signal() for _ in range(4)]
        cr    = [Signal() for _ in range(4)]
        bflag = [Signal() for _ in range(4)]
        count = Signal(3)                           # buffered frames, 0..4

        emit = Signal()
        self.comb += [
            self.source.valid.eq((count != 0) & self.enable),
            emit.eq(self.source.valid & self.source.ready),
            self.sink.ready.eq((count != 4) & ~emit),
            self.frame_strobe.eq(self.sink.valid & self.sink.ready),
        ]

        # Load a frame into slot ``count``.
        load_cases = {}
        for k in range(4):
            load_cases[k] = [
                left[k].eq(self.sink.left), right[k].eq(self.sink.right),
                cl[k].eq(status_l[bidx]), cr[k].eq(status_r[bidx]),
                bflag[k].eq(bidx == 0),
            ]
        self.sync += [
            If(emit,
                count.eq(0),
                self.frames_sent.eq(self.frames_sent + count),
            ),
            If(self.sink.valid & self.sink.ready,
                Case(count, load_cases),
                count.eq(count + 1),
                If(bidx == CHANNEL_STATUS_BITS - 1, bidx.eq(0)).Else(bidx.eq(bidx + 1)),
            ),
        ]

        # Packet contents from the buffered frames.
        def parity(sample, c):
            bits = [sample[i] for i in range(24)] + [c]
            p = bits[0]
            for b in bits[1:]:
                p = p ^ b
            return p

        present = Signal(4)
        bbits = Signal(4)
        self.comb += present.eq((1 << count) - 1)
        for k in range(4):
            self.comb += bbits[k].eq(bflag[k] & present[k])
        self.comb += self.source.header.eq(Cat(C(PacketType.ASP, 8), Cat(present, C(0, 4)), Cat(C(0, 4), bbits)))
        for k in range(4):
            pl = parity(left[k], cl[k])
            pr = parity(right[k], cr[k])
            sb6 = Cat(C(0, 1), C(0, 1), cl[k], pl, C(0, 1), C(0, 1), cr[k], pr)   # VL UL CL PL VR UR CR PR
            sub = Cat(left[k], right[k], sb6)
            self.comb += getattr(self.source, f"sub{k}").eq(Mux(present[k], sub, 0))
