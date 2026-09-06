#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""AVI InfoFrame and General Control Packet generators against the model."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.infoframe import AVIInfoFrameGenerator, GCPGenerator, avi_fields_layout


def packet_from_source(src):
    header = (yield src.header)
    subs = []
    for k in range(4):
        subs.append((yield getattr(src, f"sub{k}")))
    return model.Packet.from_words(header, subs)


class TestAVIInfoFrameGenerator(unittest.TestCase):
    def test_matches_model(self):
        dut = AVIInfoFrameGenerator()
        got = []

        def gen():
            yield dut.fields.vic.eq(16); yield dut.fields.y.eq(2); yield dut.fields.c.eq(2)
            yield dut.fields.m.eq(2); yield dut.fields.r.eq(8); yield dut.fields.q.eq(1)
            yield dut.source.ready.eq(1)
            yield
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            for _ in range(8):
                if (yield dut.source.valid):
                    got.append((yield from packet_from_source(dut.source)))
                yield

        run_simulation(dut, gen())
        self.assertEqual(got, [model.avi_infoframe(vic=16, y=2, c=2, m=2, r=8, q=1)])

    def test_holds_until_accepted(self):
        dut = AVIInfoFrameGenerator()
        seen = []

        def gen():
            yield dut.fields.vic.eq(4)
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            for i in range(10):
                seen.append((yield dut.source.valid))
                if i == 6:
                    yield dut.source.ready.eq(1)
                yield
            yield dut.source.ready.eq(0)
            yield
            seen.append((yield dut.source.valid))

        run_simulation(dut, gen())
        self.assertIn(1, seen[:6])
        self.assertEqual(seen[-1], 0)


class TestGCPGenerator(unittest.TestCase):
    def test_set_and_clear(self):
        dut = GCPGenerator()
        got = []

        def gen():
            yield dut.source.ready.eq(1)
            # frame 1: avmute on -> Set_AVMUTE; frame 2: still on -> Set again; frame 3: off -> Clear; frame 4: nothing
            for avmute in (1, 1, 0, 0):
                yield dut.avmute.eq(avmute)
                yield dut.trigger.eq(1)
                yield
                yield dut.trigger.eq(0)
                for _ in range(6):
                    if (yield dut.source.valid):
                        got.append((yield from packet_from_source(dut.source)))
                    yield

        run_simulation(dut, gen())
        self.assertEqual(got, [model.gcp_packet(set_avmute=1), model.gcp_packet(set_avmute=1), model.gcp_packet(clear_avmute=1)])
