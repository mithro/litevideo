#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Constants and the pure-Python golden model of the HDMI link layer."""

import random
import unittest

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.bch import bch_ecc


def transitions(token):
    return sum(((token >> i) ^ (token >> (i + 1))) & 1 for i in range(9))


class TestTokens(unittest.TestCase):
    def test_control_tokens_have_at_least_seven_transitions(self):
        # HDMI 1.3 §5.2.1.2: control characters have "seven or more
        # transitions" (two of the four have eight).
        for t in control_tokens:
            self.assertGreaterEqual(transitions(t), 7)

    def test_terc4_tokens_unique_and_not_control(self):
        self.assertEqual(len(set(terc4_tokens)), 16)
        self.assertFalse(set(terc4_tokens) & set(control_tokens))

    def test_guard_band_values(self):
        # HDMI 1.3 Table 5-5 / Table 5-6
        self.assertEqual(video_gb_tokens, [0b1011001100, 0b0100110011, 0b1011001100])
        self.assertEqual(data_gb_token, 0b0100110011)
        self.assertEqual(data_gb_ch0_nibble(hsync=0, vsync=0), 0xC)
        self.assertEqual(data_gb_ch0_nibble(hsync=1, vsync=1), 0xF)

    def test_period_constants(self):
        # HDMI 1.3 §5.2.3.2, Table 5-4
        self.assertEqual(PREAMBLE_LENGTH, 8)
        self.assertEqual(GUARD_BAND_LENGTH, 2)
        self.assertEqual(PACKET_LENGTH, 32)
        self.assertEqual(MAX_PACKETS_PER_ISLAND, 18)
        self.assertEqual(MIN_CONTROL_PERIOD, 12)
        self.assertEqual(MIN_EXTENDED_CONTROL_PERIOD, 32)


class TestTMDSModel(unittest.TestCase):
    def test_control_and_data_roundtrip(self):
        prng = random.Random(3)
        cnt = 0
        for _ in range(2000):
            de = prng.randrange(2)
            d = prng.randrange(256)
            c = prng.randrange(4)
            token, cnt = model.tmds_encode(d, c, de, cnt)
            dd, cc, dde = model.tmds_decode(token)
            self.assertEqual(dde, de)
            if de:
                self.assertEqual(dd, d)
            else:
                self.assertEqual(cc, c)
                self.assertEqual(cnt, 0)

    def test_dc_balance_bounded(self):
        # DVI 1.0 §3.2.2: the running disparity stays within +/-10 bits.
        prng = random.Random(4)
        cnt = 0
        for _ in range(5000):
            _, cnt = model.tmds_encode(prng.randrange(256), 0, 1, cnt)
            self.assertLessEqual(abs(cnt), 10)

    def test_terc4_roundtrip(self):
        for n in range(16):
            self.assertEqual(model.terc4_decode(model.terc4_encode(n)), n)
        self.assertIsNone(model.terc4_decode(control_tokens[0]))


class TestPacketModel(unittest.TestCase):
    def test_header_and_subpacket_words(self):
        p = model.Packet([0x01, 0x00, 0x00], [[0, 0, 1, 0x22, 0x0A, 0, 0x18]] * 4)
        self.assertEqual(p.header, 0x000001)
        self.assertEqual(p.header_ecc, bch_ecc([1, 0, 0]))
        # bytes [0x00,0x00,0x01,0x22,0x0A,0x00,0x18] little-endian
        self.assertEqual(p.subpackets[0], 0x18000A22010000)
        self.assertEqual(p.subpacket_ecc[0], bch_ecc([0, 0, 1, 0x22, 0x0A, 0, 0x18]))

    def test_null_packet(self):
        p = model.Packet.null()
        self.assertEqual(p.header, 0)
        self.assertEqual(p.subpackets, [0, 0, 0, 0])

    def test_packet_chars_bit_mapping(self):
        # §5.2.3.4: header bit c on ch0 bit 2; subpacket k bit 2c on ch1 bit k,
        # bit 2c+1 on ch2 bit k; ECC bits follow the data bits.
        p = model.Packet([0xA5, 0x3C, 0x0F], [[i * 7 + k for i in range(7)] for k in range(4)])
        chars = model.packet_chars(p)
        self.assertEqual(len(chars), 32)
        full_header = p.header | (p.header_ecc << 24)
        full_subs = [p.subpackets[k] | (p.subpacket_ecc[k] << 56) for k in range(4)]
        for c, (hbit, n1, n2) in enumerate(chars):
            self.assertEqual(hbit, (full_header >> c) & 1)
            for k in range(4):
                self.assertEqual((n1 >> k) & 1, (full_subs[k] >> (2 * c)) & 1)
                self.assertEqual((n2 >> k) & 1, (full_subs[k] >> (2 * c + 1)) & 1)


class TestIslandModel(unittest.TestCase):
    def test_island_framing(self):
        p = model.Packet.null()
        toks = model.island_tokens([p, p], hsync=1, vsync=0)
        self.assertEqual(len(toks), 8 + 2 + 64 + 2)
        # preamble: ch0 control(hsync,vsync), ch1/ch2 CTL0=1/CTL2=1
        self.assertEqual(toks[0], (control_tokens[0b01], control_tokens[0b01], control_tokens[0b01]))
        # leading guard band: ch0 TERC4(0b11,vsync,hsync), ch1/2 data GB
        self.assertEqual(toks[8], (terc4_tokens[0b1101], data_gb_token, data_gb_token))
        # first packet character: ch0 bit3 = 0, others bit3 = 1 (HDMI 1.4b CTS)
        self.assertEqual(model.terc4_decode(toks[10][0]) >> 3, 0)
        for t in toks[11:74]:
            self.assertEqual(model.terc4_decode(t[0]) >> 3, 1)
        self.assertEqual(toks[-1], (terc4_tokens[0b1101], data_gb_token, data_gb_token))

    def test_line_tokens_periods(self):
        # blanking needs 12 control + (8+2+32+2) island + 4 control + 8 preamble + 2 guard = 70
        line, periods = model.line_tokens(hactive=16, hblank=80, packets=[model.Packet.null()], hsync_start=4, hsync_len=8)
        self.assertEqual(len(line), 96)
        self.assertEqual(len(periods), 96)
        self.assertEqual(periods[:16], [Period.VIDEO] * 16)
        self.assertIn(Period.DATA_ISLAND, periods)
        self.assertEqual(periods[-10:-2], [Period.VIDEO_PREAMBLE] * 8)
        self.assertEqual(periods[-2:], [Period.VIDEO_GUARD] * 2)
