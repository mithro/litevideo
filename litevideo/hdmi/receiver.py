#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI receiver protocol layer with CSRs.

Takes the three channel-aligned 10-bit characters per pixel clock that the
input PHY delivers (``litevideo.input`` ``ChanSync`` outputs, or any
``raw_layout`` source; ``valid`` = the channels are synchronised) and
provides:

* ``source``: ``video_data_layout`` pixels with DE/HSYNC/VSYNC (period decoder);
* ``packet_source``: every data island packet with its ECC verdict;
* AVI InfoFrame capture (CEA-861-D §6.4): pixel encoding, colorimetry,
  quantization range and VIC, with the InfoFrame checksum verified;
* timing measurement: active pixels per line, active lines per frame, total
  characters per line and lines per frame;
* audio extraction (``with_audio``): samples into a ``sys``-domain FIFO
  readable over CSRs, N/CTS and Audio InfoFrame latches.

Runs in the ``pix`` domain; CSRs are in ``sys``.
"""

from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fifo import AsyncFIFO

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import *
from litex.soc.cores.video import video_data_layout

from litevideo.hdmi.common import *
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder
from litevideo.hdmi.audio.extract import AudioExtract


class TimingMeasure(LiteXModule):
    """Counts active pixels per line, active lines per frame, characters per
    line (HSYNC edge to HSYNC edge) and lines per frame, latched at the end of
    each line/frame."""
    def __init__(self):
        self.de    = Signal()
        self.hsync = Signal()
        self.vsync = Signal()
        self.valid = Signal()
        self.hactive = Signal(13)
        self.vactive = Signal(13)
        self.htotal  = Signal(13)
        self.vtotal  = Signal(13)
        self.frames  = Signal(32)

        # # #

        de_r, hs_r, vs_r = Signal(), Signal(), Signal()
        self.sync += [de_r.eq(self.de), hs_r.eq(self.hsync), vs_r.eq(self.vsync)]
        de_fall = ~self.de & de_r
        hs_edge = self.hsync & ~hs_r
        vs_edge = self.vsync & ~vs_r

        hcnt = Signal(13)
        self.sync += If(~self.valid, hcnt.eq(0)).Elif(self.de, hcnt.eq(hcnt + 1)).Elif(de_fall, self.hactive.eq(hcnt), hcnt.eq(0))
        hpos = Signal(13)
        self.sync += If(hs_edge, self.htotal.eq(hpos + 1), hpos.eq(0)).Else(hpos.eq(hpos + 1))
        lines = Signal(13)
        vlines = Signal(13)
        self.sync += [
            If(vs_edge,
                self.vtotal.eq(lines), lines.eq(0),
                self.vactive.eq(vlines), vlines.eq(0),
                self.frames.eq(self.frames + 1),
            ).Elif(hs_edge,
                lines.eq(lines + 1),
            ),
            If(de_fall & ~vs_edge, vlines.eq(vlines + 1)),
        ]


class HDMIReceiver(LiteXModule):
    def __init__(self, with_audio=True):
        self.sink   = stream.Endpoint(raw_layout)
        self.source = stream.Endpoint(video_data_layout)
        self.packet_source = stream.Endpoint(packet_rx_layout)

        self.control = CSRStorage(fields=[
            CSRField("dvi_mode", 1, reset=0, description="DE from control characters only (no preamble tracking)."),
        ])
        self.status = CSRStatus(fields=[
            CSRField("synced",  1, description="Input characters valid (channels synchronised)."),
            CSRField("hactive", 13, description="Active pixels per line."),
            CSRField("vactive", 13, description="Active lines per frame."),
        ])
        self.timing = CSRStatus(fields=[
            CSRField("htotal", 13, description="Characters per line."),
            CSRField("vtotal", 13, description="Lines per frame."),
        ])
        self.avi = CSRStatus(fields=[
            CSRField("y",   2, description="Pixel encoding: 0 RGB, 1 YCbCr 4:2:2, 2 YCbCr 4:4:4."),
            CSRField("c",   2, description="Colorimetry: 0 none, 1 BT.601, 2 BT.709."),
            CSRField("q",   2, description="RGB quantization: 0 default, 1 limited, 2 full."),
            CSRField("vic", 7, description="Video identification code."),
            CSRField("m",   2, description="Picture aspect ratio."),
            CSRField("valid", 1, description="An AVI InfoFrame with a good ECC has been received."),
            CSRField("checksum_ok", 1, description="Its InfoFrame checksum was correct."),
        ])
        self.frames      = CSRStatus(32, description="VSYNC leading edges.")
        self.islands     = CSRStatus(32, description="Data islands decoded.")
        self.packets     = CSRStatus(32, description="Packets decoded.")
        self.ecc_errors  = CSRStatus(32, description="Packets with a BCH ECC error.")
        self.period_errors = CSRStatus(32, description="Islands ended by a control character.")
        self.avi_count   = CSRStatus(32, description="AVI InfoFrames received.")
        self.periods_0 = CSRStatus(32, description="Period histogram: CONTROL[15:0], VIDEO_PREAMBLE[31:16].")
        self.periods_1 = CSRStatus(32, description="Period histogram: VIDEO_GUARD[15:0], VIDEO[31:16].")
        self.periods_2 = CSRStatus(32, description="Period histogram: DATA_PREAMBLE[15:0], DATA_LEADING_GUARD[31:16].")
        self.periods_3 = CSRStatus(32, description="Period histogram: DATA_ISLAND[15:0], DATA_TRAILING_GUARD[31:16].")

        # # #

        self.period = period = ClockDomainsRenamer("pix")(HDMIPeriodDecoder())
        self.island = dec = ClockDomainsRenamer("pix")(DataIslandDecoder())
        self.comb += [
            self.sink.connect(period.sink),
            period.source.connect(self.source),
            dec.active.eq(period.island_active),
            dec.first.eq(period.island_first),
            dec.nibble0.eq(period.nibble0),
            dec.nibble1.eq(period.nibble1),
            dec.nibble2.eq(period.nibble2),
            dec.source.connect(self.packet_source),
        ]
        ctl = Signal(len(self.control.storage))
        self.specials += MultiReg(self.control.storage, ctl, "pix")
        self.comb += period.dvi_mode.eq(ctl[0])

        # Timing.
        self.measure = tm = ClockDomainsRenamer("pix")(TimingMeasure())
        self.comb += [tm.de.eq(period.source.de), tm.hsync.eq(period.source.hsync),
                      tm.vsync.eq(period.source.vsync), tm.valid.eq(period.source.valid)]

        # AVI InfoFrame capture with checksum verification.
        p = dec.source
        avi_y, avi_c, avi_q, avi_m, avi_vic = Signal(2), Signal(2), Signal(2), Signal(2), Signal(7)
        avi_valid, avi_csum_ok, avi_count = Signal(), Signal(), Signal(32)
        pb = [p.header[0:8], p.header[8:16], p.header[16:24]]
        for k in range(4):
            sub = getattr(p, f"sub{k}")
            pb += [sub[8 * i:8 * i + 8] for i in range(7)]
        csum = Signal(12)
        self.comb += csum.eq(sum(pb[:3 + 14]))          # HB0..HB2, PB0..PB13
        is_avi = p.valid & p.ecc_ok & (p.header[0:8] == PacketType.AVI_INFOFRAME)
        pb1, pb2, pb3, pb4 = p.sub0[8:16], p.sub0[16:24], p.sub0[24:32], p.sub0[32:40]
        self.sync.pix += If(is_avi,
            avi_y.eq(pb1[5:7]), avi_c.eq(pb2[6:8]), avi_m.eq(pb2[4:6]), avi_q.eq(pb3[2:4]), avi_vic.eq(pb4[0:7]),
            avi_valid.eq(1), avi_csum_ok.eq(csum[0:8] == 0), avi_count.eq(avi_count + 1),
        )

        # Counters and histogram.
        hist = [Signal(16) for _ in range(8)]
        for value, counter in enumerate(hist):
            self.sync.pix += If((period.period == value) & period.source.valid, counter.eq(counter + 1))
        perr = Signal(32)
        self.sync.pix += If(period.error, perr.eq(perr + 1))

        self.specials += [
            MultiReg(self.sink.valid,  self.status.fields.synced),
            MultiReg(tm.hactive, self.status.fields.hactive),
            MultiReg(tm.vactive, self.status.fields.vactive),
            MultiReg(tm.htotal,  self.timing.fields.htotal),
            MultiReg(tm.vtotal,  self.timing.fields.vtotal),
            MultiReg(avi_y, self.avi.fields.y), MultiReg(avi_c, self.avi.fields.c),
            MultiReg(avi_q, self.avi.fields.q), MultiReg(avi_vic, self.avi.fields.vic),
            MultiReg(avi_m, self.avi.fields.m),
            MultiReg(avi_valid, self.avi.fields.valid), MultiReg(avi_csum_ok, self.avi.fields.checksum_ok),
            MultiReg(tm.frames, self.frames.status),
            MultiReg(dec.island_count, self.islands.status),
            MultiReg(dec.packet_count, self.packets.status),
            MultiReg(dec.ecc_error_count, self.ecc_errors.status),
            MultiReg(perr, self.period_errors.status),
            MultiReg(avi_count, self.avi_count.status),
            MultiReg(Cat(hist[0], hist[1]), self.periods_0.status),
            MultiReg(Cat(hist[2], hist[3]), self.periods_1.status),
            MultiReg(Cat(hist[4], hist[5]), self.periods_2.status),
            MultiReg(Cat(hist[6], hist[7]), self.periods_3.status),
        ]

        if with_audio:
            self.add_audio()

    def add_audio(self):
        self.audio = ext = ClockDomainsRenamer("pix")(AudioExtract())
        self.comb += self.island.source.connect(ext.sink)
        fifo = ClockDomainsRenamer({"write": "pix", "read": "sys"})(AsyncFIFO(width=32, depth=512))
        self.audio_fifo = fifo
        src = ext.sample_source
        self.comb += [
            fifo.din.eq(Cat(src.sample, src.channel, src.b, src.c, src.p, src.v, C(1, 1))),
            fifo.we.eq(src.valid & fifo.writable),
        ]
        self.audio_sample_data  = CSRStatus(32, description="Extracted subframe: sample[23:0], channel[26:24], b[27], c[28], p[29], v[30], 1[31].")
        self.audio_sample_valid = CSRStatus(1, description="The sample FIFO has data.")
        self.audio_sample_pop   = CSRStorage(1, description="Write to pop the sample FIFO.")
        self.comb += [
            self.audio_sample_data.status.eq(fifo.dout),
            self.audio_sample_valid.status.eq(fifo.readable),
            fifo.re.eq(self.audio_sample_pop.re),
        ]
        self.audio_n   = CSRStatus(20, description="ACR N received.")
        self.audio_cts = CSRStatus(20, description="ACR CTS received.")
        self.audio_infoframe = CSRStatus(fields=[
            CSRField("cc", 3), CSRField("ct", 4), CSRField("ss", 2), CSRField("sf", 3), CSRField("ca", 8), CSRField("valid", 1)])
        self.audio_asps    = CSRStatus(32, description="Audio Sample Packets extracted.")
        self.audio_acrs    = CSRStatus(32, description="ACR packets extracted.")
        self.audio_samples = CSRStatus(32, description="Subframes extracted.")
        self.audio_dropped = CSRStatus(32, description="Packets dropped on ECC error.")
        f = self.audio_infoframe.fields
        self.specials += [
            MultiReg(ext.n,   self.audio_n.status),
            MultiReg(ext.cts, self.audio_cts.status),
            MultiReg(ext.infoframe.cc, f.cc), MultiReg(ext.infoframe.ct, f.ct),
            MultiReg(ext.infoframe.ss, f.ss), MultiReg(ext.infoframe.sf, f.sf),
            MultiReg(ext.infoframe.ca, f.ca), MultiReg(ext.infoframe_valid, f.valid),
            MultiReg(ext.asp_count,     self.audio_asps.status),
            MultiReg(ext.acr_count,     self.audio_acrs.status),
            MultiReg(ext.sample_count,  self.audio_samples.status),
            MultiReg(ext.dropped_count, self.audio_dropped.status),
        ]
