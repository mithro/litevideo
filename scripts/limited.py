#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Run a command inside a transient systemd user scope with resource limits.

Synthesis tools (Vivado, Yosys, nextpnr) can take all the memory and CPU of a
shared machine. This wrapper puts the command in its own cgroup so the kernel
enforces the limits, without needing root:

    uv run scripts/limited.py -- vivado -mode batch -source build.tcl
    uv run scripts/limited.py --memory-max 8G --cpu-quota 400% -- make

Defaults suit a 12-core / 32 GB desktop shared with other developers: 12 GB
RAM, 2 GB swap, 6 cores worth of CPU time, low IO weight. When the memory
limit is hit the kernel kills the command (exit code 137) instead of swapping
the whole machine. See systemd.resource-control(5).
"""

import argparse
import os
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memory-max", default="12G", help="MemoryMax= (default 12G)")
    parser.add_argument("--swap-max", default="2G", help="MemorySwapMax= (default 2G)")
    parser.add_argument("--cpu-quota", default="600%", help="CPUQuota= (default 600%%, i.e. 6 cores)")
    parser.add_argument("--io-weight", default="50", help="IOWeight= (default 50, range 1-10000)")
    parser.add_argument("--unit", default=None, help="scope unit name (default: auto)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run (prefix with --)")
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no command given")
    if shutil.which("systemd-run") is None:
        print("limited.py: systemd-run not found; running without limits", file=sys.stderr)
        os.execvp(command[0], command)

    argv = ["systemd-run", "--user", "--scope", "--quiet",
            "-p", f"MemoryMax={args.memory_max}",
            "-p", f"MemorySwapMax={args.swap_max}",
            "-p", f"CPUQuota={args.cpu_quota}",
            "-p", f"IOWeight={args.io_weight}"]
    if args.unit:
        argv += ["--unit", args.unit]
    argv += ["--"] + command
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
