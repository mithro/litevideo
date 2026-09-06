#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMITransmitter -> HDMIReceiver: timing, AVI InfoFrame capture, counters."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi.transmitter import HDMITransmitter
from litevideo.hdmi.receiver import HDMIReceiver

from test.common import stream_inserter
from test.test_hdmi_framer import TIMING, video_beats, LINE, VTOTAL


class DUT(Module):
    def __init__(self):
        self.submodules.tx = ClockDomainsRenamer({"pix": "sys"})(HDMITransmitter(default_vic=4))
        self.submodules.rx = ClockDomainsRenamer({"pix": "sys"})(HDMIReceiver(with_audio=False))
        self.comb += self.tx.source.connect(self.rx.sink)


class TestHDMIReceiver(unittest.TestCase):
    def test_timing_and_avi(self):
        dut = DUT()
        beats = video_beats(TIMING, 4)
        st = {}

        def setup():
            # avi_config storage bits: y@0(2) a@2 b@3(2) s@5(2) c@7(2) m@9(2) r@11(4) itc@15 ec@16(3) q@19(2) sc@21(2) vic@23(7)
            yield dut.tx.avi_config.storage.eq((2 << 0) | (2 << 7) | (2 << 9) | (8 << 11) | (16 << 23))  # y=2 c=2 m=2 r=8 vic=16
            for _ in range(len(beats) + 60):
                yield
            for name in ("hactive", "vactive", "synced"):
                st[name] = (yield getattr(dut.rx.status.fields, name))
            for name in ("htotal", "vtotal"):
                st[name] = (yield getattr(dut.rx.timing.fields, name))
            for name in ("y", "c", "q", "vic", "m", "valid", "checksum_ok"):
                st["avi_" + name] = (yield getattr(dut.rx.avi.fields, name))
            for name in ("frames", "islands", "packets", "ecc_errors", "period_errors", "avi_count"):
                st[name] = (yield getattr(dut.rx, name).status)

        run_simulation(dut, [setup(), stream_inserter(dut.tx.sink, beats, drain=60)])
        self.assertEqual((st["hactive"], st["vactive"]), (TIMING["hactive"], TIMING["vactive"]))
        self.assertEqual((st["htotal"], st["vtotal"]), (LINE, VTOTAL))
        self.assertEqual((st["avi_y"], st["avi_c"], st["avi_m"], st["avi_vic"]), (2, 2, 2, 16))
        self.assertEqual((st["avi_valid"], st["avi_checksum_ok"]), (1, 1))
        self.assertEqual(st["ecc_errors"], 0)
        self.assertEqual(st["period_errors"], 0)
        self.assertGreaterEqual(st["avi_count"], 3)
        self.assertEqual(st["packets"], st["avi_count"])
        self.assertEqual(st["frames"], 4)

    def run_format(self, avi_storage, convert=True):
        """Transmit 2 frames with ``avi_config`` = ``avi_storage``; return
        (rx converted lines, rx raw wire lines, input lines) as (r, g, b) tuples."""
        dut = DUT()
        beats = video_beats(TIMING, 2)
        inputs, cur_in = [], []
        for b in beats:
            if b["de"]:
                cur_in.append((b["r"], b["g"], b["b"]))
            elif cur_in:
                inputs.append(cur_in); cur_in = []
        conv_lines, raw_lines, cc, cr = [], [], [], []

        @passive
        def collect():
            while True:
                for src, lines, cur in ((dut.rx.source, conv_lines, cc), (dut.rx.raw_source, raw_lines, cr)):
                    if (yield src.de):
                        cur.append(((yield src.r), (yield src.g), (yield src.b)))
                    elif cur:
                        lines.append(list(cur)); cur.clear()
                yield

        def control():
            yield dut.tx.avi_config.storage.eq(avi_storage)
            yield dut.rx.control.storage.eq(0b10 if convert else 0b00)
            yield

        run_simulation(dut, [stream_inserter(dut.tx.sink, beats, drain=80), collect(), control()])
        return conv_lines, raw_lines, inputs

    def test_convert_back_to_rgb(self):
        from litevideo.csc.convert import PixelFormat, convert_line
        f = HDMITransmitter(default_vic=4).avi_config.fields
        def storage(y, c, q, vic=4):
            return (y << f.y.offset) | (c << f.c.offset) | (q << f.q.offset) | (2 << f.m.offset) | (8 << f.r.offset) | (vic << f.vic.offset)
        cases = [  # (y, c, q) -> (fmt, colorimetry, rgb_limited, ycc_limited) the receiver must infer
            ((2, 2, 0), (PixelFormat.YCBCR444, 2, 1, 1)),
            ((1, 1, 0), (PixelFormat.YCBCR422, 1, 1, 1)),
            ((0, 0, 1), (PixelFormat.RGB, 2, 1, 1)),
            ((2, 0, 0), (PixelFormat.YCBCR444, 2, 1, 1)),   # C=0 on 720p -> BT.709
        ]
        for (y, c, q), (fmt, col, rgb_l, ycc_l) in cases:
            conv_lines, raw_lines, inputs = self.run_format(storage(y, c, q))
            # Frame 0 has no AVI InfoFrame yet (no island slot before timing is known), so
            # compare the last frame's lines: the AVI has been latched by then.
            n = TIMING["vactive"]
            self.assertGreaterEqual(len(conv_lines), 2 * n)
            for line_in, line_raw, line_rx in zip(inputs[-n:], raw_lines[-n:], conv_lines[-n:]):
                wire = [(b, g, r) for r, g, b in line_raw]
                expected = convert_line(wire, fmt, PixelFormat.RGB, col, rgb_l, 0, ycc_l)
                self.assertEqual([(r, g, b) for b, g, r in expected], line_rx, (y, c, q))
                if fmt in (PixelFormat.YCBCR444, PixelFormat.RGB):
                    # full round trip through limited-range quantization: within 2 codes
                    for a, b in zip(line_in, line_rx):
                        self.assertTrue(all(abs(u - v) <= 2 for u, v in zip(a, b)), (y, c, q, a, b))

    def test_convert_disabled_passes_wire_values(self):
        f = HDMITransmitter(default_vic=4).avi_config.fields
        conv_lines, raw_lines, _ = self.run_format((2 << f.y.offset) | (2 << f.c.offset) | (4 << f.vic.offset), convert=False)
        self.assertEqual(conv_lines, raw_lines)
