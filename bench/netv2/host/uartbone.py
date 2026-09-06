#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Minimal LiteX uartbone client: CSR read/write by name over a serial port.

Protocol (litex/tools/remote/comm_uart.py): command byte 0x02 (read) or 0x01
(write), length byte (words), 4-byte big-endian *word* address, then for
writes the big-endian 32-bit words; a read returns the words back to back.
The CSR map comes from the csr.csv the LiteX builder writes. Needs only
pyserial, so it runs on the Raspberry Pi host.

    uartbone.py --port /dev/ttyAMA0 --csr csr.csv read hdmi_tx_status
    uartbone.py --port /dev/ttyAMA0 --csr csr.csv write hdmi_tx_control 0x0b
    uartbone.py ... regs            # list registers
"""

import argparse
import csv
import json

import serial


class CSRMap:
    def __init__(self, path):
        self.regs = {}
        self.consts = {}
        with open(path) as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#"):
                    continue
                if row[0] == "csr_register":
                    _, name, addr, size, mode, *_ = row
                    self.regs[name] = (int(addr, 0), int(size))
                elif row[0] == "constant":
                    self.consts[row[1]] = row[2]
        self.data_width = int(self.consts.get("config_csr_data_width", 32))


class UARTBone:
    def __init__(self, port, baudrate=115200, timeout=1.0):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)

    def read_words(self, addr, n=1):
        self.ser.reset_input_buffer()
        self.ser.write(bytes([0x02, n]) + (addr // 4).to_bytes(4, "big"))
        raw = self.ser.read(4 * n)
        if len(raw) != 4 * n:
            raise TimeoutError(f"short read at {addr:#x}: {len(raw)} bytes")
        return [int.from_bytes(raw[4 * i:4 * i + 4], "big") for i in range(n)]

    def write_words(self, addr, words):
        self.ser.write(bytes([0x01, len(words)]) + (addr // 4).to_bytes(4, "big")
                       + b"".join(w.to_bytes(4, "big") for w in words))


class CSR:
    def __init__(self, bone, csrmap):
        self.bone, self.map = bone, csrmap

    def read(self, name):
        addr, size = self.map.regs[name]
        words = self.bone.read_words(addr, size)
        value = 0
        for w in words:
            value = (value << self.map.data_width) | (w & ((1 << self.map.data_width) - 1))
        return value

    def write(self, name, value):
        addr, size = self.map.regs[name]
        mask = (1 << self.map.data_width) - 1
        words = [(value >> (self.map.data_width * (size - 1 - i))) & mask for i in range(size)]
        self.bone.write_words(addr, words)


def align_channel(csr, prefix, slave_taps, iterations=300, settle=10):
    """Phase-align one litevideo S7DataCapture channel (the HDMI2USB
    ``hdmi_in`` firmware loop): reset both IDELAYs, offset the slave by
    ``slave_taps`` (about a quarter bit), then step master and slave together
    while the phase detector reports too late / too early. Returns
    (synced, iterations used, master taps, slave taps, last phase)."""
    import time
    DLY_RST, M_INC, M_DEC, S_INC, S_DEC = 1, 2, 4, 8, 16
    TOO_LATE, TOO_EARLY = 1, 2
    csr.write(f"{prefix}_cap_dly_ctl", DLY_RST)
    for _ in range(slave_taps):
        csr.write(f"{prefix}_cap_dly_ctl", S_INC)
    csr.write(f"{prefix}_cap_phase_reset", 1)
    stable = 0
    phase = 0
    for i in range(iterations):
        time.sleep(0.002)
        phase = csr.read(f"{prefix}_cap_phase")
        if phase & TOO_LATE:
            csr.write(f"{prefix}_cap_dly_ctl", M_DEC | S_DEC)
            stable = 0
        elif phase & TOO_EARLY:
            csr.write(f"{prefix}_cap_dly_ctl", M_INC | S_INC)
            stable = 0
        else:
            stable += 1
        csr.write(f"{prefix}_cap_phase_reset", 1)
        if stable >= settle and csr.read(f"{prefix}_charsync_char_synced"):
            break
    return {
        "synced": csr.read(f"{prefix}_charsync_char_synced"),
        "iterations": i + 1,
        "master_taps": csr.read(f"{prefix}_cap_cntvalueout_m"),
        "slave_taps": csr.read(f"{prefix}_cap_cntvalueout_s"),
        "phase": phase,
        "ctl_pos": csr.read(f"{prefix}_charsync_ctl_pos"),
    }


def _set_taps(csr, prefix, tap, slave_taps):
    csr.write(f"{prefix}_cap_dly_ctl", 1)                   # reset both IDELAYs
    for _ in range(slave_taps):
        csr.write(f"{prefix}_cap_dly_ctl", 8)               # slave +quarter bit
    for _ in range(tap):
        csr.write(f"{prefix}_cap_dly_ctl", 2 | 8)           # master and slave together


def _best_window(eye):
    """Centre of the longest circular run of 1s in ``eye``; (centre, length)."""
    n = len(eye)
    best_start, best_len = 0, 0
    for start in range(n):
        if not eye[start]:
            continue
        length = 0
        while length < n and eye[(start + length) % n]:
            length += 1
        if length > best_len:
            best_start, best_len = start, length
    return ((best_start + best_len // 2) % n if best_len else 0), best_len


def eye_scan(csr, slave_taps, settle=0.03, channels=3):
    """Align all channels with the channel synchroniser as the eye indicator
    (the per-channel phase detector's verdict does not track the eye on the
    sources tried; character sync stays asserted at every tap). First sweep
    the master tap of all channels together to find the joint window, then
    refine each channel with the others parked at the joint centre."""
    import time

    def synced():
        time.sleep(settle)
        a = csr.read("chansync_channels_synced")
        time.sleep(settle)
        return a & csr.read("chansync_channels_synced")

    joint = []
    for tap in range(32):
        for n in range(channels):
            _set_taps(csr, f"data{n}", tap, slave_taps)
        joint.append(synced())
    centre, run = _best_window(joint)
    result = {"joint_eye": "".join(map(str, joint)), "joint_centre": centre, "joint_run": run}
    taps = [centre] * channels
    for n in range(channels):
        for m in range(channels):
            _set_taps(csr, f"data{m}", taps[m], slave_taps)
        eye = []
        for tap in range(32):
            _set_taps(csr, f"data{n}", tap, slave_taps)
            eye.append(synced())
        c, r = _best_window(eye)
        if r:
            taps[n] = c
        result[f"data{n}"] = {"eye": "".join(map(str, eye)), "tap": taps[n], "run": r}
    for n in range(channels):
        _set_taps(csr, f"data{n}", taps[n], slave_taps)
        csr.write(f"data{n}_cap_phase_reset", 1)
    time.sleep(0.1)
    for n in range(channels):
        result[f"data{n}"].update({"synced": csr.read(f"data{n}_charsync_char_synced"),
                                   "master_taps": csr.read(f"data{n}_cap_cntvalueout_m"),
                                   "slave_taps": csr.read(f"data{n}_cap_cntvalueout_s"),
                                   "ctl_pos": csr.read(f"data{n}_charsync_ctl_pos")})
    result["chansync"] = csr.read("chansync_channels_synced")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baudrate", type=int, default=115200)
    p.add_argument("--csr", required=True, help="csr.csv from the build")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regs")
    r = sub.add_parser("read"); r.add_argument("names", nargs="+")
    w = sub.add_parser("write"); w.add_argument("name"); w.add_argument("value")
    d = sub.add_parser("drain", help="pop up to COUNT words from a FIFO exposed as data/valid/pop CSRs")
    d.add_argument("data"); d.add_argument("valid"); d.add_argument("pop"); d.add_argument("count", type=int)
    b = sub.add_parser("batch", help='run a JSON list of ops [["w", name, value], ["r", name], ["sleep", seconds]] and print the read results')
    b.add_argument("job")
    a = sub.add_parser("align", help="phase-align HDMI input channels data0..data2 (litevideo S7DataCapture)")
    a.add_argument("--slave-taps", type=int, default=5, help="initial slave IDELAY offset (about a quarter bit)")
    a.add_argument("--eye", action="store_true", help="eye scan with the channel synchroniser as indicator instead of the phase-detector loop")
    args = p.parse_args()
    csrmap = CSRMap(args.csr)
    if args.cmd == "regs":
        for name, (addr, size) in sorted(csrmap.regs.items(), key=lambda kv: kv[1][0]):
            print(f"{addr:#010x} {size:2d} {name}")
        return
    csr = CSR(UARTBone(args.port, args.baudrate), csrmap)
    if args.cmd == "read":
        print(json.dumps({n: csr.read(n) for n in args.names}))
    elif args.cmd == "drain":
        words = []
        while len(words) < args.count and csr.read(args.valid):
            words.append(csr.read(args.data))
            csr.write(args.pop, 1)
        print(json.dumps(words))
    elif args.cmd == "batch":
        import time
        out = []
        for op in json.load(open(args.job)):
            if op[0] == "w":
                csr.write(op[1], int(op[2]))
            elif op[0] == "r":
                out.append(csr.read(op[1]))
            elif op[0] == "sleep":
                time.sleep(float(op[1]))
        print(json.dumps(out))
    elif args.cmd == "align":
        if args.eye:
            print(json.dumps(eye_scan(csr, args.slave_taps)))
        else:
            print(json.dumps({f"data{n}": align_channel(csr, f"data{n}", args.slave_taps) for n in range(3)}))
    else:
        csr.write(args.name, int(args.value, 0))


if __name__ == "__main__":
    main()
