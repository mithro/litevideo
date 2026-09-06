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
from litevideo.csc.convert import PixelFormat, convert_line

# ColorBarsPattern: 8 bars of hres/8 pixels; LiteX's colours (video.py).
BARS = [(0xff, 0xff, 0xff), (0xff, 0xff, 0x00), (0x00, 0xff, 0xff), (0x00, 0xff, 0x00),
        (0xff, 0x00, 0xff), (0xff, 0x00, 0x00), (0x00, 0x00, 0xff), (0x00, 0x00, 0x00)]


def bars_row(hres=1280):
    return [BARS[min(7, x // (hres // 8))] for x in range(hres)]


def expected_bars_crc(hres=1280, vres=720):
    return frame_crc(bars_row(hres) * vres)


def expected_converted_crc(fmt_out, colorimetry, rgb_out_limited, ycc_limited, hres=1280, vres=720):
    """CRC of the bars as they appear on the wire after the transmitter's
    PixelFormatConverter (FrameCRC hashes (r, g, b) = wire channels (2, 1, 0))."""
    wire_in = [(b, g, r) for r, g, b in bars_row(hres)]
    row = convert_line(wire_in, PixelFormat.RGB, fmt_out, colorimetry, 0, rgb_out_limited, ycc_limited)
    return frame_crc([(c2, c1, c0) for c0, c1, c2 in row] * vres)


def avi_storage(y=0, c=0, q=2, vic=4, m=2, r=8):
    """avi_config storage word, field offsets taken from the transmitter's CSR definition."""
    from litevideo.hdmi.transmitter import HDMITransmitter
    f = HDMITransmitter(default_vic=vic).avi_config.fields
    return (y << f.y.offset) | (c << f.c.offset) | (m << f.m.offset) | (r << f.r.offset) | (q << f.q.offset) | (vic << f.vic.offset)


# (name, y, c, q) -> converter controls (fmt_out, colorimetry, rgb_out_limited, ycc_limited)
FORMATS = [
    ("RGB full (default)",      (0, 0, 2), (PixelFormat.RGB, 2, 0, 1)),
    ("RGB limited (Q=1)",       (0, 0, 1), (PixelFormat.RGB, 2, 1, 1)),
    ("RGB default Q on 720p",   (0, 0, 0), (PixelFormat.RGB, 2, 1, 1)),
    ("YCbCr 4:4:4 BT.709",      (2, 2, 0), (PixelFormat.YCBCR444, 2, 1, 1)),
    ("YCbCr 4:4:4 BT.601",      (2, 1, 0), (PixelFormat.YCBCR444, 1, 1, 1)),
    ("YCbCr 4:2:2 BT.709",      (1, 2, 0), (PixelFormat.YCBCR422, 2, 1, 1)),
    ("YCbCr 4:2:2 C default",   (1, 0, 0), (PixelFormat.YCBCR422, 2, 1, 1)),
]


def check_tone(samples, fs=48000, freq=1000.0):
    """samples: [(24-bit value, channel, b)]. Left/right must alternate and be
    equal, every value must be a ROM entry, block starts every 192 frames, and
    the spectrum must peak at ``freq``."""
    import numpy as np
    from litevideo.hdmi.audio.model import tone_table
    if len(samples) < 200:
        return False, f"only {len(samples)} samples drained"
    table = set(tone_table())
    chans = [c for _, c, _ in samples]
    start = chans.index(0)
    samples = samples[start:]
    frames = [(samples[i][0], samples[i + 1][0], samples[i][2]) for i in range(0, len(samples) - 1, 2)]
    if any(samples[i][1] != (i & 1) for i in range(len(samples))):
        return False, "channels do not alternate L/R"
    if any(l != r for l, r, _ in frames):
        return False, "left != right"
    bad = [l for l, _, _ in frames if l not in table]
    if bad:
        return False, f"{len(bad)} values not in the ROM, e.g. {bad[0]:#08x}"
    bstarts = [i for i, (_, _, b) in enumerate(frames) if b]
    if len(bstarts) >= 2 and any(b - a != 192 for a, b in zip(bstarts, bstarts[1:])):
        return False, f"block starts at {bstarts}"
    x = np.array([l - (1 << 24) if l & (1 << 23) else l for l, _, _ in frames], dtype=float)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    peak = int(np.argmax(spec[1:]) + 1)
    peak_hz = peak * fs / len(x)
    ok = abs(peak_hz - freq) <= fs / len(x)
    return ok, f"{len(frames)} frames, peak {peak_hz:.0f} Hz (bin {fs / len(x):.0f} Hz), block starts {bstarts[:3]}"


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
    last = b["main_rx_last_header"] & 0xFF
    check("last packet is a known type", last in (0x82, 0x02, 0x01, 0x84, 0x03),
          f"header={b['main_rx_last_header']:#08x} ({ {0x82: 'AVI', 0x02: 'ASP', 0x01: 'ACR', 0x84: 'Audio IF', 0x03: 'GCP'}.get(last, '?')})")
    exp = expected_bars_crc()
    check("tx frame CRC = colour bars", b["main_tx_frame_crc"] == exp, f"{b['main_tx_frame_crc']:#010x} vs {exp:#010x}")
    check("rx frame CRC = tx frame CRC", b["main_rx_frame_crc"] == b["main_tx_frame_crc"], f"{b['main_rx_frame_crc']:#010x}")
    hist = {"video": (delta("main_rx_periods_1") >> 16) & 0xFFFF, "island": delta("main_rx_periods_3") & 0xFFFF}
    check("period histogram has VIDEO and DATA_ISLAND", hist["video"] > 0 and hist["island"] > 0, str(hist))

    # Non-audio packets per frame: AVI + Audio InfoFrame = 2 normally, 3 (plus a
    # GCP) while AVMUTE is set. Audio Sample and Clock Regeneration packets are
    # subtracted using the extractor's counters, so the ratio is the robust
    # observable whatever the audio rate.
    def packets_per_frame():
        names = ["hdmi_tx_frame_count", "main_rx_packets", "main_audio_asps", "main_audio_acrs"]
        x = rig.csr_read(names)
        time.sleep(1.0)
        y = rig.csr_read(names)
        d = {n: (y[n] - x[n]) & 0xFFFFFFFF for n in names}
        other = d["main_rx_packets"] - d["main_audio_asps"] - d["main_audio_acrs"]
        return other / max(d["hdmi_tx_frame_count"], 1)

    r1 = packets_per_frame()
    check("two non-audio packets (AVI, Audio InfoFrame) per frame", 1.9 <= r1 <= 2.1, f"{r1:.2f} packets/frame")
    rig.csr_write("hdmi_tx_control", 0b1101)
    time.sleep(0.5)
    r2 = packets_per_frame()
    check("AVMUTE adds a GCP per frame", 2.9 <= r2 <= 3.1, f"{r2:.2f} packets/frame")
    rig.csr_write("hdmi_tx_control", 0b1001)

    # DVI mode: islands stop.
    rig.csr_write("hdmi_tx_control", 0b1011)
    time.sleep(0.5)
    d1 = rig.csr_read(["main_rx_islands"])
    time.sleep(1.0)
    d2 = rig.csr_read(["main_rx_islands"])
    check("DVI mode stops islands", d1["main_rx_islands"] == d2["main_rx_islands"], f"{d1['main_rx_islands']} -> {d2['main_rx_islands']}")
    rig.csr_write("hdmi_tx_control", 0b1001)

    # Pixel formats: the wire-side frame CRC follows the AVI configuration.
    for name, (y, c, q), ctrl in FORMATS:
        rig.csr_write("hdmi_tx_avi_config", avi_storage(y, c, q))
        time.sleep(0.2)
        got = rig.csr_read(["main_rx_frame_crc", "main_tx_frame_crc"])
        exp = expected_converted_crc(*ctrl)
        check(f"format {name}: rx frame CRC = model", got["main_rx_frame_crc"] == exp,
              f"{got['main_rx_frame_crc']:#010x} vs {exp:#010x} (tx input {got['main_tx_frame_crc']:#010x})")
    rig.csr_write("hdmi_tx_avi_config", avi_storage())

    # Audio: ACR, InfoFrame, lossless steady state (overruns do accumulate while
    # DVI mode stops the islands above, so count over a window), the tone.
    au_names = ["main_audio_n", "main_audio_cts", "main_audio_infoframe_rx", "main_audio_asps",
                "main_audio_acrs", "main_audio_samples", "main_audio_dropped",
                "hdmi_tx_audio_frames", "hdmi_tx_audio_overruns"]
    time.sleep(0.5)
    au0 = rig.csr_read(au_names)
    t_au = time.monotonic()
    time.sleep(5.0)
    au = rig.csr_read(au_names)
    dt_au = time.monotonic() - t_au
    dau = {n: (au[n] - au0[n]) & 0xFFFFFFFF for n in au_names}
    check("ACR N/CTS received", (au["main_audio_n"], au["main_audio_cts"]) == (6144, 74250),
          f"N={au['main_audio_n']} CTS={au['main_audio_cts']} (acr packets {au['main_audio_acrs']})")
    inf = au["main_audio_infoframe_rx"]
    cc, ct, ss, sf, ca, valid = inf & 7, (inf >> 3) & 0xF, (inf >> 7) & 3, (inf >> 9) & 7, (inf >> 12) & 0xFF, (inf >> 20) & 1
    check("Audio InfoFrame received (2ch, 48 kHz, 24 bit)", (cc, sf, ss, valid) == (1, 3, 3, 1),
          f"cc={cc} ct={ct} sf={sf} ss={ss} ca={ca} valid={valid}")
    check("audio lossless in steady state", dau["main_audio_dropped"] == 0 and dau["hdmi_tx_audio_overruns"] == 0
          and abs(dau["main_audio_samples"] - 2 * dau["hdmi_tx_audio_frames"]) <= dau["hdmi_tx_audio_frames"] // 100,
          f"over {dt_au:.1f} s: frames +{dau['hdmi_tx_audio_frames']} ({dau['hdmi_tx_audio_frames']/dt_au:.0f}/s), "
          f"subframes extracted +{dau['main_audio_samples']}, asps +{dau['main_audio_asps']}, acrs +{dau['main_audio_acrs']} "
          f"({dau['main_audio_acrs']/dt_au:.0f}/s), overruns +{dau['hdmi_tx_audio_overruns']}, dropped +{dau['main_audio_dropped']}")
    words = rig.csr_capture("audio_capture")
    samples = [(w & 0xFFFFFF, (w >> 24) & 7, (w >> 27) & 1) for w in words if w >> 31]
    ok, detail = check_tone(samples)
    check("extracted tone is the 1 kHz ROM sine", ok, detail)

    report = args.report or os.path.join("doc", "reports", time.strftime("%Y-%m-%d") + "-netv2-loopback.md")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    rig.report(report, "NeTV2 tier T1: HDMI transmitter fabric loopback", bitstream, rows, notes)
    print(open(report).read())
    sys.exit(0 if all(r[1] == "PASS" for r in rows) else 1)


if __name__ == "__main__":
    main()
