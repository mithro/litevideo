#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Receiver bench: HDMI input 1 of the NeTV2 (the Raspberry Pi 5's own HDMI-A-2
output is cabled there on rpi5-netv2) decoded by the LiteVideo receiver.

Front end: the upstream 7-series capture path (IBUFDS + IDELAYE2 + ISERDESE2
with the master/slave phase detector, 8:10 gearbox, character and channel
synchronisation) with MMCM clocking computed for ``--clkin-freq`` (65 MHz
for the Pi's EDID-less 1024x768 default, 74.25 MHz for 720p); EDID slave on
the input's DDC advertising 720p60 as the preferred mode with 2-channel
LPCM audio; then ``HDMIReceiver``.

    uv run python -m bench.netv2.hdmi_rx --clkin-freq 65e6
    uv run scripts/limited.py -- uv run python -m bench.netv2.hdmi_rx --clkin-freq 65e6 --build --toolchain vivado
"""

from migen import *

from litex.gen import *
from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

from litevideo.input.clocking import S7MMCMClocking
from litevideo.input.datacapture import S7DataCapture
from litevideo.input.charsync import CharSync
from litevideo.input.decoding import Decoding
from litevideo.input.chansync import ChanSync
from litevideo.input.edid import EDID, _default_edid
from litevideo.hdmi.receiver import HDMIReceiver

from bench.netv2.common import BenchSoC


def edid_prefer_720p(edid=_default_edid):
    """The stock NeTV2 EDID with 1280x720p60 as the preferred detailed timing
    and VIC 4 as the native short video descriptor (checksums recomputed)."""
    e = list(edid)
    # Detailed timing descriptor 1 (bytes 54..71): CEA-861-D 1280x720p60, 74.25 MHz.
    dtd = [0x01, 0x1D,             # pixel clock 7425 * 10 kHz
           0x00, 0x72, 0x51,       # hactive 1280, hblank 370
           0xD0, 0x1E, 0x20,       # vactive 720, vblank 30
           0x6E, 0x28, 0x55, 0x00, # hsync offset 110, width 40, vsync offset 5, width 5
           e[66], e[67], e[68],    # image size from the original
           0x00, 0x00, 0x1E]       # no borders; digital, separate syncs, positive polarities
    e[54:72] = dtd
    # CEA block video data block: VIC 4 native first, then VIC 16 non-native.
    ext = 128
    assert e[ext] == 0x02 and (e[ext + 4] >> 5) == 2, "unexpected CEA block layout"
    e[ext + 5], e[ext + 6] = 0x84, 0x10
    for base in (0, 128):
        e[base + 127] = (-sum(e[base:base + 127])) & 0xFF
    return e


class HDMIRxSoC(BenchSoC):
    def __init__(self, clkin_freq=65e6, **kwargs):
        BenchSoC.__init__(self, ident=f"LiteVideo NeTV2 HDMI RX bench ({clkin_freq/1e6:.2f} MHz)",
                          with_pix=False, with_idelay=True, **kwargs)
        platform = self.platform
        pads = platform.request("hdmi_in", 1)

        self.edid = EDID(pads, edid_prefer_720p())
        self.clocking = S7MMCMClocking(pads, clkin_freq)

        for n in range(3):
            cap = S7DataCapture(getattr(pads, f"data{n}_p"), getattr(pads, f"data{n}_n"))
            charsync = CharSync()
            decoding = Decoding()
            setattr(self, f"data{n}_cap", cap)
            setattr(self, f"data{n}_charsync", charsync)
            setattr(self, f"data{n}_decod", decoding)
            self.comb += [
                charsync.raw_data.eq(cap.d),
                decoding.valid_i.eq(charsync.synced),
                decoding.input.eq(charsync.data),
            ]
        self.chansync = ChanSync()
        self.comb += [
            self.chansync.valid_i.eq(self.data0_decod.valid_o & self.data1_decod.valid_o & self.data2_decod.valid_o),
            self.chansync.data_in0.eq(self.data0_decod.output),
            self.chansync.data_in1.eq(self.data1_decod.output),
            self.chansync.data_in2.eq(self.data2_decod.output),
        ]

        self.hdmi_rx = HDMIReceiver(with_audio=True)
        self.comb += [
            self.hdmi_rx.sink.valid.eq(self.chansync.chan_synced),
            self.hdmi_rx.sink.c0.eq(self.chansync.data_out0.raw),
            self.hdmi_rx.sink.c1.eq(self.chansync.data_out1.raw),
            self.hdmi_rx.sink.c2.eq(self.chansync.data_out2.raw),
        ]

        # The recovered clock family is asynchronous to sys.
        platform.add_period_constraint(pads.clk_p, 1e9 / clkin_freq)
        platform.add_false_path_constraints(self.crg.cd_sys.clk, self.clocking.cd_pix.clk)
        platform.add_false_path_constraints(self.crg.cd_sys.clk, self.clocking.cd_pix1p25x.clk)


def main():
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="LiteVideo NeTV2 HDMI receiver bench.")
    parser.add_target_argument("--variant", default="a7-100", choices=["a7-35", "a7-100"])
    parser.add_target_argument("--clkin-freq", default=65e6, type=float, help="nominal input pixel clock (Hz)")
    args = parser.parse_args()
    soc = HDMIRxSoC(variant=args.variant, toolchain=args.toolchain, clkin_freq=args.clkin_freq, **parser.soc_argdict)
    name = f"netv2-hdmi-rx-{int(args.clkin_freq / 1e6)}"
    builder_kwargs = parser.builder_argdict
    if builder_kwargs.get("output_dir") is None:
        builder_kwargs["output_dir"] = f"build/{name}"
    if builder_kwargs.get("csr_csv") is None:
        builder_kwargs["csr_csv"] = f"build/{name}/csr.csv"
    builder = Builder(soc, **builder_kwargs)
    builder.build(**parser.toolchain_argdict, run=args.build)


if __name__ == "__main__":
    main()
