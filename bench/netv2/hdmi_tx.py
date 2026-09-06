#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Tier T4 bench: 720p60 colour bars with AVI InfoFrame on NeTV2 hdmi_out 0
(Magewell capture on rpi5-netv2).

    uv run python -m bench.netv2.hdmi_tx                      # elaborate only
    uv run scripts/limited.py -- uv run python -m bench.netv2.hdmi_tx --build --toolchain vivado
"""

from migen import *

from litex.gen import *
from litex.soc.cores.video import VideoTimingGenerator, ColorBarsPattern

from litevideo.hdmi.transmitter import HDMITransmitter
from litevideo.output.hdmi.s7 import S7HDMIOutEncoderSerializer, S7HDMIOutPHY

from bench.netv2.common import BenchSoC, bench_main, VIC_720P60, PIX_CLK_FREQ
from bench.netv2.frame_crc import FrameCRC


class HDMITxSoC(BenchSoC):
    def __init__(self, **kwargs):
        BenchSoC.__init__(self, ident="LiteVideo NeTV2 HDMI TX bench", **kwargs)
        platform = self.platform
        pads = platform.request("hdmi_out", 0)

        # CEA-861-D 1280x720p60 (VIC 4): front porch 110, sync 40, back porch 220,
        # vertical 5/5/20. LiteX's built-in "1280x720@60Hz" entry has the
        # horizontal front and back porch swapped (sync 220 after DE), which a
        # sink tolerates but is not the VIC 4 timing the AVI InfoFrame declares.
        self.vtg = ClockDomainsRenamer("pix")(VideoTimingGenerator(default_video_timings={
            "pix_clk": PIX_CLK_FREQ,
            "h_active": 1280, "h_blanking": 370, "h_sync_offset": 110, "h_sync_width": 40,
            "v_active": 720,  "v_blanking": 30,  "v_sync_offset": 5,   "v_sync_width": 5,
        }))
        self.bars = ClockDomainsRenamer("pix")(ColorBarsPattern())
        self.hdmi_tx = HDMITransmitter(default_vic=VIC_720P60)
        self.comb += [self.vtg.source.connect(self.bars.vtg_sink), self.bars.source.connect(self.hdmi_tx.sink)]

        # Clock lane: fixed 0000011111 pattern at the pixel rate (litevideo
        # convention); the serialiser honours the platform's Inverted() pads.
        self.clk_gen = S7HDMIOutEncoderSerializer(pads.clk_p, pads.clk_n, bypass_encoder=True)
        self.comb += self.clk_gen.data.eq(0b0000011111)
        self.phy = S7HDMIOutPHY(pads, mode="raw")
        self.comb += self.hdmi_tx.source.connect(self.phy.sink)

        self.frame_crc = ClockDomainsRenamer("pix")(FrameCRC())
        src = self.bars.source
        self.comb += [self.frame_crc.de.eq(src.de & src.valid), self.frame_crc.vsync.eq(src.vsync),
                      self.frame_crc.r.eq(src.r), self.frame_crc.g.eq(src.g), self.frame_crc.b.eq(src.b)]
        self.add_tx_status_csrs()

        platform.add_period_constraint(self.crg.cd_pix.clk,   1e9 / PIX_CLK_FREQ)
        platform.add_period_constraint(self.crg.cd_pix5x.clk, 1e9 / (5 * PIX_CLK_FREQ))

    def add_tx_status_csrs(self):
        from migen.genlib.cdc import MultiReg
        from litex.soc.interconnect.csr import CSRStatus
        self.tx_frame_crc = CSRStatus(32, description="CRC-32 of the last colour-bar frame sent (bars source).")
        self.tx_frames    = CSRStatus(32, description="Frames counted at the bars source.")
        self.specials += [
            MultiReg(self.frame_crc.crc,   self.tx_frame_crc.status),
            MultiReg(self.frame_crc.frame, self.tx_frames.status),
        ]


if __name__ == "__main__":
    bench_main(HDMITxSoC, "LiteVideo NeTV2 HDMI transmitter bench (720p colour bars).", "netv2-hdmi-tx")
