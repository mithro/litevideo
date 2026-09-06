#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Toolchain test: one CSCMatrix with CSR-loaded coefficients and pixels.

Built to reproduce the wrong colour arithmetic seen from the openXC7 flow
(doc/toolchains.md): software loads a coefficient set and a pixel over
uartbone, reads the matrix output and compares with
``colorimetry.apply_quantized``. Everything runs in the ``sys`` domain.

    uv run python -m bench.netv2.csc_test --build --toolchain vivado
    uv run python -m bench.netv2.csc_test --build --toolchain openxc7
    uv run python -m bench.netv2.host.run_csc_test --build build/netv2-csc-test-openxc7
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect.csr import *

from litevideo.csc.matrix import CSCMatrix

from bench.netv2.common import BenchSoC, bench_main


class CSCTestSoC(BenchSoC):
    def __init__(self, **kwargs):
        BenchSoC.__init__(self, ident="LiteVideo NeTV2 CSC matrix toolchain test", with_pix=False, **kwargs)
        self.matrix = m = CSCMatrix(dw=8, cw=12)
        for i in range(3):
            setattr(self, f"offset{i}", CSRStorage(23, name=f"offset{i}", description=f"offset {i} (signed, scaled by 4096)"))
            for j in range(3):
                setattr(self, f"coef{i}{j}", CSRStorage(15, name=f"coef{i}{j}", description=f"coefficient [{i}][{j}] (signed, 12 fractional bits)"))
        self.limits = CSRStorage(fields=[CSRField("min", 8, reset=0), CSRField("max", 8, reset=255)])
        self.pixel = CSRStorage(fields=[CSRField("c0", 8), CSRField("c1", 8), CSRField("c2", 8)])
        self.result = CSRStatus(fields=[CSRField("c0", 8), CSRField("c1", 8), CSRField("c2", 8)])
        for i in range(3):
            self.comb += [m.offsets[i].eq(getattr(self, f"offset{i}").storage), m.mins[i].eq(self.limits.fields.min), m.maxs[i].eq(self.limits.fields.max)]
            for j in range(3):
                self.comb += m.coefs[i][j].eq(getattr(self, f"coef{i}{j}").storage)
        self.comb += [
            m.sink.c0.eq(self.pixel.fields.c0), m.sink.c1.eq(self.pixel.fields.c1), m.sink.c2.eq(self.pixel.fields.c2),
            self.result.fields.c0.eq(m.source.c0), self.result.fields.c1.eq(m.source.c1), self.result.fields.c2.eq(m.source.c2),
        ]


def main():
    bench_main(CSCTestSoC, "LiteVideo NeTV2 CSC matrix toolchain test.", "netv2-csc-test")


if __name__ == "__main__":
    main()
