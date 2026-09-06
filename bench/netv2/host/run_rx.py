#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Tier T3: the LiteVideo receiver on NeTV2 hdmi_in 1 fed by the Raspberry Pi
5's own HDMI output (cabled on rpi5-netv2).

    uv run python -m bench.netv2.host.run_rx --build build/netv2-hdmi-rx-65 --expect 1024x768

Announce the load to the peer sessions first.
"""

import argparse
import json
import os
import sys
import time

from bench.netv2.host import rig

RX = ["main_raw_frame_crc", "main_rgb_frame_crc", "hdmi_rx_status", "hdmi_rx_timing", "hdmi_rx_avi", "hdmi_rx_frames", "hdmi_rx_islands", "hdmi_rx_packets",
      "hdmi_rx_ecc_errors", "hdmi_rx_period_errors", "hdmi_rx_avi_count",
      "hdmi_rx_periods_0", "hdmi_rx_periods_1", "hdmi_rx_periods_2", "hdmi_rx_periods_3",
      "hdmi_rx_audio_n", "hdmi_rx_audio_cts", "hdmi_rx_audio_infoframe", "hdmi_rx_audio_asps", "hdmi_rx_audio_acrs",
      "chansync_channels_synced", "clocking_locked"]


def pi_hdmi_state():
    r = rig.ssh(["cat", "/sys/class/drm/card1-HDMI-A-2/status", "/sys/class/drm/card1-HDMI-A-2/enabled",
                 "/sys/class/drm/card1-HDMI-A-2/modes"], check=False)
    return " ".join(r.stdout.split())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", required=True)
    p.add_argument("--expect", default="1024x768", help="expected active resolution WxH")
    p.add_argument("--clkin-freq", type=float, default=65e6, help="input pixel clock the bench was built for (Hz)")
    p.add_argument("--slave-taps", type=int, default=None,
                   help="initial slave IDELAY offset; default a quarter bit period at 78 ps/tap "
                        "(HDMI2USB-litex-firmware firmware/hdmi_in0.c calibrate_delays)")
    p.add_argument("--report", default=None)
    p.add_argument("--no-load", action="store_true")
    args = p.parse_args()

    bitstream = os.path.join(args.build, "gateware", "kosagi_netv2.bit")
    csr_csv = os.path.join(args.build, "csr.csv")
    rows, notes = [], []
    exp_w, exp_h = (int(v) for v in args.expect.split("x"))
    if args.slave_taps is None:
        args.slave_taps = round(1e12 / (4 * 10 * args.clkin_freq * 78))
    notes.append(f"slave IDELAY preload {args.slave_taps} taps for {args.clkin_freq/1e6:.2f} MHz")

    def check(name, ok, detail):
        rows.append((name, "PASS" if ok else "FAIL", detail))

    notes.append("Pi HDMI-A-2 before: " + pi_hdmi_state())
    rig.install_client(csr_csv)
    if not args.no_load:
        notes.append("openFPGALoader: " + rig.load(bitstream).strip().splitlines()[-1])
    time.sleep(2.0)

    lock = rig.csr_read(["clocking_locked"])["clocking_locked"]
    check("input MMCM locked to the TMDS clock", lock == 1, f"locked={lock}")
    if not lock:
        rig.report(args.report or "doc/reports/rx-failed.md", "NeTV2 tier T3: receiver", bitstream, rows, notes)
        sys.exit(1)

    r = rig.ssh(["python3", f"{rig.REMOTE_DIR}/uartbone.py", "--port", rig.UART, "--csr", f"{rig.REMOTE_DIR}/csr.csv",
                 "align", "--slave-taps", str(args.slave_taps)], timeout=600)
    align = json.loads(r.stdout)
    for ch, res in align.items():
        check(f"{ch} character sync", res["synced"] == 1, json.dumps(res))
    time.sleep(0.5)

    def window(seconds=2.0):
        a = rig.csr_read(RX)
        t0 = time.monotonic()
        time.sleep(seconds)
        b = rig.csr_read(RX)
        return a, b, time.monotonic() - t0

    a, b, dt = window()
    # A source without preambles (DVI, which is what the Pi sends with no EDID)
    # never produces a video period in HDMI mode: fall back to the DVI rule.
    dvi_fallback = ((b["hdmi_rx_periods_1"] >> 16) - (a["hdmi_rx_periods_1"] >> 16)) & 0xFFFF == 0 \
        and b["hdmi_rx_islands"] == a["hdmi_rx_islands"]
    if dvi_fallback:
        rig.csr_write("hdmi_rx_control", 0b11)   # dvi_mode | convert
        time.sleep(0.5)
        a, b, dt = window()
        notes.append("no preambles seen: receiver switched to DVI mode (control.dvi_mode)")

    check("channels synchronised", b["chansync_channels_synced"] == 1, f"{b['chansync_channels_synced']}")
    st = b["hdmi_rx_status"]
    hactive, vactive = (st >> 1) & 0x1FFF, (st >> 14) & 0x1FFF
    tm = b["hdmi_rx_timing"]
    htotal, vtotal = tm & 0x1FFF, (tm >> 13) & 0x1FFF
    check(f"active resolution {args.expect}", (hactive, vactive) == (exp_w, exp_h), f"{hactive}x{vactive}, total {htotal}x{vtotal}")
    fps = ((b["hdmi_rx_frames"] - a["hdmi_rx_frames"]) & 0xFFFFFFFF) / dt
    check("frame rate ~60 Hz", 55 <= fps <= 65, f"{fps:.1f} fps over {dt:.2f} s")
    check("no period errors", b["hdmi_rx_period_errors"] == a["hdmi_rx_period_errors"], f"+{(b['hdmi_rx_period_errors'] - a['hdmi_rx_period_errors']) & 0xFFFFFFFF}")
    hist = {"control": (b["hdmi_rx_periods_0"] - a["hdmi_rx_periods_0"]) & 0xFFFF,
            "video": ((b["hdmi_rx_periods_1"] >> 16) - (a["hdmi_rx_periods_1"] >> 16)) & 0xFFFF,
            "island": (b["hdmi_rx_periods_3"] - a["hdmi_rx_periods_3"]) & 0xFFFF}
    check("video periods seen", hist["video"] > 0 or (dvi_fallback and hactive > 0), str(hist))
    avi = b["hdmi_rx_avi"]
    # hdmi_rx_avi fields: y[1:0] c[3:2] q[5:4] vic[12:6] m[14:13] valid[15] checksum_ok[16]
    avi_valid = (avi >> 15) & 1
    islands = (b["hdmi_rx_islands"] - a["hdmi_rx_islands"]) & 0xFFFFFFFF
    mode = "HDMI (islands present)" if islands else "DVI (no islands)"
    if avi_valid:
        detail = f"y={avi & 3} c={(avi >> 2) & 3} q={(avi >> 4) & 3} vic={(avi >> 6) & 0x7F} m={(avi >> 13) & 3} checksum_ok={(avi >> 16) & 1}"
        check("AVI InfoFrame received", ((avi >> 16) & 1) == 1, detail)
    if dvi_fallback:
        mode = "DVI (no preambles, decoded with the DVI rule)"
    check("mode identified", True, f"{mode}: +{islands} islands, +{(b['hdmi_rx_packets'] - a['hdmi_rx_packets']) & 0xFFFFFFFF} packets, ECC errors +{(b['hdmi_rx_ecc_errors'] - a['hdmi_rx_ecc_errors']) & 0xFFFFFFFF}")
    if islands:
        n, cts = b["hdmi_rx_audio_n"], b["hdmi_rx_audio_cts"]
        check("audio ACR", True, f"N={n} CTS={cts} asps +{(b['hdmi_rx_audio_asps'] - a['hdmi_rx_audio_asps']) & 0xFFFFFFFF}")
    crcs = [rig.csr_read(["main_raw_frame_crc", "main_rgb_frame_crc"]) for _ in range(3)]
    check("frame CRC stable (static desktop)", len({c["main_raw_frame_crc"] for c in crcs}) == 1,
          "raw " + ", ".join(f"{c['main_raw_frame_crc']:#010x}" for c in crcs) + "; rgb " + ", ".join(f"{c['main_rgb_frame_crc']:#010x}" for c in crcs))
    notes.append("Pi HDMI-A-2 after: " + pi_hdmi_state())

    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-rx.md")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    rig.report(report, "NeTV2 tier T3: LiteVideo receiver on hdmi_in 1 (Pi 5 HDMI source)", bitstream, rows, notes)
    print(open(report).read())
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
