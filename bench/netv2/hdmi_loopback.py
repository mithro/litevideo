#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Tier T1 bench: the transmitter's character stream fed to the receiver
protocol layer inside the fabric (no cable needed), with counters and a CRC
of the decoded video over CSRs. The pads are still driven, so this bitstream
also serves as a tier-T4 source.

    uv run python -m bench.netv2.hdmi_loopback                # elaborate only
    uv run scripts/limited.py -- uv run python -m bench.netv2.hdmi_loopback --build --toolchain vivado
"""

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import *
from litex.soc.interconnect.csr import CSRStatus, CSRStorage, CSRField

from litevideo.hdmi.common import *
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder
from litevideo.hdmi.audio.extract import AudioExtract
from litevideo.hdmi.audio.capture import AudioSampleCapture

from bench.netv2.common import bench_main
from bench.netv2.frame_crc import FrameCRC
from bench.netv2.hdmi_tx import HDMITxSoC


class HDMILoopbackSoC(HDMITxSoC):
    def __init__(self, **kwargs):
        HDMITxSoC.__init__(self, **kwargs)

        self.rx_period = rx = ClockDomainsRenamer("pix")(HDMIPeriodDecoder())
        self.rx_island = dec = ClockDomainsRenamer("pix")(DataIslandDecoder())
        self.comb += [
            rx.sink.valid.eq(1),
            rx.sink.c0.eq(self.hdmi_tx.source.c0),
            rx.sink.c1.eq(self.hdmi_tx.source.c1),
            rx.sink.c2.eq(self.hdmi_tx.source.c2),
            dec.active.eq(rx.island_active),
            dec.first.eq(rx.island_first),
            dec.nibble0.eq(rx.nibble0),
            dec.nibble1.eq(rx.nibble1),
            dec.nibble2.eq(rx.nibble2),
        ]

        # Audio extraction: one-shot sample capture drained over CSRs.
        self.rx_audio = ext = ClockDomainsRenamer("pix")(AudioExtract())
        self.comb += dec.source.connect(ext.sink)
        self.audio_capture = AudioSampleCapture()
        self.comb += ext.sample_source.connect(self.audio_capture.sink)
        self.audio_n   = CSRStatus(20, description="ACR N received.")
        self.audio_cts = CSRStatus(20, description="ACR CTS received.")
        self.audio_infoframe_rx = CSRStatus(fields=[
            CSRField("cc", 3), CSRField("ct", 4), CSRField("ss", 2), CSRField("sf", 3), CSRField("ca", 8), CSRField("valid", 1)])
        self.audio_asps    = CSRStatus(32, description="Audio Sample Packets extracted.")
        self.audio_acrs    = CSRStatus(32, description="ACR packets extracted.")
        self.audio_samples = CSRStatus(32, description="Subframes extracted.")
        self.audio_dropped = CSRStatus(32, description="Packets dropped on ECC error.")
        self.specials += [
            MultiReg(ext.n,   self.audio_n.status),
            MultiReg(ext.cts, self.audio_cts.status),
            MultiReg(ext.infoframe.cc, self.audio_infoframe_rx.fields.cc),
            MultiReg(ext.infoframe.ct, self.audio_infoframe_rx.fields.ct),
            MultiReg(ext.infoframe.ss, self.audio_infoframe_rx.fields.ss),
            MultiReg(ext.infoframe.sf, self.audio_infoframe_rx.fields.sf),
            MultiReg(ext.infoframe.ca, self.audio_infoframe_rx.fields.ca),
            MultiReg(ext.infoframe_valid, self.audio_infoframe_rx.fields.valid),
            MultiReg(ext.asp_count,    self.audio_asps.status),
            MultiReg(ext.acr_count,    self.audio_acrs.status),
            MultiReg(ext.sample_count, self.audio_samples.status),
            MultiReg(ext.dropped_count, self.audio_dropped.status),
        ]

        self.rx_frame_crc = ClockDomainsRenamer("pix")(FrameCRC())
        self.comb += [
            self.rx_frame_crc.de.eq(rx.source.de), self.rx_frame_crc.vsync.eq(rx.source.vsync),
            self.rx_frame_crc.r.eq(rx.source.r), self.rx_frame_crc.g.eq(rx.source.g), self.rx_frame_crc.b.eq(rx.source.b),
        ]

        # Period histogram: one 16-bit counter per Period value.
        hist = [Signal(16) for _ in range(8)]
        for value, counter in enumerate(hist):
            self.sync.pix += If(rx.period == value, counter.eq(counter + 1))
        errors = Signal(32)
        last_header = Signal(24)
        self.sync.pix += [
            If(rx.error, errors.eq(errors + 1)),
            If(dec.source.valid & dec.source.ecc_ok, last_header.eq(dec.source.header)),
        ]

        # CSRs (sys) from pix through MultiReg: monitoring only.
        self.rx_periods_0 = CSRStatus(32, description="Period histogram: CONTROL[15:0], VIDEO_PREAMBLE[31:16].")
        self.rx_periods_1 = CSRStatus(32, description="Period histogram: VIDEO_GUARD[15:0], VIDEO[31:16].")
        self.rx_periods_2 = CSRStatus(32, description="Period histogram: DATA_PREAMBLE[15:0], DATA_LEADING_GUARD[31:16].")
        self.rx_periods_3 = CSRStatus(32, description="Period histogram: DATA_ISLAND[15:0], DATA_TRAILING_GUARD[31:16].")
        self.rx_islands    = CSRStatus(32, description="Islands decoded.")
        self.rx_packets    = CSRStatus(32, description="Packets decoded.")
        self.rx_ecc_errors = CSRStatus(32, description="Packets with a BCH ECC error.")
        self.rx_errors     = CSRStatus(32, description="Islands ended by a control character.")
        self.rx_last_header = CSRStatus(24, description="Header of the last packet with a good ECC.")
        self.rx_frame_crc_csr = CSRStatus(32, name="rx_frame_crc", description="CRC-32 of the last decoded frame.")
        self.rx_frames     = CSRStatus(32, description="Frames decoded.")
        self.specials += [
            MultiReg(Cat(hist[0], hist[1]), self.rx_periods_0.status),
            MultiReg(Cat(hist[2], hist[3]), self.rx_periods_1.status),
            MultiReg(Cat(hist[4], hist[5]), self.rx_periods_2.status),
            MultiReg(Cat(hist[6], hist[7]), self.rx_periods_3.status),
            MultiReg(dec.island_count,    self.rx_islands.status),
            MultiReg(dec.packet_count,    self.rx_packets.status),
            MultiReg(dec.ecc_error_count, self.rx_ecc_errors.status),
            MultiReg(errors,              self.rx_errors.status),
            MultiReg(last_header,         self.rx_last_header.status),
            MultiReg(self.rx_frame_crc.crc,   self.rx_frame_crc_csr.status),
            MultiReg(self.rx_frame_crc.frame, self.rx_frames.status),
        ]


if __name__ == "__main__":
    bench_main(HDMILoopbackSoC, "LiteVideo NeTV2 HDMI fabric loopback bench.", "netv2-hdmi-loopback")
