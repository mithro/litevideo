#!/usr/bin/env python3
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-core resource estimates with Yosys (``synth_xilinx -family xc7``).

Each core is elaborated standalone with Migen, written to Verilog and
synthesised by Yosys; the cell counts (LUTs, flip-flops, carry chains,
DSP48E1, RAMB) are collected into a Markdown table.

    uv run python scripts/resources.py            # table on stdout
    uv run python scripts/resources.py --only framer,converter

Numbers are estimates for comparison between cores and revisions, not
place-and-route results (see doc/toolchains.md for those).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

from migen import *
from migen.fhdl import verilog

from litex.gen import *


def cores():
    from litevideo.hdmi.tmds import TMDSCharacterDecoder
    from litevideo.hdmi.period import HDMIPeriodDecoder
    from litevideo.hdmi.island import DataIslandDecoder, DataIslandEncoder
    from litevideo.hdmi.framer import HDMIFramer
    from litevideo.hdmi.scheduler import PacketScheduler
    from litevideo.hdmi.infoframe import AVIInfoFrameGenerator, GCPGenerator
    from litevideo.hdmi.audio.packetizer import AudioSamplePacketizer
    from litevideo.hdmi.audio.acr import ACRGenerator
    from litevideo.hdmi.audio.infoframe import AudioInfoFrameGenerator
    from litevideo.hdmi.audio.extract import AudioExtract
    from litevideo.hdmi.audio.sources import ToneGenerator
    from litevideo.csc.matrix import CSCMatrix
    from litevideo.csc.colorimetry import rgb2ycbcr_matrix, BT709
    from litevideo.csc.wire422 import YCbCr444ToWire422, Wire422ToYCbCr444
    from litevideo.csc.convert import PixelFormatConverter
    from litevideo.csc.rgb2ycbcr import RGB2YCbCr
    from litevideo.csc.ycbcr2rgb import YCbCr2RGB
    return {
        "tmds_decoder":        lambda: TMDSCharacterDecoder(0),
        "period_decoder":      HDMIPeriodDecoder,
        "island_decoder":      DataIslandDecoder,
        "island_encoder":      DataIslandEncoder,
        "framer":              HDMIFramer,
        "scheduler_5":         lambda: PacketScheduler(5),
        "avi_infoframe":       AVIInfoFrameGenerator,
        "gcp":                 GCPGenerator,
        "audio_packetizer":    AudioSamplePacketizer,
        "acr":                 lambda: ACRGenerator(6144, 74250),
        "audio_infoframe":     AudioInfoFrameGenerator,
        "audio_extract":       AudioExtract,
        "tone_generator":      lambda: ToneGenerator(74.25e6, 48000, 1000.0),
        "csc_matrix_const":    lambda: CSCMatrix(matrix=rgb2ycbcr_matrix(BT709)),
        "csc_matrix_runtime":  lambda: CSCMatrix(),
        "wire422_pack":        YCbCr444ToWire422,
        "wire422_unpack":      Wire422ToYCbCr444,
        "pixel_format_conv":   PixelFormatConverter,
        "rgb2ycbcr_xapp930":   RGB2YCbCr,
        "ycbcr2rgb_xapp931":   YCbCr2RGB,
    }


def module_ios(m):
    """All Signals reachable as attributes (one level, plus Records/Endpoints) become ports."""
    ios = set()
    const_inputs = {"coefs", "offsets", "mins", "maxs"} if getattr(m, "constant", False) else set()
    for name in dir(m):
        if name.startswith("_") or name in const_inputs:
            continue
        try:
            obj = getattr(m, name)
        except Exception:
            continue
        if isinstance(obj, Signal):
            ios.add(obj)
        elif isinstance(obj, Record):
            ios |= set(obj.flatten())
        elif isinstance(obj, list) and obj and all(isinstance(x, Record) for x in obj):
            for r in obj:
                ios |= set(r.flatten())
        elif isinstance(obj, list) and obj and all(isinstance(x, Signal) for x in obj):
            ios |= set(obj)
        elif isinstance(obj, list) and obj and all(isinstance(x, list) for x in obj):
            for row in obj:
                ios |= {x for x in row if isinstance(x, Signal)}
    return ios


STAT_RE = re.compile(r"^\s+(\S+)\s+(\d+)\s*$", re.M)


def synth(name, make, keep_dir=None):
    m = make()
    ios = module_ios(m)
    v = verilog.convert(m, ios=ios, name=name)
    d = keep_dir or tempfile.mkdtemp(prefix="litevideo-res-")
    src = os.path.join(d, f"{name}.v")
    with open(src, "w") as f:
        f.write(v.main_source)
    for fname, content in v.data_files.items():        # memory init files ($readmemh, relative paths)
        with open(os.path.join(d, fname), "w") as f:
            f.write(content)
    stat = os.path.join(d, f"{name}.stat")
    script = f"read_verilog {src}\nsynth_xilinx -family xc7 -top {name} -flatten\ntee -o {stat} stat\n"
    r = subprocess.run(["yosys", "-q", "-p", script], capture_output=True, text=True, cwd=d)
    if r.returncode != 0:
        return {"error": r.stderr.strip().splitlines()[-1] if r.stderr else "yosys failed"}
    cells = {}
    section = open(stat).read().split("Number of cells:")[-1]
    for cell, count in STAT_RE.findall(section):
        cells[cell] = cells.get(cell, 0) + int(count)
    if keep_dir is None:
        shutil.rmtree(d)
    return cells


def summarise(cells):
    def n(prefixes):
        return sum(v for k, v in cells.items() if any(k.startswith(p) for p in prefixes))
    return {
        "LUT":   n(["LUT1", "LUT2", "LUT3", "LUT4", "LUT5", "LUT6"]),
        "MUXF":  n(["MUXF"]),
        "FF":    n(["FDRE", "FDSE", "FDCE", "FDPE"]),
        "CARRY": n(["CARRY4"]),
        "DSP":   n(["DSP48"]),
        "BRAM":  n(["RAMB"]),
        "LUTRAM": n(["RAM32", "RAM64", "RAM128", "RAM256"]),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", default=None, help="comma-separated core names")
    p.add_argument("--keep", default=None, help="directory to keep the Verilog in")
    args = p.parse_args()
    table = cores()
    names = args.only.split(",") if args.only else list(table)
    print("| Core | LUTs | MUXF7/8 | FFs | CARRY4 | DSP48E1 | RAMB | LUTRAM |")
    print("|---|---|---|---|---|---|---|---|")
    for name in names:
        cells = synth(name, table[name], args.keep)
        if "error" in cells:
            print(f"| `{name}` | error: {cells['error']} | | | | | | |")
            continue
        s = summarise(cells)
        print(f"| `{name}` | {s['LUT']} | {s['MUXF']} | {s['FF']} | {s['CARRY']} | {s['DSP']} | {s['BRAM']} | {s['LUTRAM']} |")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
