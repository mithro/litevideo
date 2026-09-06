#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Tier T1: load the fabric-loopback bitstream on rpi5-netv2 and check, over
uartbone, that the transmitter's islands decode in the fabric receiver.

    uv run python -m bench.netv2.host.run_loopback --build build/netv2-hdmi-loopback

Announce the load to the peer sessions first.
"""

import argparse
import os
import sys
import time

from bench.netv2.host import rig
from bench.netv2.frame_crc import frame_crc

# ColorBarsPattern: 8 bars of hres/8 pixels; LiteX's colours (video.py).
BARS = [(0xff, 0xff, 0xff), (0xff, 0xff, 0x00), (0x00, 0xff, 0xff), (0x00, 0xff, 0x00),
        (0xff, 0x00, 0xff), (0xff, 0x00, 0x00), (0x00, 0x00, 0xff), (0x00, 0x00, 0x00)]


def expected_bars_crc(hres=1280, vres=720):
    row = []
    for x in range(hres):
        row.append(BARS[min(7, x // (hres // 8))])
    return frame_crc(row * vres)


STATUS = ["hdmi_tx_status", "hdmi_tx_island_count", "hdmi_tx_frame_count", "main_tx_frame_crc", "main_tx_frames",
          "main_rx_periods_0", "main_rx_periods_1", "main_rx_periods_2", "main_rx_periods_3", "main_rx_islands", "main_rx_packets",
          "main_rx_ecc_errors", "main_rx_errors", "main_rx_last_header", "main_rx_frame_crc", "main_rx_frames"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", required=True, help="build directory (contains gateware/kosagi_netv2.bit and csr.csv)")
    p.add_argument("--report", default=None)
    p.add_argument("--no-load", action="store_true", help="assume the bitstream is already loaded")
    args = p.parse_args()

    bitstream = os.path.join(args.build, "gateware", "kosagi_netv2.bit")
    csr_csv = os.path.join(args.build, "csr.csv")
    rows = []
    notes = []

    rig.install_client(csr_csv)
    if not args.no_load:
        out = rig.load(bitstream)
        notes.append("openFPGALoader: " + out.strip().splitlines()[-1])
    time.sleep(2.0)

    # Each csr_read is one ssh round trip plus 16 uartbone reads at 115200 baud,
    # so time the interval instead of assuming it.
    a = rig.csr_read(STATUS)
    t0 = time.monotonic()            # both reads have the same ssh latency: time end to end
    time.sleep(1.0)
    b = rig.csr_read(STATUS)
    interval = time.monotonic() - t0

    def delta(name):
        return (b[name] - a[name]) & 0xFFFFFFFF

    def check(name, ok, detail):
        rows.append((name, "PASS" if ok else "FAIL", detail))
        return ok

    hs2de = b["hdmi_tx_status"] & 0xFFFF
    valid = (b["hdmi_tx_status"] >> 16) & 1
    maxp = (b["hdmi_tx_status"] >> 17) & 0x1F
    check("timing measured", valid == 1 and hs2de == 260, f"hs2de={hs2de} valid={valid} max_packets={maxp}")
    fps = delta("hdmi_tx_frame_count") / interval
    check("frames advance ~60/s", 55 <= fps <= 65, f"+{delta('hdmi_tx_frame_count')} frames in {interval:.2f} s = {fps:.1f} fps")
    check("islands advance", delta("hdmi_tx_island_count") > 0, f"+{delta('hdmi_tx_island_count')} islands")
    check("rx packets advance", delta("main_rx_packets") > 0, f"+{delta('main_rx_packets')} packets")
    check("no ECC errors", delta("main_rx_ecc_errors") == 0, f"+{delta('main_rx_ecc_errors')}")
    check("no island errors", delta("main_rx_errors") == 0, f"+{delta('main_rx_errors')}")
    check("last packet is AVI InfoFrame", (b["main_rx_last_header"] & 0xFF) == 0x82, f"header={b['main_rx_last_header']:#08x}")
    exp = expected_bars_crc()
    check("tx frame CRC = colour bars", b["main_tx_frame_crc"] == exp, f"{b['main_tx_frame_crc']:#010x} vs {exp:#010x}")
    check("rx frame CRC = tx frame CRC", b["main_rx_frame_crc"] == b["main_tx_frame_crc"], f"{b['main_rx_frame_crc']:#010x}")
    hist = {"video": (delta("main_rx_periods_1") >> 16) & 0xFFFF, "island": delta("main_rx_periods_3") & 0xFFFF}
    check("period histogram has VIDEO and DATA_ISLAND", hist["video"] > 0 and hist["island"] > 0, str(hist))

    # Packets per frame: 1 (AVI) normally, 2 (GCP + AVI, in one island) while
    # AVMUTE is set. The GCP is scheduled before the AVI, so "last header" stays
    # the AVI; the packet/frame ratio is the robust observable.
    def packets_per_frame():
        x = rig.csr_read(["hdmi_tx_frame_count", "main_rx_packets"])
        time.sleep(1.0)
        y = rig.csr_read(["hdmi_tx_frame_count", "main_rx_packets"])
        frames = (y["hdmi_tx_frame_count"] - x["hdmi_tx_frame_count"]) & 0xFFFFFFFF
        pkts = (y["main_rx_packets"] - x["main_rx_packets"]) & 0xFFFFFFFF
        return pkts / max(frames, 1)

    r1 = packets_per_frame()
    check("one packet (AVI) per frame", 0.9 <= r1 <= 1.1, f"{r1:.2f} packets/frame")
    rig.csr_write("hdmi_tx_control", 0b1101)
    time.sleep(0.5)
    r2 = packets_per_frame()
    check("AVMUTE adds a GCP per frame", 1.9 <= r2 <= 2.1, f"{r2:.2f} packets/frame")
    rig.csr_write("hdmi_tx_control", 0b1001)

    # DVI mode: islands stop.
    rig.csr_write("hdmi_tx_control", 0b1011)
    time.sleep(0.5)
    d1 = rig.csr_read(["main_rx_islands"])
    time.sleep(1.0)
    d2 = rig.csr_read(["main_rx_islands"])
    check("DVI mode stops islands", d1["main_rx_islands"] == d2["main_rx_islands"], f"{d1['main_rx_islands']} -> {d2['main_rx_islands']}")
    rig.csr_write("hdmi_tx_control", 0b1001)

    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-loopback.md")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    rig.report(report, "NeTV2 tier T1: HDMI transmitter fabric loopback", bitstream, rows, notes)
    print(open(report).read())
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
