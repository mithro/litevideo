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


STATUS = ["hdmi_tx_status", "hdmi_tx_island_count", "hdmi_tx_frame_count", "tx_frame_crc", "tx_frames",
          "rx_periods_0", "rx_periods_1", "rx_periods_2", "rx_periods_3", "rx_islands", "rx_packets",
          "rx_ecc_errors", "rx_errors", "rx_last_header", "rx_frame_crc", "rx_frames"]


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

    a = rig.csr_read(STATUS)
    time.sleep(1.0)
    b = rig.csr_read(STATUS)

    def delta(name):
        return (b[name] - a[name]) & 0xFFFFFFFF

    def check(name, ok, detail):
        rows.append((name, "PASS" if ok else "FAIL", detail))
        return ok

    hs2de = b["hdmi_tx_status"] & 0xFFFF
    valid = (b["hdmi_tx_status"] >> 16) & 1
    maxp = (b["hdmi_tx_status"] >> 17) & 0x1F
    check("timing measured", valid == 1 and hs2de == 260, f"hs2de={hs2de} valid={valid} max_packets={maxp}")
    check("frames advance ~60/s", 50 <= delta("hdmi_tx_frame_count") <= 70, f"+{delta('hdmi_tx_frame_count')} frames in 1 s")
    check("islands advance", delta("hdmi_tx_island_count") > 0, f"+{delta('hdmi_tx_island_count')} islands")
    check("rx packets advance", delta("rx_packets") > 0, f"+{delta('rx_packets')} packets")
    check("no ECC errors", delta("rx_ecc_errors") == 0, f"+{delta('rx_ecc_errors')}")
    check("no island errors", delta("rx_errors") == 0, f"+{delta('rx_errors')}")
    check("last packet is AVI InfoFrame", (b["rx_last_header"] & 0xFF) == 0x82, f"header={b['rx_last_header']:#08x}")
    exp = expected_bars_crc()
    check("tx frame CRC = colour bars", b["tx_frame_crc"] == exp, f"{b['tx_frame_crc']:#010x} vs {exp:#010x}")
    check("rx frame CRC = tx frame CRC", b["rx_frame_crc"] == b["tx_frame_crc"], f"{b['rx_frame_crc']:#010x}")
    hist = {"video": (delta("rx_periods_1") >> 16) & 0xFFFF, "island": delta("rx_periods_3") & 0xFFFF}
    check("period histogram has VIDEO and DATA_ISLAND", hist["video"] > 0 and hist["island"] > 0, str(hist))

    # AVMUTE: last good header becomes a GCP (0x03) within a second.
    rig.csr_write("hdmi_tx_control", 0b1101)
    time.sleep(1.0)
    c = rig.csr_read(["rx_last_header"])
    check("AVMUTE sends GCP", (c["rx_last_header"] & 0xFF) in (0x03, 0x82), f"header={c['rx_last_header']:#08x}")
    rig.csr_write("hdmi_tx_control", 0b1001)

    # DVI mode: islands stop.
    rig.csr_write("hdmi_tx_control", 0b1011)
    time.sleep(0.5)
    d1 = rig.csr_read(["rx_islands"])
    time.sleep(1.0)
    d2 = rig.csr_read(["rx_islands"])
    check("DVI mode stops islands", d1["rx_islands"] == d2["rx_islands"], f"{d1['rx_islands']} -> {d2['rx_islands']}")
    rig.csr_write("hdmi_tx_control", 0b1001)

    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-loopback.md")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    rig.report(report, "NeTV2 tier T1: HDMI transmitter fabric loopback", bitstream, rows, notes)
    print(open(report).read())
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
