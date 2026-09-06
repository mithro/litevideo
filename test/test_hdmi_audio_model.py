#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio packet model: byte layouts against hand-built vectors."""

import unittest

from litevideo.hdmi.common import *
from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio import model as am


class TestChannelStatus(unittest.TestCase):
    def test_fields(self):
        s = channel_status_block(48000, IEC_CHANNEL_LEFT)
        self.assertEqual(s & 0b11, 0)                  # consumer, PCM
        self.assertEqual((s >> 2) & 1, 1)              # copyright not asserted
        self.assertEqual((s >> 20) & 0xF, 1)           # left channel
        self.assertEqual((s >> 24) & 0xF, 0x2)         # 48 kHz: bit 25 set
        self.assertEqual((s >> 32) & 0xF, 0xB)         # 24-bit word length
        r = channel_status_block(48000, IEC_CHANNEL_RIGHT)
        self.assertEqual(s ^ r, (1 ^ 2) << 20)         # differ only in the channel number
        self.assertLess(s, 1 << 40)


class TestASP(unittest.TestCase):
    def test_parity_is_even(self):
        for sample, v, u, c in ((0, 0, 0, 0), (1, 0, 0, 0), (0xFFFFFF, 1, 0, 0), (0x123456, 0, 1, 1)):
            p = am.parity(sample, v, u, c)
            ones = bin(sample).count("1") + v + u + c + p
            self.assertEqual(ones % 2, 0)

    def test_subpacket_layout(self):
        p, nxt = am.asp_packet([(0x123456, 0xABCDEF)], block_index=5)
        self.assertEqual(p.header_bytes[0], PacketType.ASP)
        self.assertEqual(p.header_bytes[1], 0b0001)              # sp0 present, layout 0
        self.assertEqual(p.header_bytes[2], 0x00)                # not block start
        self.assertEqual(p.subpacket_bytes[0][:6], [0x56, 0x34, 0x12, 0xEF, 0xCD, 0xAB])
        sb6 = p.subpacket_bytes[0][6]
        cl = (channel_status_block(48000, 1) >> 5) & 1
        cr = (channel_status_block(48000, 2) >> 5) & 1
        self.assertEqual((sb6 >> 2) & 1, cl)
        self.assertEqual((sb6 >> 6) & 1, cr)
        self.assertEqual((sb6 >> 3) & 1, am.parity(0x123456, 0, 0, cl))
        self.assertEqual((sb6 >> 7) & 1, am.parity(0xABCDEF, 0, 0, cr))
        self.assertEqual(sb6 & 0b11, 0)                          # V = U = 0 on the left
        self.assertEqual(nxt, 6)

    def test_block_start_and_wrap(self):
        p, nxt = am.asp_packet([(1, 1), (2, 2), (3, 3), (4, 4)], block_index=190)
        self.assertEqual(p.header_bytes[1], 0b1111)
        self.assertEqual(p.header_bytes[2] >> 4, 0b0100)         # frame index 192 -> 0 lands on subpacket 2
        self.assertEqual(nxt, 2)

    def test_unpack_roundtrip(self):
        frames = [(0x000001, 0xFFFFFF), (0x800000, 0x7FFFFF), (5, 6)]
        p, _ = am.asp_packet(frames, block_index=0)
        got = am.unpack_asp(p)
        self.assertEqual([(g["left"], g["right"]) for g in got], frames)
        self.assertEqual([g["b"] for g in got], [1, 0, 0])
        for g in got:
            self.assertEqual(g["pl"], am.parity(g["left"], g["vl"], g["ul"], g["cl"]))


class TestACRAndInfoFrame(unittest.TestCase):
    def test_acr_bytes(self):
        p = am.acr_packet(6144, 74250)
        self.assertEqual(p.header_bytes, [0x01, 0, 0])
        self.assertEqual(p.subpacket_bytes[0], [0x00, 0x01, 0x22, 0x0A, 0x00, 0x18, 0x00])
        self.assertEqual(p.subpacket_bytes[3], p.subpacket_bytes[0])
        self.assertEqual(am.unpack_acr(p), (6144, 74250))

    def test_audio_infoframe(self):
        p = am.audio_infoframe(cc=1, ct=0, sf=3, ss=3, ca=0)
        self.assertEqual(p.header_bytes, [0x84, 0x01, 10])
        total = sum(p.header_bytes) + sum(b for s in p.subpacket_bytes for b in s)
        self.assertEqual(total & 0xFF, 0)
        pb = p.subpacket_bytes[0]
        self.assertEqual(pb[1], 0x01)                 # PB1: CT=0, CC=1 (2 channels)
        self.assertEqual(pb[2], (3 << 2) | 3)         # PB2: SF=48 kHz, SS=24 bit
        self.assertEqual(pb[4], 0x00)                 # PB4: CA front L/R

    def test_n_cts_table(self):
        # fs = pix * N / (128 * CTS) must give back fs for every table entry.
        for (fs, pix), (n, cts) in N_CTS.items():
            self.assertAlmostEqual(pix * n / (128 * cts), fs, delta=0.5)
