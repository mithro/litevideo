#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Desktop-side helpers for the NeTV2 rig on rpi5-netv2.

The Raspberry Pi 5 host carries the NeTV2 (XC7A100T) on its GPIO header
(JTAG through openFPGALoader's rp1pio cable, UART on /dev/ttyAMA0) and a
Magewell XI100DUSB-HDMI capture device on USB (/dev/video0, ALSA card
XI100DUSBHDMI) cabled to the board's HDMI output. Everything runs over ssh;
bitstreams are loaded volatile (SRAM) only, never written to flash.

Coordination rule: announce every load to the peer sessions using the board
before calling ``load``; this module does not do that for you.
"""

import datetime
import hashlib
import json
import os
import shlex
import subprocess

HOST = "tim@rpi5-netv2.welland.mithis.com"
REMOTE_DIR = "/home/tim/litevideo"
UART = "/dev/ttyAMA0"
VIDEO = "/dev/video0"
ALSA = "hw:XI100DUSBHDMI"
JTAG = ["sudo", "openFPGALoader", "-c", "rp1pio", "--pins=27:22:4:17"]

HERE = os.path.dirname(os.path.abspath(__file__))


def ssh(args, check=True, timeout=120):
    """Run a command on the Pi; ``args`` is a list (quoted for the remote shell)."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", HOST, " ".join(shlex.quote(a) for a in args)]
    return subprocess.run(cmd, check=check, capture_output=True, text=True, timeout=timeout)


def copy_to(local, remote_name=None):
    remote_name = remote_name or os.path.basename(local)
    ssh(["mkdir", "-p", REMOTE_DIR])
    subprocess.run(["scp", "-q", local, f"{HOST}:{REMOTE_DIR}/{remote_name}"], check=True)
    return f"{REMOTE_DIR}/{remote_name}"


def copy_from(remote_name, local):
    subprocess.run(["scp", "-q", f"{HOST}:{REMOTE_DIR}/{remote_name}", local], check=True)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(bitstream):
    """Volatile JTAG load; returns the openFPGALoader output."""
    remote = copy_to(bitstream)
    r = ssh(JTAG + [remote], timeout=300)
    out = r.stdout + r.stderr
    if "Done" not in out and "done" not in out:
        raise RuntimeError(f"openFPGALoader did not report completion:\n{out}")
    return out


def install_client(csr_csv):
    copy_to(os.path.join(HERE, "uartbone.py"))
    return copy_to(csr_csv, "csr.csv")


def csr_read(names):
    r = ssh(["python3", f"{REMOTE_DIR}/uartbone.py", "--port", UART, "--csr", f"{REMOTE_DIR}/csr.csv", "read"] + list(names))
    return json.loads(r.stdout)


def csr_write(name, value):
    ssh(["python3", f"{REMOTE_DIR}/uartbone.py", "--port", UART, "--csr", f"{REMOTE_DIR}/csr.csv", "write", name, f"{value:#x}"])


def capture_frame(local_png, width=1280, height=720, frames=3):
    """Grab ``frames`` frames from the Magewell and keep the last one as PNG."""
    ssh(["ffmpeg", "-loglevel", "error", "-y", "-f", "v4l2", "-video_size", f"{width}x{height}",
         "-i", VIDEO, "-frames:v", str(frames), "-update", "1", f"{REMOTE_DIR}/frame.png"], timeout=60)
    copy_from("frame.png", local_png)


def capture_format():
    return ssh(["v4l2-ctl", "-d", VIDEO, "--get-fmt-video"], check=False).stdout


def capture_audio(local_wav, seconds=2, rate=48000):
    ssh(["arecord", "-q", "-D", ALSA, "-f", "S16_LE", "-r", str(rate), "-c", "2", "-d", str(seconds),
         f"{REMOTE_DIR}/audio.wav"], timeout=60)
    copy_from("audio.wav", local_wav)


def report(path, title, bitstream, rows, notes=()):
    """Write a markdown report; ``rows`` = [(check, result, detail)]."""
    now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [f"# {title}", "", f"Date: {now}. Host: `{HOST}`. Bitstream: `{os.path.basename(bitstream)}` "
             f"(SHA-256 `{sha256(bitstream)}`), volatile JTAG load.", "",
             "| Check | Result | Detail |", "|---|---|---|"]
    for check, result, detail in rows:
        lines.append(f"| {check} | {result} | {detail} |")
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path
