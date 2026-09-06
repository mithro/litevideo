#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""AudioExtract fed with model packets."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio import model as am
from litevideo.hdmi.audio.extract import AudioExtract


def run_extract(packets):
    """packets: list of (Packet, ecc_ok). Returns (samples, status dict)."""
    dut = AudioExtract()
    samples = []
    status = {}

    def drive():
        for p, ok in packets:
            yield dut.sink.valid.eq(1)
            yield dut.sink.ecc_ok.eq(ok)
            yield dut.sink.header.eq(p.header)
            for k in range(4):
                yield getattr(dut.sink, f"sub{k}").eq(p.subpackets[k])
            yield
            yield dut.sink.valid.eq(0)
            for _ in range(12):
                yield
        status["n"] = (yield dut.n); status["cts"] = (yield dut.cts); status["acr_valid"] = (yield dut.acr_valid)
        status["cc"] = (yield dut.infoframe.cc); status["sf"] = (yield dut.infoframe.sf)
        status["ss"] = (yield dut.infoframe.ss); status["lsv"] = (yield dut.infoframe.lsv)
        status["if_valid"] = (yield dut.infoframe_valid)
        for name in ("asp_count", "acr_count", "infoframe_count", "sample_count", "dropped_count"):
            status[name] = (yield getattr(dut, name))

    @passive
    def collect():
        while True:
            if (yield dut.sample_source.valid):
                s = {}
                for n in ("sample", "channel", "v", "u", "c", "p", "b"):
                    s[n] = (yield getattr(dut.sample_source, n))
                samples.append(s)
            yield

    run_simulation(dut, [drive(), collect()])
    return samples, status


class TestAudioExtract(unittest.TestCase):
    def test_asp_acr_infoframe(self):
        frames = am.sine_frames(9)
        p1, b = am.asp_packet(frames[:4], block_index=190)
        p2, b = am.asp_packet(frames[4:8], block_index=b)
        p3, b = am.asp_packet(frames[8:9], block_index=b)
        acr = am.acr_packet(6144, 74250)
        inf = am.audio_infoframe(cc=1, sf=3, ss=3, lsv=5)
        samples, st = run_extract([(acr, 1), (inf, 1), (p1, 1), (p2, 0), (p2, 1), (p3, 1), (inf, 0)])

        self.assertEqual((st["n"], st["cts"], st["acr_valid"]), (6144, 74250, 1))
        self.assertEqual((st["cc"], st["sf"], st["ss"], st["lsv"], st["if_valid"]), (1, 3, 3, 5, 1))
        self.assertEqual((st["asp_count"], st["acr_count"], st["infoframe_count"], st["dropped_count"]), (3, 1, 1, 2))
        self.assertEqual(st["sample_count"], 18)
        got = [(s["sample"], s["channel"]) for s in samples]
        expected = []
        for l, r in frames:
            expected += [(l, 0), (r, 1)]
        self.assertEqual(got, expected)
        # Block start: frame index 192 (the third frame of p1) -> both its subframes carry b.
        self.assertEqual([s["b"] for s in samples], [0, 0, 0, 0, 1, 1] + [0] * 12)
        # C and P bits are the ones the model encoded.
        unpacked = am.unpack_asp(p1) + am.unpack_asp(p2) + am.unpack_asp(p3)
        for u, (sl, sr) in zip(unpacked, zip(samples[0::2], samples[1::2])):
            self.assertEqual((sl["c"], sl["p"], sr["c"], sr["p"]), (u["cl"], u["pl"], u["cr"], u["pr"]))
