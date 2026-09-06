#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""AudioSampleCapture: arm, contiguous fill, stop when full, re-arm."""

import unittest

from migen import *

from litevideo.hdmi.audio.capture import AudioSampleCapture


class TestAudioSampleCapture(unittest.TestCase):
    def test_one_shot(self):
        dut = ClockDomainsRenamer({"pix": "sys"})(AudioSampleCapture(depth=16))
        drained = []

        @passive
        def source():
            # A subframe every 3 cycles, numbered, channel alternating.
            n = 0
            while True:
                yield dut.sink.valid.eq(1)
                yield dut.sink.sample.eq(n)
                yield dut.sink.channel.eq(n & 1)
                yield
                yield dut.sink.valid.eq(0)
                yield
                yield
                n += 1

        def drain(expect_count):
            words = []
            while (yield dut.sample_valid.status):
                words.append((yield dut.sample_data.status))
                yield dut.sample_pop.re.eq(1)
                yield
                yield dut.sample_pop.re.eq(0)
                yield
            return words

        def control():
            # Nothing captured before arming.
            for _ in range(60):
                yield
            self.assertEqual((yield dut.sample_valid.status), 0)
            # Arm: capture 16 contiguous subframes then stop.
            yield dut.arm.re.eq(1)
            yield
            yield dut.arm.re.eq(0)
            for _ in range(200):
                yield
            self.assertEqual((yield dut.status.fields.armed), 0)
            self.assertEqual((yield dut.status.fields.count), 16)
            words = yield from drain(16)
            samples = [w & 0xFFFFFF for w in words]
            self.assertEqual(len(samples), 16)
            self.assertEqual(samples, list(range(samples[0], samples[0] + 16)))
            self.assertTrue(all(w >> 31 for w in words))
            self.assertEqual([(w >> 24) & 7 for w in words], [s & 1 for s in samples])
            # Re-arm later: a fresh contiguous block, later samples.
            for _ in range(50):
                yield
            yield dut.arm.re.eq(1)
            yield
            yield dut.arm.re.eq(0)
            for _ in range(200):
                yield
            words2 = yield from drain(16)
            samples2 = [w & 0xFFFFFF for w in words2]
            self.assertEqual(samples2, list(range(samples2[0], samples2[0] + 16)))
            self.assertGreater(samples2[0], samples[-1])

        run_simulation(dut, [source(), control()])



class TestAudioSampleCaptureTwoClocks(unittest.TestCase):
    def test_pix_faster_than_sys(self):
        """The arm/reset handshake and the AsyncFIFO with genuinely different
        clocks: pix at 74.25 MHz (13.47 ns), sys at 50 MHz (20 ns)."""
        dut = AudioSampleCapture(depth=16)
        words = []

        @passive
        def source():
            n = 0
            while True:
                yield dut.sink.valid.eq(1)
                yield dut.sink.sample.eq(n)
                yield dut.sink.channel.eq(n & 1)
                yield
                yield dut.sink.valid.eq(0)
                for _ in range(4):
                    yield
                n += 1

        def control():
            for _ in range(40):
                yield
            yield dut.arm.re.eq(1)
            yield
            yield dut.arm.re.eq(0)
            for _ in range(400):
                yield
            self.assertEqual((yield dut.status.fields.armed), 0)
            self.assertEqual((yield dut.status.fields.count), 16)
            while (yield dut.sample_valid.status):
                words.append((yield dut.sample_data.status))
                yield dut.sample_pop.re.eq(1)
                yield
                yield dut.sample_pop.re.eq(0)
                yield
            samples = [w & 0xFFFFFF for w in words]
            self.assertEqual(len(samples), 16)
            self.assertEqual(samples, list(range(samples[0], samples[0] + 16)))

        run_simulation(dut, {"sys": control(), "pix": source()}, clocks={"sys": 20, "pix": 13.47})

if __name__ == "__main__":
    unittest.main()
