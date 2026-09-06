#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Drive bench/netv2/csc_test.py: load coefficient sets and pixels, compare
the hardware matrix output with the Python model.

    uv run python -m bench.netv2.host.run_csc_test --build build/netv2-csc-test-openxc7
"""

import argparse
import os
import random
import sys
import time

from bench.netv2.host import rig
from litevideo.csc import colorimetry as cm

CW = 12


def signed(v, bits):
    return v & ((1 << bits) - 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", required=True)
    p.add_argument("--no-load", action="store_true")
    p.add_argument("--pixels", type=int, default=64)
    p.add_argument("--report", default=None)
    args = p.parse_args()
    bitstream = os.path.join(args.build, "gateware", "kosagi_netv2.bit")
    rig.install_client(os.path.join(args.build, "csr.csv"))
    rows, notes = [], []
    if not args.no_load:
        notes.append("openFPGALoader: " + rig.load(bitstream).strip().splitlines()[-1])
    time.sleep(1.0)

    matrices = {
        "identity":            cm.identity_matrix(),
        "bt709 rgb->ycc":      cm.rgb2ycbcr_matrix(cm.BT709, cm.FULL, cm.LIMITED),
        "bt601 ycc->rgb":      cm.ycbcr2rgb_matrix(cm.BT601, cm.LIMITED, cm.FULL),
        "rgb full->limited":   cm.rgb_range_matrix(cm.FULL, cm.LIMITED),
    }
    random.seed(7)
    pixels = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 0)]
    pixels += [tuple(random.randint(0, 255) for _ in range(3)) for _ in range(max(0, args.pixels - len(pixels)))]
    ops = []
    for name, mat in matrices.items():
        q = cm.quantize(mat, CW)
        for i in range(3):
            ops.append(("w", f"main_offset{i}", signed(q.offsets[i], 23)))
            for j in range(3):
                ops.append(("w", f"main_coef{i}{j}", signed(q.m[i][j], 15)))
        ops.append(("w", "main_limits", q.mins[0] | (q.maxs[0] << 8)))
        for px in pixels:
            ops.append(("w", "main_pixel", px[0] | (px[1] << 8) | (px[2] << 16)))
            ops.append(("r", "main_result"))
    results = iter(rig.csr_batch(ops))
    for name, mat in matrices.items():
        q = cm.quantize(mat, CW)
        q = cm.Matrix(q.m, q.offsets, [q.mins[0]] * 3, [q.maxs[0]] * 3)   # the test SoC has one min/max pair
        bad = []
        for px in pixels:
            r = next(results)
            got = (r & 0xFF, (r >> 8) & 0xFF, (r >> 16) & 0xFF)
            exp = cm.apply_quantized(q, CW, px)
            if got != exp:
                bad.append(f"{px} -> {got} expected {exp}")
        rows.append((f"matrix {name}: {len(pixels)} pixels", "PASS" if not bad else "FAIL",
                     "all match" if not bad else f"{len(bad)} wrong, e.g. " + "; ".join(bad[:3])))
        print(rows[-1])
    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-csc-test.md")
    rig.report(report, "NeTV2 CSC matrix toolchain test", bitstream, rows, notes)
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
