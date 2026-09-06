#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""NeTV2 bench SoC: CPU-less, CSRs over uartbone, pixel clocks from an MMCM.

The Kosagi/Alphamax NeTV2 (litex-boards ``kosagi_netv2``) has a 50 MHz
oscillator, two HDMI outputs and two HDMI inputs (TMDS_33). The bench SoCs
have no CPU: control and status registers are reached over LiteX's uartbone
bridge on the board's ``serial`` pads, which are wired to the Raspberry Pi
host's ``/dev/ttyAMA0`` (see doc/testing.md and bench/netv2/host/).
"""

from migen import *

from litex.gen import *
from litex.build.parser import LiteXArgumentParser
from litex.soc.cores.clock import S7PLL, S7MMCM
from litex.soc.integration.soc_core import SoCMini
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

# 720p60 (CEA VIC 4): 74.25 MHz pixel clock, 371.25 MHz serial clock. LiteX's
# S7MMCM picks the closest legal configuration from the 50 MHz oscillator
# within ``margin``; the achieved frequency is printed by compute_config at
# build time and recorded in doc/transmitter.md.
PIX_CLK_FREQ = 74.25e6
VIC_720P60   = 4


class CRG(LiteXModule):
    """sys from a PLL; optionally the self-timed pix/pix5x output clocks from an
    MMCM (transmitter benches) and a 200 MHz IDELAYCTRL reference (receiver)."""
    def __init__(self, platform, sys_clk_freq, with_pix=True, with_idelay=False):
        self.rst      = Signal()
        self.cd_sys   = ClockDomain()

        clk50 = platform.request("clk50")
        self.pll = pll = S7PLL(speedgrade=-2)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)

        if with_pix:
            self.cd_pix   = ClockDomain()
            self.cd_pix5x = ClockDomain()
            self.mmcm = mmcm = S7MMCM(speedgrade=-2)
            self.comb += mmcm.reset.eq(self.rst)
            mmcm.register_clkin(clk50, 50e6)
            mmcm.create_clkout(self.cd_pix,   PIX_CLK_FREQ,     margin=2e-3)
            mmcm.create_clkout(self.cd_pix5x, 5 * PIX_CLK_FREQ, margin=2e-3, with_reset=False)
            platform.add_false_path_constraints(self.cd_sys.clk, self.cd_pix.clk)

        if with_idelay:
            from litex.soc.cores.clock import S7IDELAYCTRL
            self.cd_idelay = ClockDomain()
            pll.create_clkout(self.cd_idelay, 200e6)
            self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)


class BenchSoC(SoCMini):
    def __init__(self, variant="a7-100", toolchain="vivado", sys_clk_freq=50e6, ident="LiteVideo NeTV2 bench",
                 with_pix=True, with_idelay=False, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)
        if toolchain == "openxc7":
            from bench.netv2.openxc7 import prepare_platform
            prepare_platform(platform)
        # The LiteX argument parser injects cpu_type="vexriscv", with_uart=True,
        # with_timer=True, an SRAM size and ident_version into soc_argdict;
        # this bench has no CPU (CSRs come over uartbone on the same "serial"
        # pads the SoC UART would take), so override them here.
        kwargs.update(cpu_type="None", with_uart=False, with_timer=False, integrated_sram_size=0,
                      ident=ident, ident_version=True)
        SoCMini.__init__(self, platform, sys_clk_freq, **kwargs)
        self.crg = CRG(platform, sys_clk_freq, with_pix=with_pix, with_idelay=with_idelay)
        self.add_uartbone(uart_name="serial", baudrate=115200)
        if toolchain == "openxc7":
            from bench.netv2.openxc7 import prepare_soc
            prepare_soc(self)


def bench_main(soc_cls, description, default_build_name):
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description=description)
    parser.add_target_argument("--variant", default="a7-100", choices=["a7-35", "a7-100"])
    args = parser.parse_args()
    soc = soc_cls(variant=args.variant, toolchain=args.toolchain, **parser.soc_argdict)
    builder_kwargs = parser.builder_argdict
    # builder_argdict already carries output_dir=None / csr_csv=None, so setdefault is a no-op.
    if builder_kwargs.get("output_dir") is None:
        builder_kwargs["output_dir"] = f"build/{default_build_name}"
    if builder_kwargs.get("csr_csv") is None:
        builder_kwargs["csr_csv"] = f"build/{default_build_name}/csr.csv"
    builder = Builder(soc, **builder_kwargs)
    builder.build(**parser.toolchain_argdict, run=args.build)
