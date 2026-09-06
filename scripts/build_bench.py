#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Build a NeTV2 bench with one of the flows, inside the cgroup scope.

    uv run python scripts/build_bench.py hdmi_tx vivado
    uv run python scripts/build_bench.py hdmi_tx yosys        # Yosys synth, Vivado P&R
    uv run python scripts/build_bench.py hdmi_tx openxc7      # fully open source (scripts/openxc7-env.sh)
    uv run python scripts/build_bench.py hdmi_rx vivado -- --clkin-freq 74.25e6

The build goes to build/netv2-<bench>[-<flow>] (Vivado keeps the bench's
default directory); extra arguments after ``--`` go to the bench. Vivado is
sourced from ``VIVADO_SETTINGS`` (default /opt/Xilinx/2025.2/Vivado/settings64.sh).
"""

import argparse
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_DIRS = {"hdmi_tx": "netv2-hdmi-tx", "hdmi_loopback": "netv2-hdmi-loopback", "hdmi_rx": None, "csc_test": "netv2-csc-test"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bench", choices=sorted(DEFAULT_DIRS))
    p.add_argument("flow", choices=["vivado", "yosys", "openxc7"])
    p.add_argument("--memory-max", default="12G")
    p.add_argument("--cpu-quota", default="600%")
    p.add_argument("--unit", default=None)
    p.add_argument("extra", nargs="*", help="arguments for the bench (after --)")
    args = p.parse_args()

    bench_cmd = ["uv", "run", "--no-sync", "python", "-m", f"bench.netv2.{args.bench}", "--build"]
    if args.flow == "vivado":
        bench_cmd += ["--toolchain", "vivado"]
    elif args.flow == "yosys":
        bench_cmd += ["--toolchain", "vivado", "--synth-mode", "yosys"]
    else:
        bench_cmd += ["--toolchain", "openxc7"]
    out = DEFAULT_DIRS[args.bench]
    if out is not None and args.flow != "vivado":
        out = f"{out}-{args.flow}"
        bench_cmd += ["--output-dir", f"build/{out}", "--csr-csv", f"build/{out}/csr.csv"]
    bench_cmd += args.extra

    env_lines = [f"cd {shlex.quote(ROOT)}"]
    if args.flow in ("vivado", "yosys"):
        env_lines.append(f"source {shlex.quote(os.environ.get('VIVADO_SETTINGS', '/opt/Xilinx/2025.2/Vivado/settings64.sh'))}")
    if args.flow == "openxc7":
        env_lines.append(f"source {shlex.quote(os.path.join(HERE, 'openxc7-env.sh'))}")
    script = " && ".join(env_lines) + " && exec " + shlex.join(bench_cmd)
    unit = args.unit or f"litevideo-{args.bench}-{args.flow}-{os.getpid()}"
    cmd = ["uv", "run", "--no-sync", os.path.join(HERE, "limited.py"), "--memory-max", args.memory_max,
           "--cpu-quota", args.cpu_quota, "--unit", unit, "--", "bash", "-c", script]
    print("+", shlex.join(cmd), file=sys.stderr)
    sys.exit(subprocess.call(cmd, cwd=ROOT))


if __name__ == "__main__":
    main()
