#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Model: InfoFrame / GCP builders and whole-frame character generation."""

import unittest

from litevideo.hdmi.common import *
from litevideo.hdmi import model


class TestInfoFrameModel(unittest.TestCase):
    def test_checksum_makes_sum_zero(self):
        p = model.infoframe_packet(PacketType.AVI_INFOFRAME, 2, [0x10, 0x28, 0x00, 0x04, 0x00] + [0] * 8)
        total = sum(p.header_bytes) + sum(b for s in p.subpacket_bytes for b in s)
        self.assertEqual(total & 0xFF, 0)
        self.assertEqual(p.header_bytes, [0x82, 0x02, 13])

    def test_avi_defaults(self):
        p = model.avi_infoframe(vic=4)
        # CEA-861-D Table 8..12: PB1 = {0, Y1 Y0, A0, B1 B0, S1 S0}; RGB, no bars, no scan info.
        self.assertEqual(p.subpacket_bytes[0][1], 0x00)
        # PB2 = {C1 C0, M1 M0, R3..R0}: colorimetry none, aspect 16:9 for VIC 4, active format same as picture.
        self.assertEqual(p.subpacket_bytes[0][2], 0x28)
        self.assertEqual(p.subpacket_bytes[0][4], 4)        # PB4 = VIC

    def test_gcp(self):
        p = model.gcp_packet(set_avmute=1)
        self.assertEqual(p.header_bytes, [0x03, 0, 0])
        self.assertEqual([s[0] for s in p.subpacket_bytes], [0x01] * 4)   # SB0 bit0 = Set_AVMUTE
        p = model.gcp_packet(clear_avmute=1)
        self.assertEqual([s[0] for s in p.subpacket_bytes], [0x10] * 4)   # SB0 bit4 = Clear_AVMUTE


class TestFrameModel(unittest.TestCase):
    def test_frame_tokens_shape(self):
        timing = dict(hactive=16, hfront=4, hsync=8, hback=20, vactive=2, vfront=1, vsync=1, vback=1)
        frames = model.frame_tokens(timing, nframes=1)
        line = 16 + 4 + 8 + 20
        self.assertEqual(len(frames), line * 5)
        # Video lines end with the video preamble and guard band before the next active line.
        first_line = frames[:line]
        self.assertEqual([t[:3] for t in first_line[-2:]], [tuple(video_gb_tokens)] * 2)
        self.assertEqual([t[3] for t in first_line[:16]], [1] * 16)

    def test_frame_tokens_island_uses_live_syncs(self):
        timing = dict(hactive=16, hfront=4, hsync=16, hback=60, vactive=1, vfront=0, vsync=1, vback=0)
        p = model.Packet.null()
        frames = model.frame_tokens(timing, nframes=1, islands={0: [p]})
        line = 16 + 4 + 16 + 60
        start = 16 + 4 + MIN_CONTROL_PERIOD
        island = frames[start:start + model.island_length(1)]
        # HSYNC ends 16 characters into blanking = 4 characters into the island.
        hs = [t[4] for t in island]
        self.assertEqual(hs[:4], [1] * 4)
        self.assertEqual(hs[4:], [0] * (len(hs) - 4))
        for c0, c1, c2, de, h, v in island[8:10] + island[-2:]:     # guard bands carry the syncs on ch0
            self.assertEqual(c0, model.terc4_encode(data_gb_ch0_nibble(h, v)))
