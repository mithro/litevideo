#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""AudioSamplePacketizer against the packet model."""

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.audio.common import *
from litevideo.hdmi.audio import model as am
from litevideo.hdmi.audio.packetizer import AudioSamplePacketizer

from test.common import stream_inserter


def run_packetizer(frames, valid_rand=0, ready_rand=0, seed=0):
    dut = AudioSamplePacketizer(fs=48000)
    beats = [{"left": l, "right": r} for l, r in frames]
    packets = []
    prng = random.Random(seed)

    @passive
    def collect():
        while True:
            ready = prng.randrange(100) >= ready_rand
            yield dut.source.ready.eq(ready)
            yield
            if ready and (yield dut.source.valid):
                header = (yield dut.source.header)
                subs = []
                for k in range(4):
                    subs.append((yield getattr(dut.source, f"sub{k}")))
                packets.append(model.Packet.from_words(header, subs))

    run_simulation(dut, [stream_inserter(dut.sink, beats, valid_rand=valid_rand, seed=seed, drain=20), collect()])
    return packets


def unpack_all(packets):
    return [f for p in packets for f in am.unpack_asp(p)]


class TestAudioSamplePacketizer(unittest.TestCase):
    def test_bit_exact_against_model_when_backpressured(self):
        frames = am.sine_frames(400)
        packets = run_packetizer(frames, ready_rand=85, seed=1)
        got = unpack_all(packets)
        self.assertEqual([(g["left"], g["right"]) for g in got], frames)
        # Rebuild the expected packets from the model with the same grouping.
        bidx = 0
        idx = 0
        for p in packets:
            n = len(am.unpack_asp(p))
            expected, bidx = am.asp_packet(frames[idx:idx + n], block_index=bidx)
            self.assertEqual(p, expected)
            idx += n
        self.assertTrue(any(len(am.unpack_asp(p)) == 4 for p in packets), "backpressure should produce full packets")

    def test_one_frame_per_packet_when_drained(self):
        frames = am.sine_frames(50)
        packets = run_packetizer(frames, valid_rand=50, seed=2)
        self.assertTrue(all(len(am.unpack_asp(p)) == 1 for p in packets))
        self.assertEqual([(g["left"], g["right"]) for g in unpack_all(packets)], frames)

    def test_block_start_every_192_frames(self):
        frames = [(i, i) for i in range(400)]
        got = unpack_all(run_packetizer(frames, ready_rand=50, seed=3))
        self.assertEqual([i for i, g in enumerate(got) if g["b"]], [0, 192, 384])

    def test_channel_status_and_parity(self):
        frames = [(random.Random(4).randrange(1 << 24), 0) for _ in range(200)]
        got = unpack_all(run_packetizer(frames, ready_rand=30, seed=4))
        sl = channel_status_block(48000, IEC_CHANNEL_LEFT)
        sr = channel_status_block(48000, IEC_CHANNEL_RIGHT)
        for i, g in enumerate(got):
            self.assertEqual(g["cl"], (sl >> (i % 192)) & 1)
            self.assertEqual(g["cr"], (sr >> (i % 192)) & 1)
            self.assertEqual(g["pl"], am.parity(g["left"], 0, 0, g["cl"]))
            self.assertEqual(g["pr"], am.parity(g["right"], 0, 0, g["cr"]))
            self.assertEqual((g["vl"], g["ul"], g["vr"], g["ur"]), (0, 0, 0, 0))
