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

Packet sources in priority order (HDMI 1.3 §7.8.2): Audio Sample Packets,
Audio Clock Regeneration, Audio InfoFrame (all three only with
``with_audio``), then General Control, then the AVI InfoFrame.

With ``with_audio`` the transmitter carries a built-in tone generator
(``litevideo.hdmi.audio.sources.ToneGenerator``) as its PCM source: it needs
``pix_clk_freq`` to derive the sample rate and picks N/CTS from HDMI Tables
7-1 to 7-3 when the pixel clock is a standard one (otherwise N from the
"Other" row and a CTS the integrator sets over CSR).
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
from litevideo.hdmi.audio.common import N_CTS, N_DEFAULT, SF_CODE, SS_24BIT
from litevideo.hdmi.audio.packetizer import AudioSamplePacketizer
from litevideo.hdmi.audio.acr import ACRGenerator
from litevideo.hdmi.audio.infoframe import AudioInfoFrameGenerator
from litevideo.hdmi.audio.sources import ToneGenerator, tone_increment


class HDMITransmitter(LiteXModule):
    def __init__(self, default_vic=4, extra_packet_sinks=0, with_audio=False, pix_clk_freq=None, fs=48000, tone_freq=1000.0):
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

        n_audio = 3 if with_audio else 0
        n_sinks = n_audio + extra_packet_sinks + 2
        self.scheduler = sched = ClockDomainsRenamer("pix")(PacketScheduler(n_sinks))
        self.comb += sched.source.connect(framer.packet_sink)
        audio_sinks = sched.sinks[:n_audio]
        self.extra_packet_sinks = sched.sinks[n_audio:n_audio + extra_packet_sinks]
        gcp_sink, avi_sink = sched.sinks[n_audio + extra_packet_sinks:]

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

        if with_audio:
            self.add_audio(audio_sinks, frame, pix_clk_freq, fs, tone_freq)

    def add_audio(self, sinks, frame, pix_clk_freq, fs, tone_freq):
        assert pix_clk_freq is not None, "with_audio needs pix_clk_freq"
        asp_sink, acr_sink, aif_sink = sinks
        n, cts = N_CTS.get((fs, int(round(pix_clk_freq))), (N_DEFAULT[fs], 0))

        self.audio_control = CSRStorage(fields=[
            CSRField("enable",         1, reset=1, description="Send audio packets."),
            CSRField("tone_enable",    1, reset=1, description="Run the built-in tone generator."),
            CSRField("send_acr",       1, reset=1, description="Send Audio Clock Regeneration packets."),
            CSRField("send_infoframe", 1, reset=1, description="Send the Audio InfoFrame once per frame."),
            CSRField("acr_measure",    1, reset=0, description="Measure CTS from a 128*fs strobe (needs an audio clock)."),
        ])
        self.audio_n   = CSRStorage(20, reset=n,   description="ACR N (HDMI 1.3 Tables 7-1 to 7-3).")
        self.audio_cts = CSRStorage(20, reset=cts, description="ACR CTS for the constant mode.")
        self.audio_infoframe = CSRStorage(fields=[
            CSRField("cc",     3, reset=1,            description="Channel count minus one (1 = 2 channels)."),
            CSRField("ct",     4, reset=0,            description="Coding type (0 = refer to stream header)."),
            CSRField("ss",     2, reset=SS_24BIT,     description="Sample size (3 = 24 bit)."),
            CSRField("sf",     3, reset=SF_CODE[fs],  description="Sample frequency (3 = 48 kHz)."),
            CSRField("ca",     8, reset=0,            description="Speaker allocation (0 = front L/R)."),
            CSRField("lsv",    4, reset=0,            description="Level shift value."),
            CSRField("dm_inh", 1, reset=0,            description="Down-mix inhibit."),
        ])
        self.tone_increment = CSRStorage(32, reset=tone_increment(tone_freq, fs),
                                         description="Tone phase increment per sample (freq / fs * 2^32).")
        self.audio_frames   = CSRStatus(32, description="Audio frames packetised.")
        self.audio_acrs     = CSRStatus(32, description="ACR packets generated.")
        self.audio_overruns = CSRStatus(32, description="Tone frames dropped because the packetizer was full.")

        actl = Signal(len(self.audio_control.storage))
        a_n = Signal(20)
        a_cts = Signal(20)
        a_if = Signal(len(self.audio_infoframe.storage))
        a_inc = Signal(32)
        self.specials += [
            MultiReg(self.audio_control.storage, actl, "pix"),
            MultiReg(self.audio_n.storage, a_n, "pix"),
            MultiReg(self.audio_cts.storage, a_cts, "pix"),
            MultiReg(self.audio_infoframe.storage, a_if, "pix"),
            MultiReg(self.tone_increment.storage, a_inc, "pix"),
        ]
        enable, tone_en, send_acr, send_if, measure = [actl[i] for i in range(5)]

        self.tone = tone = ClockDomainsRenamer("pix")(ToneGenerator(pix_clk_freq, fs, tone_freq))
        self.packetizer = pk = ClockDomainsRenamer("pix")(AudioSamplePacketizer(fs))
        self.acr = acr = ClockDomainsRenamer("pix")(ACRGenerator(n, cts))
        self.audio_if = aif = ClockDomainsRenamer("pix")(AudioInfoFrameGenerator())
        af = aif.fields
        self.comb += [
            tone.enable.eq(tone_en & enable),
            tone.tone_increment.eq(a_inc),
            tone.source.connect(pk.sink),
            pk.enable.eq(enable),
            pk.source.connect(asp_sink),
            acr.n.eq(a_n), acr.cts.eq(a_cts), acr.measure.eq(measure),
            acr.frame_strobe.eq(pk.frame_strobe & send_acr),
            acr.source.connect(acr_sink),
            Cat(af.cc, af.ct, af.ss, af.sf, af.ca, af.lsv, af.dm_inh).eq(a_if),
            aif.trigger.eq(frame & enable & send_if),
            aif.source.connect(aif_sink),
        ]
        self.specials += [
            MultiReg(pk.frames_sent, self.audio_frames.status),
            MultiReg(acr.acr_count, self.audio_acrs.status),
            MultiReg(tone.overruns, self.audio_overruns.status),
        ]
