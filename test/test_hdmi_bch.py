#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI data island BCH ECC.

Vectors were produced by two independent implementations that agree: the
reflected LFSR of hdl-util/hdmi (src/packet_assembler.sv, mask 8'b10000011)
and polynomial long division by G(x) = x^8 + x^7 + x^6 + 1 (HDMI 1.3
§5.2.3.5: "G(x)=1+x6+x7+x8").
"""

import random
import unittest

from migen import *

from litevideo.hdmi.bch import bch_ecc, bch_step, BCH_LFSR_MASK

VECTORS = [
    ([0x00, 0x00, 0x00], 0x00),
    ([0x01, 0x00, 0x00], 0x4A),   # ACR header
    ([0x02, 0x01, 0x00], 0x65),   # ASP header, subpacket 0 present
    ([0x82, 0x02, 0x0D], 0xE4),   # AVI InfoFrame header
    ([0x84, 0x01, 0x0A], 0x4A),   # Audio InfoFrame header
    ([0xFF, 0xFF, 0xFF], 0x39),
    ([0x00] * 7, 0x00),
    ([0x00, 0x00, 0x01, 0x22, 0x0A, 0x00, 0x18], 0xB9),
    ([1, 2, 3, 4, 5, 6, 7], 0xB2),
    ([0xA5, 0x5A, 0xC3, 0x3C, 0xF0, 0x0F, 0x81], 0xE4),
]


class TestBCHModel(unittest.TestCase):
    def test_mask_is_reflected_polynomial(self):
        self.assertEqual(BCH_LFSR_MASK, 0x83)

    def test_vectors(self):
        for data, ecc in VECTORS:
            self.assertEqual(bch_ecc(data), ecc, data)

    def test_polynomial_division_agrees(self):
        # Independent check: remainder of M(x)*x^8 mod G(x), bits LSB-first.
        G = 0x1C1
        prng = random.Random(1)
        for _ in range(200):
            data = [prng.randrange(256) for _ in range(prng.choice((3, 7)))]
            reg = 0
            for b in data:
                for i in range(8):
                    reg = (reg << 1) | ((b >> i) & 1)
                    if reg & 0x100:
                        reg ^= G
            for _ in range(8):
                reg <<= 1
                if reg & 0x100:
                    reg ^= G
            rem = reg & 0xFF
            reflected = int(f"{rem:08b}"[::-1], 2)
            self.assertEqual(bch_ecc(data), reflected)


class TestBCHGateware(unittest.TestCase):
    def test_serial_step_matches_model(self):
        class DUT(Module):
            def __init__(self):
                self.bit = Signal()
                self.clear = Signal()
                self.state = Signal(8)
                self.sync += If(self.clear, self.state.eq(0)).Else(self.state.eq(bch_step(self.state, self.bit)))

        prng = random.Random(2)
        cases = [[prng.randrange(256) for _ in range(prng.choice((3, 7)))] for _ in range(20)]
        results = []

        def gen(dut):
            for data in cases:
                yield dut.clear.eq(1)
                yield
                yield dut.clear.eq(0)
                for b in data:
                    for i in range(8):
                        yield dut.bit.eq((b >> i) & 1)
                        yield
                yield   # the last bit is registered on this edge
                results.append((yield dut.state))

        dut = DUT()
        run_simulation(dut, gen(dut))
        self.assertEqual(results, [bch_ecc(d) for d in cases])
