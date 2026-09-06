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
