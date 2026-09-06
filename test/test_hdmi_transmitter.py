#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMITransmitter: CSR-driven AVI InfoFrame and General Control Packets,
checked through the phase-1 decoders."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.transmitter import HDMITransmitter
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder
from litevideo.csc.convert import PixelFormat, convert_line

from test.common import stream_inserter
from test.test_hdmi_framer import TIMING, video_beats


class DUT(Module):
    def __init__(self):
        self.submodules.tx = ClockDomainsRenamer({"pix": "sys"})(HDMITransmitter(default_vic=4))
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        self.comb += [
            self.tx.source.connect(self.period.sink),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
        ]


class TestHDMITransmitter(unittest.TestCase):
    def test_avi_per_frame_and_avmute(self):
        dut = DUT()
        beats = video_beats(TIMING, 6)
        vtotal = sum(TIMING[k] for k in ("vactive", "vfront", "vsync", "vback"))
        line = sum(TIMING[k] for k in ("hactive", "hfront", "hsync", "hback"))
        frame_len = vtotal * line
        packets = []
        status = {}

        @passive
        def collect():
            while True:
                if (yield dut.dec.source.valid):
                    header = (yield dut.dec.source.header)
                    subs = []
                    for k in range(4):
                        subs.append((yield getattr(dut.dec.source, f"sub{k}")))
                    packets.append((model.Packet.from_words(header, subs), (yield dut.dec.source.ecc_ok)))
                yield

        def control():
            # Frames 0..2: defaults. From frame 3: AVMUTE on. Frame 5: AVMUTE off.
            # CSR fields are derived from ``storage``; write the storage register
            # (bit 0 enable_islands, bit 1 dvi_mode, bit 2 avmute, bit 3 avi_enable).
            for _ in range(3 * frame_len):
                yield
            yield dut.tx.control.storage.eq(0b1101)
            for _ in range(2 * frame_len):
                yield
            yield dut.tx.control.storage.eq(0b1001)
            for _ in range(frame_len + 60):
                yield
            status["island_count"] = (yield dut.tx.island_count.status)
            status["frame_count"] = (yield dut.tx.frame_count.status)
            status["max_packets"] = (yield dut.tx.status.fields.max_packets)

        run_simulation(dut, [stream_inserter(dut.tx.sink, beats, drain=80), collect(), control()])

        self.assertTrue(all(ok for _, ok in packets))
        avi = model.avi_infoframe(vic=4, m=2, r=8, q=2)
        avis = [p for p, _ in packets if p.type == PacketType.AVI_INFOFRAME]
        gcps = [p for p, _ in packets if p.type == PacketType.GCP]
        # One AVI InfoFrame per frame once timing is known (frame 0 has no slot yet).
        self.assertGreaterEqual(len(avis), 4)
        self.assertTrue(all(p == avi for p in avis))
        # GCP: Set_AVMUTE while muted (2 frames), then one Clear_AVMUTE.
        self.assertEqual(gcps[:2], [model.gcp_packet(set_avmute=1)] * 2)
        self.assertEqual(gcps[-1], model.gcp_packet(clear_avmute=1))
        self.assertEqual(len(gcps), 3)
        # Only these two packet types are generated.
        self.assertEqual(len(packets), len(avis) + len(gcps))
        self.assertEqual(status["island_count"], len(packets))
        self.assertEqual(status["frame_count"], 6)
        self.assertEqual(status["max_packets"], 1)


    def run_format(self, avi_storage, dvi_mode=False):
        """Run 2 frames with ``avi_config`` = ``avi_storage``; return the decoded
        active pixels per line (wire order (c0, c1, c2)) and the input lines."""
        dut = DUT()
        beats = video_beats(TIMING, 2)
        rx_lines, cur = [], []
        inputs, cur_in = [], []
        for b in beats:
            if b["de"]:
                cur_in.append((b["b"], b["g"], b["r"]))
            elif cur_in:
                inputs.append(cur_in); cur_in = []

        @passive
        def collect():
            while True:
                if (yield dut.period.source.de):
                    cur.append(((yield dut.period.source.b), (yield dut.period.source.g), (yield dut.period.source.r)))
                elif cur:
                    rx_lines.append(list(cur)); cur.clear()
                yield

        def control():
            yield dut.tx.avi_config.storage.eq(avi_storage)
            yield dut.tx.control.storage.eq(0b1011 if dvi_mode else 0b1001)
            yield dut.period.dvi_mode.eq(dvi_mode)
            yield

        run_simulation(dut, [stream_inserter(dut.tx.sink, beats, drain=80), collect(), control()])
        # In DVI mode the idle characters before the stream starts decode as a stray pixel: drop partial lines.
        rx_lines = [l for l in rx_lines if len(l) == TIMING["hactive"]]
        return rx_lines, inputs

    def test_output_formats(self):
        f = HDMITransmitter(default_vic=4).avi_config.fields   # field offsets
        def storage(y, c, q, vic=4):
            return (y << f.y.offset) | (c << f.c.offset) | (q << f.q.offset) | (2 << f.m.offset) | (8 << f.r.offset) | (vic << f.vic.offset)
        cases = [  # (y, c, q) -> converter controls (fmt_in RGB full; fmt_out, colorimetry, rgb_out_limited, ycc_limited)
            ((0, 0, 2), (PixelFormat.RGB, 2, 0, 1)),        # default: full RGB, untouched
            ((0, 0, 0), (PixelFormat.RGB, 2, 1, 1)),        # Q default on 720p: limited RGB
            ((2, 2, 0), (PixelFormat.YCBCR444, 2, 1, 1)),   # BT.709 4:4:4
            ((1, 1, 0), (PixelFormat.YCBCR422, 1, 1, 1)),   # BT.601 4:2:2
        ]
        for (y, c, q), (fmt_out, col, rgb_l, ycc_l) in cases:
            rx_lines, inputs = self.run_format(storage(y, c, q))
            self.assertEqual(len(rx_lines), len(inputs), (y, c, q))
            for line_in, line_rx in zip(inputs, rx_lines):
                expected = convert_line(line_in, PixelFormat.RGB, fmt_out, col, 0, rgb_l, ycc_l)
                self.assertEqual(line_rx, expected, (y, c, q))

    def test_dvi_mode_forces_rgb(self):
        f = HDMITransmitter(default_vic=4).avi_config.fields
        rx_lines, inputs = self.run_format((2 << f.y.offset) | (4 << f.vic.offset), dvi_mode=True)
        self.assertEqual(rx_lines, inputs)
