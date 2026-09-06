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


def pi_reprobe():
    """Make the Pi re-read the bench EDID and re-select its preferred mode: there
    is no HPD line on hdmi_in 1, so force the DRM connector off and back on,
    which raises the hotplug event the compositor (labwc) needs to change mode."""
    rig.ssh(["sudo", "sh", "-c", "echo off > /sys/class/drm/card1-HDMI-A-2/status"], check=False)
    time.sleep(3.0)
    rig.ssh(["sudo", "sh", "-c", "echo detect > /sys/class/drm/card1-HDMI-A-2/status"], check=False)
    time.sleep(6.0)


def pi_tone(seconds=8, freq=1000.0, rate=48000):
    """Play a stereo sine on the Pi's HDMI-A-2 ALSA device (vc4hdmi1) in the background."""
    import numpy as np
    import wave
    n = int(rate * seconds)
    t = np.arange(n) / rate
    x = (0.5 * 32767 * np.sin(2 * np.pi * freq * t)).astype("<i2")
    local = os.path.join("tmp", "pi_tone.wav")
    os.makedirs("tmp", exist_ok=True)
    with wave.open(local, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.repeat(x, 2).tobytes())
    rig.copy_to(local, "pi_tone.wav")
    os.remove(local)
    rig.ssh(["sh", "-c", f"nohup aplay -q -D plughw:vc4hdmi1,0 {rig.REMOTE_DIR}/pi_tone.wav > /dev/null 2>&1 &"], check=False)


def check_captured_tone(words, fs=48000, freq=1000.0):
    """Captured subframes: left/right alternate, spectrum peaks at ``freq`` on both channels."""
    import numpy as np
    samples = [(w & 0xFFFFFF, (w >> 24) & 7) for w in words if w >> 31]
    if len(samples) < 200:
        return False, f"only {len(samples)} subframes captured"
    start = next(i for i, (_, c) in enumerate(samples) if c == 0)
    samples = samples[start:]
    if any(samples[i][1] != (i & 1) for i in range(len(samples))):
        return False, "channels do not alternate L/R"
    details = []
    ok = True
    for ch in (0, 1):
        x = np.array([v - (1 << 24) if v & (1 << 23) else v for v, c in samples if c == ch], dtype=float)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        peak = int(np.argmax(spec[1:]) + 1)
        peak_hz = peak * fs / len(x)
        rms = np.sqrt(np.mean(x ** 2)) / (1 << 23)
        ok = ok and abs(peak_hz - freq) <= 2 * fs / len(x) and rms > 0.01
        details.append(f"ch{ch}: peak {peak_hz:.0f} Hz (bin {fs / len(x):.0f} Hz), rms {rms:.3f} FS")
    return ok, f"{len(samples)} subframes; " + "; ".join(details)


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
    p.add_argument("--phase-loop", action="store_true", help="HDMI2USB phase-detector loop instead of the channel-sync eye scan")
    p.add_argument("--reprobe", action="store_true", help="force the Pi to re-read the bench EDID before measuring")
    p.add_argument("--tone", action="store_true", help="play a 1 kHz tone from the Pi and check the extracted audio")
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
    if args.reprobe:
        pi_reprobe()
        notes.append("Pi HDMI-A-2 after re-probe: " + pi_hdmi_state())

    rig.csr_write("hdmi_rx_control", 0b10)   # HDMI decoding, convert to RGB (a previous run may have left DVI mode)
    # The source clock may have restarted (re-probe, mode change): reset the
    # input MMCM and the IDELAYs so the ISERDES/BUFR path starts clean, then align.
    rig.csr_batch([("w", "clocking_mmcm_reset", 1), ("sleep", 0.1), ("w", "clocking_mmcm_reset", 0), ("sleep", 0.5)]
                  + [("w", f"data{n}_cap_dly_ctl", 1) for n in range(3)] + [("w", f"data{n}_cap_phase_reset", 1) for n in range(3)])
    time.sleep(0.5)
    lock = rig.csr_read(["clocking_locked"])["clocking_locked"]
    check("input MMCM locked to the TMDS clock", lock == 1, f"locked={lock}")
    if not lock:
        rig.report(args.report or "doc/reports/rx-failed.md", "NeTV2 tier T3: receiver", bitstream, rows, notes)
        sys.exit(1)

    r = rig.ssh(["python3", f"{rig.REMOTE_DIR}/uartbone.py", "--port", rig.UART, "--csr", f"{rig.REMOTE_DIR}/csr.csv",
                 "align", "--slave-taps", str(args.slave_taps)] + ([] if args.phase_loop else ["--eye"]), timeout=600)
    align = json.loads(r.stdout)
    if "joint_eye" in align:
        notes.append(f"eye scan: joint eye {align['joint_eye']} centre {align['joint_centre']} run {align['joint_run']}")
    for ch in ("data0", "data1", "data2"):
        res = align[ch]
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
    from litevideo.hdmi.receiver import HDMIReceiver
    rxf = HDMIReceiver(with_audio=True)   # CSR field offsets

    def field(word, csr, name):
        f = getattr(csr.fields, name)
        return (word >> f.offset) & ((1 << f.size) - 1)

    hactive, vactive = field(b["hdmi_rx_status"], rxf.status, "hactive"), field(b["hdmi_rx_status"], rxf.status, "vactive")
    htotal, vtotal = field(b["hdmi_rx_timing"], rxf.timing, "htotal"), field(b["hdmi_rx_timing"], rxf.timing, "vtotal")
    check(f"active resolution {args.expect}", (hactive, vactive) == (exp_w, exp_h), f"{hactive}x{vactive}, total {htotal}x{vtotal}")
    fps = ((b["hdmi_rx_frames"] - a["hdmi_rx_frames"]) & 0xFFFFFFFF) / dt
    check("frame rate ~60 Hz", 55 <= fps <= 65, f"{fps:.1f} fps over {dt:.2f} s")
    check("no period errors", b["hdmi_rx_period_errors"] == a["hdmi_rx_period_errors"], f"+{(b['hdmi_rx_period_errors'] - a['hdmi_rx_period_errors']) & 0xFFFFFFFF}")
    hist = {"control": (b["hdmi_rx_periods_0"] - a["hdmi_rx_periods_0"]) & 0xFFFF,
            "video": ((b["hdmi_rx_periods_1"] >> 16) - (a["hdmi_rx_periods_1"] >> 16)) & 0xFFFF,
            "island": (b["hdmi_rx_periods_3"] - a["hdmi_rx_periods_3"]) & 0xFFFF}
    check("video periods seen", hist["video"] > 0 or (dvi_fallback and hactive > 0), str(hist))
    avi = {n: field(b["hdmi_rx_avi"], rxf.avi, n) for n in ("y", "c", "q", "vic", "m", "yq", "valid", "checksum_ok")}
    islands = (b["hdmi_rx_islands"] - a["hdmi_rx_islands"]) & 0xFFFFFFFF
    mode = "HDMI (islands present)" if islands else "DVI (no islands)"
    if avi["valid"]:
        check("AVI InfoFrame received with a good checksum", avi["checksum_ok"] == 1,
              " ".join(f"{k}={v}" for k, v in avi.items()) + f" (+{(b['hdmi_rx_avi_count'] - a['hdmi_rx_avi_count']) & 0xFFFFFFFF} in the window)")
    if dvi_fallback:
        mode = "DVI (no preambles, decoded with the DVI rule)"
    check("mode identified", True, f"{mode}: +{islands} islands, +{(b['hdmi_rx_packets'] - a['hdmi_rx_packets']) & 0xFFFFFFFF} packets, ECC errors +{(b['hdmi_rx_ecc_errors'] - a['hdmi_rx_ecc_errors']) & 0xFFFFFFFF}")
    if islands:
        n, cts = b["hdmi_rx_audio_n"], b["hdmi_rx_audio_cts"]
        check("audio ACR", True, f"N={n} CTS={cts} asps +{(b['hdmi_rx_audio_asps'] - a['hdmi_rx_audio_asps']) & 0xFFFFFFFF}")
    if args.tone:
        pi_tone(seconds=20)
        time.sleep(3.0)
        x = rig.csr_read(["hdmi_rx_audio_asps", "hdmi_rx_audio_acrs", "hdmi_rx_audio_n", "hdmi_rx_audio_cts", "hdmi_rx_audio_infoframe"])
        words = rig.csr_capture("hdmi_rx_audio_capture")
        y = rig.csr_read(["hdmi_rx_audio_asps", "hdmi_rx_audio_acrs"])
        inf = x["hdmi_rx_audio_infoframe"]
        check("audio packets from the Pi", y["hdmi_rx_audio_asps"] > x["hdmi_rx_audio_asps"],
              f"asps +{y['hdmi_rx_audio_asps'] - x['hdmi_rx_audio_asps']}, acrs +{y['hdmi_rx_audio_acrs'] - x['hdmi_rx_audio_acrs']}, "
              f"N={x['hdmi_rx_audio_n']} CTS={x['hdmi_rx_audio_cts']}, infoframe cc={inf & 7} sf={(inf >> 9) & 7} ss={(inf >> 7) & 3} valid={(inf >> 20) & 1}")
        ok, detail = check_captured_tone(words)
        check("extracted 1 kHz tone from the Pi", ok, detail)
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
