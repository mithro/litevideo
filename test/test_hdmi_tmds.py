#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.tmds import TMDSCharacterDecoder


class TestTMDSCharacterDecoder(unittest.TestCase):
    def run_tokens(self, channel, tokens):
        dut = TMDSCharacterDecoder(channel)
        out = []

        def gen():
            for t in tokens + [0]:
                yield dut.raw.eq(t)
                yield
                out.append({
                    "d": (yield dut.d), "c": (yield dut.c), "control": (yield dut.control),
                    "video_gb": (yield dut.video_gb), "data_gb": (yield dut.data_gb),
                    "terc4": (yield dut.terc4), "terc4_valid": (yield dut.terc4_valid),
                })

        run_simulation(dut, gen())
        return out[1:]   # one cycle of latency

    def test_video_data(self):
        prng = random.Random(5)
        pixels = [prng.randrange(256) for _ in range(300)]
        cnt = 0
        tokens = []
        for p in pixels:
            t, cnt = model.tmds_encode(p, 0, 1, cnt)
            tokens.append(t)
        out = self.run_tokens(0, tokens)
        self.assertEqual([o["d"] for o in out], pixels)
        self.assertTrue(all(o["control"] == 0 for o in out))

    def test_control_guard_terc4(self):
        for channel in range(3):
            tokens = control_tokens + [video_gb_tokens[channel], data_gb_token] + terc4_tokens
            out = self.run_tokens(channel, tokens)
            for i in range(4):
                self.assertEqual((out[i]["control"], out[i]["c"]), (1, i))
            self.assertEqual(out[4]["video_gb"], 1)
            self.assertEqual(out[5]["data_gb"], 1 if channel else 0)
            for n in range(16):
                self.assertEqual((out[6 + n]["terc4_valid"], out[6 + n]["terc4"]), (1, n))
