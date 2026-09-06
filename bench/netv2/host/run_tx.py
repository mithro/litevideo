#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Tier T4: load a transmitter bitstream on rpi5-netv2 and check the Magewell
capture shows the colour bars.

    uv run python -m bench.netv2.host.run_tx --build build/netv2-hdmi-tx

Announce the load to the peer sessions first.
"""

import argparse
import os
import sys
import time

from PIL import Image

from bench.netv2.host import rig
from bench.netv2.host.run_loopback import BARS

TOLERANCE = 40


def sample_bars(png, width=1280, height=720):
    img = Image.open(png).convert("RGB")
    got = []
    for i in range(8):
        x = int((i + 0.5) * width / 8)
        got.append(img.getpixel((x, height // 2)))
    return img.size, got


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", required=True)
    p.add_argument("--report", default=None)
    p.add_argument("--no-load", action="store_true")
    args = p.parse_args()

    bitstream = os.path.join(args.build, "gateware", "kosagi_netv2.bit")
    csr_csv = os.path.join(args.build, "csr.csv")
    rows, notes = [], []

    rig.install_client(csr_csv)
    if not args.no_load:
        notes.append("openFPGALoader: " + rig.load(bitstream).strip().splitlines()[-1])
    time.sleep(3.0)

    def check(name, ok, detail):
        rows.append((name, "PASS" if ok else "FAIL", detail))

    st = rig.csr_read(["hdmi_tx_status", "hdmi_tx_frame_count", "hdmi_tx_island_count"])
    check("transmitter running", (st["hdmi_tx_status"] >> 16) & 1 == 1, f"status={st['hdmi_tx_status']:#x} frames={st['hdmi_tx_frame_count']}")
    notes.append("Magewell format: " + " ".join(rig.capture_format().split()))

    outdir = os.path.join("doc", "reports", "captures")
    os.makedirs(outdir, exist_ok=True)
    for mode, ctl in (("hdmi", 0b1001), ("dvi", 0b1011), ("avmute", 0b1101)):
        rig.csr_write("hdmi_tx_control", ctl)
        time.sleep(1.5)
        png = os.path.join(outdir, f"{time.strftime('%Y-%m-%d')}-netv2-tx-{mode}.png")
        rig.capture_frame(png)
        size, got = sample_bars(png)
        ok = all(all(abs(a - b) <= TOLERANCE for a, b in zip(g, e)) for g, e in zip(got, BARS))
        black = all(sum(g) < 30 for g in got)
        detail = f"size={size} bars={got}" + (" (all black: no signal?)" if black else "")
        if mode == "avmute":
            check("AVMUTE capture (informational)", True, detail)
        else:
            check(f"{mode} mode colour bars captured", ok, detail)
    rig.csr_write("hdmi_tx_control", 0b1001)

    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-tx.md")
    rig.report(report, "NeTV2 tier T4: HDMI transmitter into the Magewell capture", bitstream, rows, notes)
    print(open(report).read())
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
