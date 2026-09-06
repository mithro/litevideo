#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI transmitter: framer, scheduler and packet generators with CSRs.

Runs in the ``pix`` clock domain (rename with ``ClockDomainsRenamer`` if the
integrator uses another name); CSRs live in ``sys`` and are synchronised with
``MultiReg``. Status counters cross back to ``sys`` through ``MultiReg`` as
well, so they are for monitoring only (a read may tear across bits).
Priority of packet sources (HDMI §7.8.2): audio samples, audio clock
regeneration (both added in phase 3 through ``extra_packet_sinks``), General
Control, AVI InfoFrame.
"""

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import *
from litex.soc.cores.video import video_data_layout

from litevideo.hdmi.common import *
from litevideo.hdmi.framer import HDMIFramer
from litevideo.hdmi.scheduler import PacketScheduler
from litevideo.hdmi.infoframe import AVIInfoFrameGenerator, GCPGenerator


class HDMITransmitter(LiteXModule):
    def __init__(self, default_vic=4, extra_packet_sinks=0):
        self.sink   = stream.Endpoint(video_data_layout)
        self.source = stream.Endpoint(raw_layout)

        self.control = CSRStorage(fields=[
            CSRField("enable_islands", 1, reset=1, description="Insert data islands."),
            CSRField("dvi_mode",       1, reset=0, description="DVI output: no preambles, guard bands or islands."),
            CSRField("avmute",         1, reset=0, description="Send General Control Packets with Set_AVMUTE."),
            CSRField("avi_enable",     1, reset=1, description="Send the AVI InfoFrame once per frame."),
        ])
        self.avi_config = CSRStorage(fields=[
            CSRField("y",   2, reset=0, description="Pixel encoding: 0 RGB, 1 YCbCr 4:2:2, 2 YCbCr 4:4:4 (CEA-861-D Table 8)."),
            CSRField("a",   1, reset=0, description="Active format information present."),
            CSRField("b",   2, reset=0, description="Bar info valid."),
            CSRField("s",   2, reset=0, description="Scan information."),
            CSRField("c",   2, reset=0, description="Colorimetry: 0 none, 1 BT.601, 2 BT.709 (Table 9)."),
            CSRField("m",   2, reset=2, description="Picture aspect: 1 4:3, 2 16:9."),
            CSRField("r",   4, reset=8, description="Active format aspect (8 = same as picture)."),
            CSRField("itc", 1, reset=0, description="IT content."),
            CSRField("ec",  3, reset=0, description="Extended colorimetry."),
            CSRField("q",   2, reset=0, description="RGB quantization: 0 default, 1 limited, 2 full (Table 11)."),
            CSRField("sc",  2, reset=0, description="Non-uniform scaling."),
            CSRField("vic", 7, reset=default_vic, description="Video identification code (CEA-861-D Table 3)."),
        ])
        self.avi_config2 = CSRStorage(fields=[
            CSRField("yq", 2, reset=0, description="YCC quantization (CEA-861-E)."),
            CSRField("cn", 2, reset=0, description="Content type (CEA-861-E)."),
            CSRField("pr", 4, reset=0, description="Pixel repetition factor minus one."),
        ])
        self.status = CSRStatus(fields=[
            CSRField("hs2de",       16, description="Measured HSYNC leading edge to DE rise, in characters."),
            CSRField("hs2de_valid",  1, description="hs2de has been measured."),
            CSRField("max_packets",  5, description="Packets per island that fit on this timing."),
        ])
        self.island_count = CSRStatus(32, description="Data islands sent.")
        self.frame_count  = CSRStatus(32, description="VSYNC leading edges seen.")

        # # #

        self.framer = framer = ClockDomainsRenamer("pix")(HDMIFramer())
        self.comb += [self.sink.connect(framer.sink), framer.source.connect(self.source)]

        n_sinks = 2 + extra_packet_sinks
        self.scheduler = sched = ClockDomainsRenamer("pix")(PacketScheduler(n_sinks))
        self.comb += sched.source.connect(framer.packet_sink)
        self.extra_packet_sinks = sched.sinks[:extra_packet_sinks]   # higher priority (audio, phase 3)
        gcp_sink, avi_sink = sched.sinks[extra_packet_sinks:]

        # Configuration into pix.
        ctl  = Signal(len(self.control.storage))
        avi  = Signal(len(self.avi_config.storage))
        avi2 = Signal(len(self.avi_config2.storage))
        self.specials += [
            MultiReg(self.control.storage,     ctl,  "pix"),
            MultiReg(self.avi_config.storage,  avi,  "pix"),
            MultiReg(self.avi_config2.storage, avi2, "pix"),
        ]
        self.comb += [framer.enable_islands.eq(ctl[0]), framer.dvi_mode.eq(ctl[1])]

        # Frame trigger: VSYNC leading edge at the framer input.
        vsync_r = Signal()
        frame = Signal()
        self.sync.pix += vsync_r.eq(self.sink.vsync & self.sink.valid)
        self.comb += frame.eq(self.sink.vsync & self.sink.valid & ~vsync_r)

        self.avi = avig = ClockDomainsRenamer("pix")(AVIInfoFrameGenerator())
        self.gcp = gcpg = ClockDomainsRenamer("pix")(GCPGenerator())
        f = avig.fields
        self.comb += [
            Cat(f.y, f.a, f.b, f.s, f.c, f.m, f.r, f.itc, f.ec, f.q, f.sc, f.vic).eq(avi),
            Cat(f.yq, f.cn, f.pr).eq(avi2),
            avig.trigger.eq(frame & ctl[3]),
            avig.source.connect(avi_sink),
            gcpg.avmute.eq(ctl[2]),
            gcpg.trigger.eq(frame),
            gcpg.source.connect(gcp_sink),
        ]

        # Status back to sys.
        frame_count = Signal(32)
        self.sync.pix += If(frame, frame_count.eq(frame_count + 1))
        self.specials += [
            MultiReg(framer.hs2de,        self.status.fields.hs2de),
            MultiReg(framer.hs2de_valid,  self.status.fields.hs2de_valid),
            MultiReg(framer.max_packets,  self.status.fields.max_packets),
            MultiReg(framer.island_count, self.island_count.status),
            MultiReg(frame_count,         self.frame_count.status),
        ]
