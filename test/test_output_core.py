#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""VideoOutCore reads a 16x16 frame of incrementing bytes through a modelled
LiteDRAM read port and must stream them out in order."""

import unittest

from migen import *

from litedram.common import LiteDRAMNativePort

from litevideo.output.core import VideoOutCore


class DRAMMemory:
    def __init__(self, width, depth, init=[]):
        self.mem = list(init) + [0] * (depth - len(init))
        self.depth = depth

    @passive
    def read_generator(self, port):
        address = 0
        pending = 0
        while True:
            yield port.cmd.ready.eq(0)
            yield port.rdata.valid.eq(0)
            if pending:
                yield port.rdata.valid.eq(1)
                yield port.rdata.data.eq(self.mem[address % self.depth])
                yield
                yield port.rdata.valid.eq(0)
                yield port.rdata.data.eq(0)
                pending = 0
            elif (yield port.cmd.valid):
                pending = not (yield port.cmd.we)
                address = (yield port.cmd.addr)
                yield
                yield port.cmd.ready.eq(1)
            yield


class DUT(Module):
    def __init__(self):
        self.dram_port = LiteDRAMNativePort(mode="read", address_width=32, data_width=32, clock_domain="video")
        self.submodules.core = VideoOutCore(self.dram_port)
        self.sync += self.core.source.ready.eq(~self.core.source.ready)


@passive
def capture(dut, video_data):
    while True:
        if ((yield dut.core.source.valid) and (yield dut.core.source.ready) and (yield dut.core.source.de)):
            video_data.append((yield dut.core.source.data))
        yield


def configure(dut):
    for _ in range(100):
        yield
    ini = dut.core.initiator
    for name, value in (("hres", 16), ("hsync_start", 18), ("hsync_end", 20), ("hscan", 24),
                        ("vres", 16), ("vsync_start", 18), ("vsync_end", 20), ("vscan", 24),
                        ("base", 0), ("length", 16 * 16 * 4)):
        yield getattr(ini, name).storage.eq(value)
    yield
    yield ini.enable.storage.eq(1)
    for _ in range(4096):
        yield


class TestVideoOutCore(unittest.TestCase):
    def test_sequential_frame(self):
        for video_clk_ns in (20, 10, 5):
            with self.subTest(video_clk_ns=video_clk_ns):
                dut = DUT()
                mem = DRAMMemory(32, 1024, list(range(256)))
                video_data = []
                run_simulation(dut,
                    {"sys": [configure(dut)],
                     "video": [capture(dut, video_data), mem.read_generator(dut.dram_port)]},
                    clocks={"sys": 10, "video": video_clk_ns})
                self.assertGreater(len(video_data), 256)
                errors = sum(1 for a, b in zip(video_data, video_data[1:]) if b != (a + 1) % 256)
                self.assertEqual(errors, 0)
