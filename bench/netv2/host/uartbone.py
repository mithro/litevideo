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
    else:
        csr.write(args.name, int(args.value, 0))


if __name__ == "__main__":
    main()
