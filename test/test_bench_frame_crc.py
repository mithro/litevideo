#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""bench/netv2/frame_crc: gateware CRC-32 per frame equals the Python reference
and the reference equals zlib's CRC-32 over the packed 24-bit pixels."""

import random
import unittest
import zlib

from migen import *

from bench.netv2.frame_crc import FrameCRC, frame_crc


class TestFrameCRC(unittest.TestCase):
    def test_reference_matches_zlib(self):
        prng = random.Random(51)
        pixels = [(prng.randrange(256), prng.randrange(256), prng.randrange(256)) for _ in range(300)]
        packed = b"".join(bytes((r, g, b)) for r, g, b in pixels)
        self.assertEqual(frame_crc(pixels), zlib.crc32(packed))
        # A known vector: zlib.crc32(b"123456789") == 0xCBF43926 (CRC-32/ISO-HDLC check value).
        self.assertEqual(frame_crc([(0x31, 0x32, 0x33), (0x34, 0x35, 0x36), (0x37, 0x38, 0x39)]), 0xCBF43926)

    def test_gateware_matches_reference(self):
        prng = random.Random(52)
        frames = [[(prng.randrange(256), prng.randrange(256), prng.randrange(256)) for _ in range(40)] for _ in range(3)]
        dut = FrameCRC()
        got = []

        def gen():
            for frame in frames:
                # blanking with a VSYNC pulse (latches the previous frame's CRC)
                yield dut.de.eq(0)
                yield dut.vsync.eq(1)
                yield
                yield dut.vsync.eq(0)
                for _ in range(3):
                    yield
                for r, g, b in frame:
                    yield dut.de.eq(1); yield dut.r.eq(r); yield dut.g.eq(g); yield dut.b.eq(b)
                    yield
                yield dut.de.eq(0)
                for _ in range(3):
                    yield
            yield dut.vsync.eq(1)
            yield
            yield dut.vsync.eq(0)
            yield
            got.append((yield dut.crc))
            got.append((yield dut.frame))

        run_simulation(dut, gen())
        self.assertEqual(got, [frame_crc(frames[-1]), 4])
