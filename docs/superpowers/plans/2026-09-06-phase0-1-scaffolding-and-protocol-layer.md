# LiteVideo HDMI phases 0 and 1: scaffolding and protocol layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give LiteVideo a modern test/CI/packaging skeleton and a PHY-independent HDMI protocol layer (tokens, BCH ECC, golden model, TMDS character decoder, period decoder, data island decoder and encoder) that is bit-exact against a Python model and the HDMI 1.3 specification.

**Architecture:** New package `litevideo/hdmi/` holds pure-Migen, clock-domain-agnostic protocol modules (integrators wrap them with `ClockDomainsRenamer("pix")`). Every gateware module is checked in Migen simulation against `litevideo/hdmi/model.py`, which in turn is checked against hand-verified vectors. Existing code is only touched for LiteX 2026.04 compatibility and one typo. Streams use LiteX `stream.Endpoint` layouts so later phases can drop LiteX's own video cores in front of them.

**Tech Stack:** Python 3.9+, `uv`, Migen 0.9.2 (mithro/migen mirror rev 4c2ae8d), LiteX 2026.04, LiteDRAM 2026.04, pytest, Pillow (image tests). Spec: HDMI 1.3 (public copy at <https://fpga.mit.edu/6205/_static/F24/default_files/CEC_HDMI_Specification.pdf>), DVI 1.0 (<https://glenwing.github.io/docs/DVI-1.0.pdf>). Design: `docs/superpowers/specs/2026-09-06-litevideo-hdmi-design.md` on branch `claude-notes`.

**Working rules for every task:**
- Work in the worktree `/home/tim/github/mithro/litevideo/.worktrees/hdmi` on branch `hdmi-support`. Never `cd` into the main checkout. Never use bare `git stash`.
- Run Python only through `uv run` (after Task 1: `uv run pytest ...`). Hooks block `python -c`, heredocs, `2>/dev/null`, and files under `/tmp`; put throwaway scripts under a project-local `tmp/` and delete them.
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019hSUBC7wjGnRjSJEX1zt5k
  ```
- New source files start with the LiteX-style header:
  ```python
  #
  # This file is part of LiteVideo.
  #
  # Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
  # SPDX-License-Identifier: BSD-2-Clause
  ```
- Cite the spec section next to every protocol constant or rule (`# HDMI 1.3 §5.4.3 Table 5-x`).

---

## File structure

Created in phase 0:

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` | packaging + pinned dev environment (replaces `setup.py`) |
| `.github/workflows/ci.yml` | run `pytest` on push/PR |
| `scripts/limited.py` | run a command under `systemd-run --user --scope` cgroup limits |
| `test/__init__.py`, `test/common.py` | stream inserter/collector helpers shared by all tests |
| `test/data/lena.png` | image used by the csc tests (moved from `litevideo/csc/test/`) |
| `test/csc_model.py` | the Python `RAWImage` model (moved from `litevideo/csc/test/common.py`, Pillow API fixed) |
| `test/test_csc.py` | ported csc tests with assertions |
| `test/test_output_core.py` | ported `VideoOutCore` DMA test |
| `doc/README.md`, `doc/testing.md`, `doc/toolchains.md`, `doc/references.md` | documentation skeleton |

Modified in phase 0: `README.md`, `.gitignore`, `litevideo/output/common.py` (c2 width), `litevideo/output/core.py` and `litevideo/input/__init__.py` (`dw`/`aw` → `data_width`/`address_width`). Deleted: `setup.py`, `litevideo/csc/test/`, `litevideo/output/test/`.

Created in phase 1:

| Path | Responsibility |
|---|---|
| `litevideo/hdmi/__init__.py` | package doc, re-exports |
| `litevideo/hdmi/common.py` | tokens, period/packet constants, stream layouts, packet type codes |
| `litevideo/hdmi/bch.py` | BCH(32,24)/(64,56) ECC: Python reference and Migen serial step |
| `litevideo/hdmi/model.py` | Python golden model: TMDS/TERC4 coding, `Packet`, island/line token generation |
| `litevideo/hdmi/tmds.py` | `TMDSCharacterDecoder`: one 10-bit character → data/control/guard/TERC4 classification |
| `litevideo/hdmi/period.py` | `HDMIPeriodDecoder`: three characters → period, syncs, DE, pixels, island nibbles |
| `litevideo/hdmi/island/__init__.py` | re-exports |
| `litevideo/hdmi/island/decoder.py` | `DataIslandDecoder`: nibbles → packet stream with ECC check |
| `litevideo/hdmi/island/encoder.py` | `DataIslandEncoder`: packet stream → framed island token stream |
| `test/test_hdmi_bch.py`, `test/test_hdmi_model.py`, `test/test_hdmi_tmds.py`, `test/test_hdmi_period.py`, `test/test_hdmi_island_decoder.py`, `test/test_hdmi_island_encoder.py`, `test/test_hdmi_island_roundtrip.py` | tests |
| `doc/hdmi-protocol.md` | protocol documentation with spec references |

---

## Phase 0: scaffolding

### Task 1: packaging with `pyproject.toml` and a pinned `uv` environment

**Files:**
- Create: `pyproject.toml`
- Delete: `setup.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "litevideo"
version = "2026.04.dev0"
description = "Small footprint and configurable video cores"
readme = "README.md"
license = { text = "BSD-2-Clause" }
requires-python = ">=3.9"
authors = [{ name = "Florent Kermarrec", email = "florent@enjoy-digital.fr" }]
keywords = ["HDL", "FPGA", "hardware design", "HDMI"]
classifiers = [
    "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
    "Environment :: Console",
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: BSD License",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
]
dependencies = ["migen", "litex", "litedram"]

[project.optional-dependencies]
dev = ["pytest>=8", "pillow", "numpy"]

[project.urls]
Homepage = "https://github.com/enjoy-digital/litevideo"

[tool.setuptools.packages.find]
include = ["litevideo*"]
exclude = ["test*", "bench*", "doc*", "scripts*"]

[tool.setuptools.package-data]
litevideo = ["terminal/*.bin", "terminal/*.jpg"]

# Pinned to the LiteX 2026.04 family (same pins as the NeTV2 modernisation
# tree) so simulations and builds are reproducible. LiteX 2026.04 pins migen
# to a git.m-labs.hk SHA that is mirrored in mithro/migen.
[tool.uv.sources]
migen    = { git = "https://github.com/mithro/migen.git", rev = "4c2ae8dfeea37f235b52acb8166f12acaaae4f7c" }
litex    = { git = "https://github.com/enjoy-digital/litex.git", tag = "2026.04" }
litedram = { git = "https://github.com/enjoy-digital/litedram.git", tag = "2026.04" }

[tool.pytest.ini_options]
testpaths = ["test"]
addopts = "-q"
```

- [ ] **Step 2: Delete `setup.py`, extend `.gitignore`**

Run: `git rm -q setup.py`

Append to `.gitignore`:
```
# uv / local environments and scratch
.venv/
uv.lock.bak
tmp/
# simulation outputs
*.vcd
*.fst
# gateware builds
build/
```

- [ ] **Step 3: Sync the environment and lock**

Run: `rm -rf .venv && uv sync --extra dev 2>&1 | tail -5`
Expected: ends with `+ litevideo==2026.04.dev0 (from file://...)` and a `uv.lock` appears.

Run: `uv run python -m pytest --co -q 2>&1 | tail -2`
Expected: `no tests ran` (the `test/` directory does not exist yet) with exit code 5. That is fine.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock .gitignore
git commit -m "Add pyproject.toml with pinned LiteX 2026.04 dev environment, drop setup.py"
```

### Task 2: stream test helpers

**Files:**
- Create: `test/__init__.py` (empty), `test/common.py`

- [ ] **Step 1: Write `test/common.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Simulation helpers shared by the tests.

``stream_inserter`` drives a LiteX ``stream.Endpoint`` sink from a list of
dicts (one dict per beat, keys are field names), optionally with random
``valid`` gaps. ``stream_collector`` records beats from a source into a list of
dicts, optionally with random ``ready`` back-pressure. Both follow the LiteEth
``test/test_stream.py`` pattern.
"""

import random

from migen import *


def stream_inserter(endpoint, beats, seed=0, valid_rand=0, first_last=False, drain=64):
    """Generator: push ``beats`` (list of dicts) into ``endpoint`` (a sink),
    then idle for ``drain`` cycles so pipelined cores can flush (the
    simulation ends when the last non-passive generator returns)."""
    prng = random.Random(seed)
    for n, beat in enumerate(beats):
        while prng.randrange(100) < valid_rand:
            yield endpoint.valid.eq(0)
            yield
        yield endpoint.valid.eq(1)
        for name, value in beat.items():
            yield getattr(endpoint, name).eq(value)
        if first_last:
            yield endpoint.first.eq(n == 0)
            yield endpoint.last.eq(n == len(beats) - 1)
        yield
        while not (yield endpoint.ready):
            yield
    yield endpoint.valid.eq(0)
    if first_last:
        yield endpoint.first.eq(0)
        yield endpoint.last.eq(0)
    for _ in range(drain):
        yield


@passive
def stream_collector(endpoint, fields, dest, seed=0, ready_rand=0):
    """Passive generator: collect beats of ``endpoint`` (a source) into ``dest``.

    ``yield`` is not allowed inside a comprehension, hence the explicit loop."""
    prng = random.Random(seed)
    while True:
        ready = prng.randrange(100) >= ready_rand
        yield endpoint.ready.eq(ready)
        yield
        if ready and (yield endpoint.valid):
            beat = {}
            for name in fields:
                beat[name] = (yield getattr(endpoint, name))
            dest.append(beat)


def run_for(cycles):
    """Generator: idle for ``cycles`` clock cycles."""
    for _ in range(cycles):
        yield
```

Note the collector samples `valid` after the clock edge on which it drove `ready`; this is the standard Migen pattern (`ready` assigned, `yield`, then read).

- [ ] **Step 2: Commit**

```bash
git add test/__init__.py test/common.py
git commit -m "test: add stream inserter/collector helpers"
```

### Task 3: port the colour-space tests to pytest with assertions

**Files:**
- Move: `litevideo/csc/test/lena.png` → `test/data/lena.png`
- Move: `litevideo/csc/test/common.py` → `test/csc_model.py` (fix Pillow API)
- Create: `test/test_csc.py`
- Delete: `litevideo/csc/test/` (remaining `*_tb.py`, `Makefile`)

- [ ] **Step 1: Move the model and image**

```bash
mkdir -p test/data
git mv litevideo/csc/test/lena.png test/data/lena.png
git mv litevideo/csc/test/common.py test/csc_model.py
git rm -q -r litevideo/csc/test
```

In `test/csc_model.py` replace `Image.ANTIALIAS` with `Image.LANCZOS` (Pillow ≥ 10 removed `ANTIALIAS`), remove the unused `from migen import *`, `from litex.soc.interconnect.stream import *`, `import random`, `from copy import deepcopy` lines, and add the file header comment.

- [ ] **Step 2: Write the failing tests**

`test/test_csc.py`:

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Colour-space conversion tests: the Migen cores against the Python models in
``test/csc_model.py`` on a 32x32 crop of the classic test image."""

import os
import random
import unittest

from migen import *

from litevideo.csc.rgb2ycbcr import rgb2ycbcr_coefs, RGB2YCbCr
from litevideo.csc.ycbcr2rgb import ycbcr2rgb_coefs, YCbCr2RGB
from litevideo.csc.ycbcr444to422 import YCbCr444to422
from litevideo.csc.ycbcr422to444 import YCbCr422to444

from test.common import stream_inserter, stream_collector, run_for
from test.csc_model import RAWImage

LENA = os.path.join(os.path.dirname(__file__), "data", "lena.png")
SIZE = 32


def max_abs_diff(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


class TestRGB2YCbCr(unittest.TestCase):
    def test_against_model(self):
        image = RAWImage(rgb2ycbcr_coefs(8), LENA, SIZE)
        ref = RAWImage(rgb2ycbcr_coefs(8), LENA, SIZE)
        ref.rgb2ycbcr_model()

        dut = RGB2YCbCr()
        beats = [{"r": r, "g": g, "b": b} for r, g, b in zip(image.r, image.g, image.b)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=20),
            stream_collector(dut.source, ["y", "cb", "cr"], out, ready_rand=20),
        ])
        self.assertEqual(len(out), len(beats))
        for name in ("y", "cb", "cr"):
            diff = max_abs_diff([o[name] for o in out], getattr(ref, name))
            # 8-bit fixed-point coefficients: the datapath rounds differently
            # from the float model by at most a couple of LSB.
            self.assertLessEqual(diff, 3, f"{name}: max |hw - model| = {diff}")


class TestYCbCr2RGB(unittest.TestCase):
    def test_against_model(self):
        image = RAWImage(ycbcr2rgb_coefs(8), LENA, SIZE)
        image.rgb2ycbcr()                      # Wikipedia reference to get YCbCr inputs
        ref = RAWImage(ycbcr2rgb_coefs(8), LENA, SIZE)
        ref.rgb2ycbcr()
        ref.ycbcr2rgb_model()

        dut = YCbCr2RGB()
        beats = [{"y": y, "cb": cb, "cr": cr} for y, cb, cr in zip(image.y, image.cb, image.cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=20),
            stream_collector(dut.source, ["r", "g", "b"], out, ready_rand=20),
        ])
        self.assertEqual(len(out), len(beats))
        for name in ("r", "g", "b"):
            hw = [o[name] for o in out]
            model = [min(255, max(0, v)) for v in getattr(ref, name)]
            diff = max_abs_diff(hw, model)
            self.assertLessEqual(diff, 3, f"{name}: max |hw - model| = {diff}")


class TestYCbCr422to444(unittest.TestCase):
    def test_upsampling(self):
        prng = random.Random(42)
        y = [prng.randrange(256) for _ in range(32)]
        cb_cr = [prng.randrange(20, 200) for _ in range(32)]
        exp_cb = [cb_cr[2 * (i // 2)] for i in range(32)]
        exp_cr = [cb_cr[2 * (i // 2) + 1] for i in range(32)]

        dut = YCbCr422to444()
        beats = [{"y": yy, "cb_cr": c} for yy, c in zip(y, cb_cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sink, beats, valid_rand=30),
            stream_collector(dut.source, ["y", "cb", "cr"], out, ready_rand=30),
        ])
        self.assertEqual([o["y"] for o in out], y)
        self.assertEqual([o["cb"] for o in out], exp_cb)
        self.assertEqual([o["cr"] for o in out], exp_cr)


class TestYCbCrResampling(unittest.TestCase):
    """444 -> 422 -> 444: Y survives exactly and chroma comes back in equal
    pairs. Which two input pixels each pair averages depends on the
    ``YCbCr444to422Datapath.first`` alignment strobe, which only
    ``FrameExtraction`` drives (litevideo/input/analysis.py); this port of the
    old bench therefore checks pairing, not the mean. Phase 4 (pixel formats)
    reworks the 4:2:2 path and its tests."""
    def test_chain(self):
        prng = random.Random(7)
        n = 64
        y = [prng.randrange(256) for _ in range(n)]
        cb = [prng.randrange(256) for _ in range(n)]
        cr = [prng.randrange(256) for _ in range(n)]

        class DUT(Module):
            def __init__(self):
                self.submodules.down = YCbCr444to422()
                self.submodules.up = YCbCr422to444()
                self.comb += self.down.source.connect(self.up.sink)

        dut = DUT()
        beats = [{"y": a, "cb": b, "cr": c} for a, b, c in zip(y, cb, cr)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.down.sink, beats),
            stream_collector(dut.up.source, ["y", "cb", "cr"], out),
        ])
        self.assertEqual(len(out), n)
        self.assertEqual([o["y"] for o in out], y)
        for i in range(0, n, 2):
            for name in ("cb", "cr"):
                self.assertEqual(out[i][name], out[i + 1][name])
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest test/test_csc.py -v 2>&1 | tail -15`
Expected: 4 passed. Measured while reviewing this plan: all 1024 beats arrive (the inserter's `drain` covers the 8+3 cycle pipelines) and the maximum |hw - model| is 1 LSB on every channel, so the bound of 3 has margin. If a count assertion fails, the drain is too short for that core: raise `drain` in the call, not the bound.

- [ ] **Step 4: Commit**

```bash
git add -A test litevideo/csc
git commit -m "test: port colour-space benches to pytest with assertions"
```

### Task 4: LiteDRAM 2026.04 port names and the output core test

**Files:**
- Modify: `litevideo/output/core.py` (lines 48, 55-58, 205-206), `litevideo/input/__init__.py` (line 141)
- Create: `test/test_output_core.py`
- Delete: `litevideo/output/test/`

- [ ] **Step 1: Rename port attributes**

In `litevideo/output/core.py` replace every `dram_port.dw` with `dram_port.data_width` and every `dram_port.aw` with `dram_port.address_width`. In `litevideo/input/__init__.py` line 141 replace `dram_port.dw` with `dram_port.data_width`. (LiteDRAM 2026.04 `LiteDRAMNativePort(mode, address_width, data_width, clock_domain)`, see `litedram/common.py:341`; it still carries `dw`/`aw` compatibility aliases at lines 355-357, so this is a modernisation, not a fix.)

- [ ] **Step 2: Write the test**

`test/test_output_core.py` (port of `litevideo/output/test/core_tb.py`):

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""VideoOutCore reads a 16x16 frame of incrementing bytes through a modelled
LiteDRAM read port and must stream them out in order."""

import unittest

from migen import *

from litedram.common import LiteDRAMNativePort

from litevideo.output.core import VideoOutCore


class DRAMMemory:
    def __init__(self, width, depth, init=[]):
        self.mem = list(init) + [0] * (depth - len(init))
        self.depth = depth

    @passive
    def read_generator(self, port):
        address = 0
        pending = 0
        while True:
            yield port.cmd.ready.eq(0)
            yield port.rdata.valid.eq(0)
            if pending:
                yield port.rdata.valid.eq(1)
                yield port.rdata.data.eq(self.mem[address % self.depth])
                yield
                yield port.rdata.valid.eq(0)
                yield port.rdata.data.eq(0)
                pending = 0
            elif (yield port.cmd.valid):
                pending = not (yield port.cmd.we)
                address = (yield port.cmd.addr)
                yield
                yield port.cmd.ready.eq(1)
            yield


class DUT(Module):
    def __init__(self):
        self.dram_port = LiteDRAMNativePort(mode="read", address_width=32, data_width=32, clock_domain="video")
        self.submodules.core = VideoOutCore(self.dram_port)
        self.sync += self.core.source.ready.eq(~self.core.source.ready)


@passive
def capture(dut, video_data):
    while True:
        if ((yield dut.core.source.valid) and (yield dut.core.source.ready) and (yield dut.core.source.de)):
            video_data.append((yield dut.core.source.data))
        yield


def configure(dut):
    for _ in range(100):
        yield
    ini = dut.core.initiator
    for name, value in (("hres", 16), ("hsync_start", 18), ("hsync_end", 20), ("hscan", 24),
                        ("vres", 16), ("vsync_start", 18), ("vsync_end", 20), ("vscan", 24),
                        ("base", 0), ("length", 16 * 16 * 4)):
        yield getattr(ini, name).storage.eq(value)
    yield
    yield ini.enable.storage.eq(1)
    for _ in range(4096):
        yield


class TestVideoOutCore(unittest.TestCase):
    def test_sequential_frame(self):
        for video_clk_ns in (20, 10, 5):
            with self.subTest(video_clk_ns=video_clk_ns):
                dut = DUT()
                mem = DRAMMemory(32, 1024, list(range(256)))
                video_data = []
                run_simulation(dut,
                    {"sys": [configure(dut)],
                     "video": [capture(dut, video_data), mem.read_generator(dut.dram_port)]},
                    clocks={"sys": 10, "video": video_clk_ns})
                self.assertGreater(len(video_data), 256)
                errors = sum(1 for a, b in zip(video_data, video_data[1:]) if b != (a + 1) % 256)
                self.assertEqual(errors, 0)
```

- [ ] **Step 3: Run**

Run: `git rm -q -r litevideo/output/test && uv run pytest test/test_output_core.py -v 2>&1 | tail -8`
Expected: PASS for the three sub-tests. If `LiteDRAMNativePort` signal names differ (`port.cmd.addr` vs `adr`), check `uv run python -m pydoc litedram.common.LiteDRAMNativePort` and adapt the model, not the core. If the sequence check fails with the original bench's known behaviour (errors at frame boundaries), report the numbers instead of loosening the assert.

- [ ] **Step 4: Commit**

```bash
git add -A litevideo/output litevideo/input test/test_output_core.py
git commit -m "output/input: use LiteDRAM 2026.04 port attribute names; port core bench to pytest"
```

### Task 5: fix the raw PHY layout width

**Files:**
- Modify: `litevideo/output/common.py:43`

- [ ] **Step 1: Change `("c2", 11)` to `("c2", 10)`** with the comment `# three 10-bit TMDS characters, one per channel (was 11: typo, truncated by the PHYs)`.

- [ ] **Step 2: Run the whole suite**: `uv run pytest -q 2>&1 | tail -3` → all pass.

- [ ] **Step 3: Commit**: `git commit -am "output/common: raw phy_layout c2 is 10 bits"`

### Task 6: cgroup-limited command wrapper

**Files:**
- Create: `scripts/limited.py`

- [ ] **Step 1: Write the wrapper**

```python
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
```

- [ ] **Step 2: Verify**

Run: `chmod +x scripts/limited.py && uv run scripts/limited.py --memory-max 200M -- sh -c 'cat /proc/self/cgroup; echo limited-ok'`
Expected: a cgroup path containing `run-` (a transient scope) and `limited-ok`.

- [ ] **Step 3: Commit**: `git add scripts/limited.py && git commit -m "scripts: add cgroup-limited command wrapper for synthesis runs"`

### Task 7: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: ci

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install (locked)
        run: uv sync --extra dev --locked
      - name: Test
        run: uv run pytest -v
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest with uv on push and pull request"
git push -u origin hdmi-support
```

- [ ] **Step 3: Check the run**: `gh run list -R mithro/litevideo -b hdmi-support -L 1` then `gh run watch -R mithro/litevideo <id> --exit-status` → success. If `uv sync --locked` fails in CI because git deps need network, it will still work (public repos); if it fails for another reason, paste the log and fix.

### Task 8: documentation skeleton and README

**Files:**
- Create: `doc/README.md`, `doc/testing.md`, `doc/toolchains.md`, `doc/references.md`
- Modify: `README.md`

- [ ] **Step 1: Write `doc/README.md`**

```markdown
# LiteVideo documentation

| Document | Contents |
|---|---|
| [hdmi-protocol.md](hdmi-protocol.md) | HDMI link layer: periods, TMDS/TERC4 coding, data islands, BCH ECC, packets (phase 1) |
| [testing.md](testing.md) | how to run the simulation tests and the hardware tiers |
| [toolchains.md](toolchains.md) | Vivado, Yosys+Vivado and openXC7 flows, resource limits |
| [references.md](references.md) | specifications and external code this library follows |

Later phases add `audio.md`, `pixel-formats.md`, `transmitter.md`, `receiver.md`
and `reports/`.
```

- [ ] **Step 2: Write `doc/testing.md`**

```markdown
# Testing

## Tier 0: simulation (no hardware)

    uv sync --extra dev
    uv run pytest -v

Every gateware core in `litevideo/hdmi/` is simulated with Migen against the
pure-Python model `litevideo/hdmi/model.py`; the model itself is checked
against vectors derived from the HDMI specification text and an independent
implementation (see `test/test_hdmi_bch.py`). Colour-space cores are checked
against float models on a test image.

Helpers: `test/common.py` (`stream_inserter`, `stream_collector`). The
`test/` package shadows the standard library's `test` package; that is fine
under pytest (default prepend import mode, as LiteEth does it) but
`python -m unittest test.test_x` may pick up the wrong package, so use
`uv run pytest`.

## Hardware tiers

| Tier | Rig | What it proves |
|---|---|---|
| T1 | fabric loopback on a NeTV2 (`rpi5-netv2`) | protocol layer at the pixel rate on silicon, no cables |
| T2 | HDMI cable `hdmi_out` 0 → `hdmi_in` 0 on the same board | SERDES, clock recovery, real TMDS |
| T3 | real HDMI source into `hdmi_in` 0 | ECC and packet conventions against a commercial source |
| T4 | real HDMI sink with audio capture on `hdmi_out` 0 | transmitter accepted by a commercial sink |

Board targets and host scripts live under `bench/` (from phase 2). Every
hardware run writes a dated report under `doc/reports/`.
```

- [ ] **Step 3: Write `doc/toolchains.md`**

```markdown
# Toolchains

All synthesis runs on the shared build machine go through
`scripts/limited.py`, which places the command in a systemd user scope with
memory, swap, CPU and IO limits (`systemd.resource-control(5)`):

    uv run scripts/limited.py -- <command>

Flows, in the order they are brought up:

1. **Vivado** (2025.2): LiteX `--toolchain vivado`.
2. **Yosys synthesis, Vivado place and route**: LiteX Vivado toolchain with
   `synth_mode="yosys"` (`--synth-mode yosys`).
3. **openXC7** (Yosys + nextpnr-xilinx + Project X-Ray): LiteX
   `--toolchain openxc7`; needs `CHIPDB`, `PRJXRAY_DB_DIR` and
   `NEXTPNR_XILINX_PYTHON_DIR` in the environment. Known limits: no
   false-path/multicycle constraints, ISERDESE2 fed from pads and MMCME2_ADV
   issues (nextpnr-xilinx #143, #79).

Convention on the shared machine: one Vivado run at a time.
```

- [ ] **Step 4: Write `doc/references.md`** with the reference list from section 12 of the design spec (HDMI 1.3 public copy, CEA-861-D, DVI 1.0, hdl-util/hdmi, LiteX video cores, XAPP930, AES3), one bullet each with URL and what it is used for.

- [ ] **Step 5: Update `README.md`**: in `[> Features` add `- HDMI data islands, audio and InfoFrames (in progress, see doc/)`; replace the `[> Tests` section with:

```
[> Tests
--------
Unit tests live in ./test/ and run with pytest inside a uv environment
pinned to the LiteX 2026.04 family:

```sh
$ uv sync --extra dev
$ uv run pytest -v
```
```

and add a `[> Documentation` section pointing to `doc/README.md` before `[> License`.

- [ ] **Step 6: Commit**: `git add doc README.md && git commit -m "doc: add documentation skeleton, update README test instructions"`

---

## Phase 1: protocol layer

### Task 9: `litevideo/hdmi/common.py`

**Files:**
- Create: `litevideo/hdmi/__init__.py`, `litevideo/hdmi/common.py`
- Test: `test/test_hdmi_model.py` (part 1, constants)

- [ ] **Step 1: Write the failing test**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from litevideo.hdmi.common import *


def transitions(token):
    return sum(((token >> i) ^ (token >> (i + 1))) & 1 for i in range(9))


class TestTokens(unittest.TestCase):
    def test_control_tokens_have_at_least_seven_transitions(self):
        # HDMI 1.3 §5.2.1.2: control characters have "seven or more
        # transitions" (two of the four have eight).
        for t in control_tokens:
            self.assertGreaterEqual(transitions(t), 7)

    def test_terc4_tokens_unique_and_not_control(self):
        self.assertEqual(len(set(terc4_tokens)), 16)
        self.assertFalse(set(terc4_tokens) & set(control_tokens))

    def test_guard_band_values(self):
        # HDMI 1.3 Table 5-5 / Table 5-6
        self.assertEqual(video_gb_tokens, [0b1011001100, 0b0100110011, 0b1011001100])
        self.assertEqual(data_gb_token, 0b0100110011)
        self.assertEqual(data_gb_ch0_nibble(hsync=0, vsync=0), 0xC)
        self.assertEqual(data_gb_ch0_nibble(hsync=1, vsync=1), 0xF)

    def test_period_constants(self):
        # HDMI 1.3 §5.2.3.2, Table 5-4
        self.assertEqual(PREAMBLE_LENGTH, 8)
        self.assertEqual(GUARD_BAND_LENGTH, 2)
        self.assertEqual(PACKET_LENGTH, 32)
        self.assertEqual(MAX_PACKETS_PER_ISLAND, 18)
        self.assertEqual(MIN_CONTROL_PERIOD, 12)
        self.assertEqual(MIN_EXTENDED_CONTROL_PERIOD, 32)
```

Run: `uv run pytest test/test_hdmi_model.py -v` → fails with `ModuleNotFoundError: litevideo.hdmi`.

- [ ] **Step 2: Write `litevideo/hdmi/__init__.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI link-layer cores, independent of any PHY or clock domain.

Modules here run in the default clock domain; integrators rename it to the
pixel clock with ``ClockDomainsRenamer("pix")``. See doc/hdmi-protocol.md.
"""
```

- [ ] **Step 3: Write `litevideo/hdmi/common.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Constants and stream layouts of the HDMI link layer.

References: HDMI Specification 1.3 (sections quoted per constant), DVI 1.0
§3.2 for the TMDS control characters.
"""

from litex.soc.interconnect import stream

# TMDS characters ------------------------------------------------------------------------------

# Control characters, indexed by {D1, D0}: HDMI 1.3 §5.4.2 Table 5-34 and the
# "case (D1, D0)" table; on channel 0 D0=HSYNC, D1=VSYNC; on channel 1
# D0=CTL0, D1=CTL1; on channel 2 D0=CTL2, D1=CTL3.
control_tokens = [
    0b1101010100,  # D1=0 D0=0
    0b0010101011,  # D1=0 D0=1
    0b0101010100,  # D1=1 D0=0
    0b1010101011,  # D1=1 D0=1
]

# TERC4 characters indexed by the 4-bit data word: HDMI 1.3 §5.4.3.
terc4_tokens = [
    0b1010011100, 0b1001100011, 0b1011100100, 0b1011100010,
    0b0101110001, 0b0100011110, 0b0110001110, 0b0100111100,
    0b1011001100, 0b0100111001, 0b0110011100, 0b1011000110,
    0b1010001110, 0b1001110001, 0b0101100011, 0b1011000011,
]

# Video leading guard band, one value per channel: HDMI 1.3 Table 5-5.
video_gb_tokens = [0b1011001100, 0b0100110011, 0b1011001100]

# Data island guard band on channels 1 and 2: HDMI 1.3 Table 5-6. Channel 0
# carries TERC4(0b11, VSYNC, HSYNC) during both guard bands (§5.2.3.3).
data_gb_token = 0b0100110011


def data_gb_ch0_nibble(hsync, vsync):
    """The 4-bit TERC4 word channel 0 carries during data island guard bands."""
    return 0b1100 | ((vsync & 1) << 1) | (hsync & 1)


# Period structure -----------------------------------------------------------------------------

PREAMBLE_LENGTH              = 8    # HDMI 1.3 §5.2.1.1: 8 characters
GUARD_BAND_LENGTH            = 2    # §5.2.2.1, §5.2.3.3
PACKET_LENGTH                = 32   # §5.2.3.4: 32 characters per packet
MAX_PACKETS_PER_ISLAND       = 18   # §5.2.3.2
MIN_CONTROL_PERIOD           = 12   # §5.2.3.2: tS,min
MIN_EXTENDED_CONTROL_PERIOD  = 32   # Table 5-4: tEXTS,min
EXTENDED_CONTROL_MAX_DELAY_S = 50e-3  # Table 5-4: tEXTS,max_delay
MIN_ISLAND_TO_PREAMBLE       = 4    # tS,min (12) minus the 8-character preamble that ends the
                                    # control period after an island (§5.2.3.2, Figure 5-3)

# Preamble values as (channel 1 {D1,D0}, channel 2 {D1,D0}): Table 5-2,
# CTL0=1 for both, CTL2=1 only for a data island.
PREAMBLE_VIDEO = (0b01, 0b00)
PREAMBLE_DATA  = (0b01, 0b01)


class Period:
    """Link period, as decoded by HDMIPeriodDecoder (HDMI 1.3 §5.2)."""
    CONTROL             = 0
    VIDEO_PREAMBLE      = 1
    VIDEO_GUARD         = 2
    VIDEO               = 3
    DATA_PREAMBLE       = 4
    DATA_LEADING_GUARD  = 5
    DATA_ISLAND         = 6
    DATA_TRAILING_GUARD = 7


# Packets --------------------------------------------------------------------------------------

class PacketType:
    """Packet type codes: HDMI 1.3 Table 5-8 and CEA-861-D Table 4."""
    NULL            = 0x00
    ACR             = 0x01  # Audio Clock Regeneration
    ASP             = 0x02  # Audio Sample Packet
    GCP             = 0x03  # General Control Packet
    ACP             = 0x04  # Audio Content Protection
    ISRC1           = 0x05
    ISRC2           = 0x06
    ONE_BIT_AUDIO   = 0x07
    DST_AUDIO       = 0x08
    HBR_AUDIO       = 0x09
    GAMUT_METADATA  = 0x0A
    VENDOR_INFOFRAME = 0x81
    AVI_INFOFRAME   = 0x82
    SPD_INFOFRAME   = 0x83
    AUDIO_INFOFRAME = 0x84
    MPEG_INFOFRAME  = 0x85


# Stream layouts -------------------------------------------------------------------------------

# Three 10-bit TMDS characters, one per channel, one beat per pixel clock.
raw_layout = [("c0", 10), ("c1", 10), ("c2", 10)]

# One data island packet: 24 header bits (HB0 | HB1 << 8 | HB2 << 16) and four
# 56-bit subpackets (SB0 in bits 0..7 ... SB6 in bits 48..55). ECC is not part
# of the layout: the encoder computes it, the decoder checks it.
packet_layout = [
    ("header", 24),
    ("sub0",   56),
    ("sub1",   56),
    ("sub2",   56),
    ("sub3",   56),
]

# Received packet: adds the ECC verdict (1 = header and all subpackets valid).
packet_rx_layout = packet_layout + [("ecc_ok", 1)]


def packet_endpoint():
    return stream.Endpoint(packet_layout)


def packet_rx_endpoint():
    return stream.Endpoint(packet_rx_layout)
```

- [ ] **Step 4: Run**: `uv run pytest test/test_hdmi_model.py -v` → 4 passed.

- [ ] **Step 5: Commit**: `git add litevideo/hdmi test/test_hdmi_model.py && git commit -m "hdmi: add link-layer constants and stream layouts"`

### Task 10: BCH ECC (`litevideo/hdmi/bch.py`)

**Files:**
- Create: `litevideo/hdmi/bch.py`, `test/test_hdmi_bch.py`

- [ ] **Step 1: Write the failing test**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI data island BCH ECC.

Vectors were produced by two independent implementations that agree: the
reflected LFSR of hdl-util/hdmi (src/packet_assembler.sv, mask 8'b10000011)
and polynomial long division by G(x) = x^8 + x^7 + x^6 + 1 (HDMI 1.3
§5.2.3.5: "G(x)=1+x6+x7+x8").
"""

import random
import unittest

from migen import *

from litevideo.hdmi.bch import bch_ecc, bch_step, BCH_LFSR_MASK

VECTORS = [
    ([0x00, 0x00, 0x00], 0x00),
    ([0x01, 0x00, 0x00], 0x4A),   # ACR header
    ([0x02, 0x01, 0x00], 0x65),   # ASP header, subpacket 0 present
    ([0x82, 0x02, 0x0D], 0xE4),   # AVI InfoFrame header
    ([0x84, 0x01, 0x0A], 0x4A),   # Audio InfoFrame header
    ([0xFF, 0xFF, 0xFF], 0x39),
    ([0x00] * 7, 0x00),
    ([0x00, 0x00, 0x01, 0x22, 0x0A, 0x00, 0x18], 0xB9),
    ([1, 2, 3, 4, 5, 6, 7], 0xB2),
    ([0xA5, 0x5A, 0xC3, 0x3C, 0xF0, 0x0F, 0x81], 0xE4),
]


class TestBCHModel(unittest.TestCase):
    def test_mask_is_reflected_polynomial(self):
        self.assertEqual(BCH_LFSR_MASK, 0x83)

    def test_vectors(self):
        for data, ecc in VECTORS:
            self.assertEqual(bch_ecc(data), ecc, data)

    def test_polynomial_division_agrees(self):
        # Independent check: remainder of M(x)*x^8 mod G(x), bits LSB-first.
        G = 0x1C1
        prng = random.Random(1)
        for _ in range(200):
            data = [prng.randrange(256) for _ in range(prng.choice((3, 7)))]
            reg = 0
            for b in data:
                for i in range(8):
                    reg = (reg << 1) | ((b >> i) & 1)
                    if reg & 0x100:
                        reg ^= G
            for _ in range(8):
                reg <<= 1
                if reg & 0x100:
                    reg ^= G
            rem = reg & 0xFF
            reflected = int(f"{rem:08b}"[::-1], 2)
            self.assertEqual(bch_ecc(data), reflected)


class TestBCHGateware(unittest.TestCase):
    def test_serial_step_matches_model(self):
        class DUT(Module):
            def __init__(self):
                self.bit = Signal()
                self.clear = Signal()
                self.state = Signal(8)
                self.sync += If(self.clear, self.state.eq(0)).Else(self.state.eq(bch_step(self.state, self.bit)))

        prng = random.Random(2)
        cases = [[prng.randrange(256) for _ in range(prng.choice((3, 7)))] for _ in range(20)]
        results = []

        def gen(dut):
            for data in cases:
                yield dut.clear.eq(1)
                yield
                yield dut.clear.eq(0)
                for b in data:
                    for i in range(8):
                        yield dut.bit.eq((b >> i) & 1)
                        yield
                yield   # the last bit is registered on this edge
                results.append((yield dut.state))

        dut = DUT()
        run_simulation(dut, gen(dut))
        self.assertEqual(results, [bch_ecc(d) for d in cases])
```

Run: `uv run pytest test/test_hdmi_bch.py -v` → ImportError.

- [ ] **Step 2: Write `litevideo/hdmi/bch.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""BCH ECC of HDMI data island packets.

HDMI 1.3 §5.2.3.5: "BCH(64,56) and BCH(32,24) are generated by the polynomial
G(x) shown in Figure 5-5. G(x)=1+x6+x7+x8". Bits enter LSB first (bit 0 of
HB0/SB0 first, §5.2.3.4 Figure 5-4). The generator is implemented as a
reflected right-shifting LFSR: each data bit is XORed with the register LSB,
the register shifts right, and the feedback XORs in the reflected polynomial
mask 0x83 (= 0xC1 bit-reversed). This is exactly the ``next_ecc`` function of
hdl-util/hdmi ``src/packet_assembler.sv``.

The header ECC covers 24 bits; each subpacket ECC covers 56 bits. Both are
transmitted after their data, LSB first, as the last 8 characters of the
packet (header: 1 bit per character on channel 0 bit 2; subpackets: 2 bits
per character on channels 1 and 2).
"""

from migen import *

BCH_POLYNOMIAL = 0x1C1   # x^8 + x^7 + x^6 + 1
BCH_LFSR_MASK  = 0x83    # low byte of the polynomial, bit-reversed


def bch_ecc(data_bytes):
    """Python reference: ECC over ``data_bytes`` (list of ints), LSB first."""
    ecc = 0
    for byte in data_bytes:
        for i in range(8):
            feedback = (ecc ^ (byte >> i)) & 1
            ecc >>= 1
            if feedback:
                ecc ^= BCH_LFSR_MASK
    return ecc


def bch_step(state, bit):
    """Migen expression: next 8-bit LFSR state after feeding one data bit."""
    feedback = state[0] ^ bit
    return Cat(state[1:], 0) ^ (Replicate(feedback, 8) & C(BCH_LFSR_MASK, 8))
```

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_bch.py -v` → 4 passed.

- [ ] **Step 4: Commit**: `git add litevideo/hdmi/bch.py test/test_hdmi_bch.py && git commit -m "hdmi: add BCH ECC reference and serial LFSR step with cross-checked vectors"`

### Task 11: Python golden model (`litevideo/hdmi/model.py`)

**Files:**
- Create: `litevideo/hdmi/model.py`
- Modify: `test/test_hdmi_model.py` (append)

- [ ] **Step 1: Append failing tests to `test/test_hdmi_model.py`**

```python
import random

from litevideo.hdmi import model
from litevideo.hdmi.bch import bch_ecc


class TestTMDSModel(unittest.TestCase):
    def test_control_and_data_roundtrip(self):
        prng = random.Random(3)
        cnt = 0
        for _ in range(2000):
            de = prng.randrange(2)
            d = prng.randrange(256)
            c = prng.randrange(4)
            token, cnt = model.tmds_encode(d, c, de, cnt)
            dd, cc, dde = model.tmds_decode(token)
            self.assertEqual(dde, de)
            if de:
                self.assertEqual(dd, d)
            else:
                self.assertEqual(cc, c)
                self.assertEqual(cnt, 0)

    def test_dc_balance_bounded(self):
        # DVI 1.0 §3.2.2: the running disparity stays within +/-10 bits.
        prng = random.Random(4)
        cnt = 0
        for _ in range(5000):
            _, cnt = model.tmds_encode(prng.randrange(256), 0, 1, cnt)
            self.assertLessEqual(abs(cnt), 10)

    def test_terc4_roundtrip(self):
        for n in range(16):
            self.assertEqual(model.terc4_decode(model.terc4_encode(n)), n)
        self.assertIsNone(model.terc4_decode(control_tokens[0]))


class TestPacketModel(unittest.TestCase):
    def test_header_and_subpacket_words(self):
        p = model.Packet([0x01, 0x00, 0x00], [[0, 0, 1, 0x22, 0x0A, 0, 0x18]] * 4)
        self.assertEqual(p.header, 0x000001)
        self.assertEqual(p.header_ecc, bch_ecc([1, 0, 0]))
        # bytes [0x00,0x00,0x01,0x22,0x0A,0x00,0x18] little-endian
        self.assertEqual(p.subpackets[0], 0x18000A22010000)
        self.assertEqual(p.subpacket_ecc[0], bch_ecc([0, 0, 1, 0x22, 0x0A, 0, 0x18]))

    def test_null_packet(self):
        p = model.Packet.null()
        self.assertEqual(p.header, 0)
        self.assertEqual(p.subpackets, [0, 0, 0, 0])

    def test_packet_chars_bit_mapping(self):
        # §5.2.3.4: header bit c on ch0 bit 2; subpacket k bit 2c on ch1 bit k,
        # bit 2c+1 on ch2 bit k; ECC bits follow the data bits.
        p = model.Packet([0xA5, 0x3C, 0x0F], [[i * 7 + k for i in range(7)] for k in range(4)])
        chars = model.packet_chars(p)
        self.assertEqual(len(chars), 32)
        full_header = p.header | (p.header_ecc << 24)
        full_subs = [p.subpackets[k] | (p.subpacket_ecc[k] << 56) for k in range(4)]
        for c, (hbit, n1, n2) in enumerate(chars):
            self.assertEqual(hbit, (full_header >> c) & 1)
            for k in range(4):
                self.assertEqual((n1 >> k) & 1, (full_subs[k] >> (2 * c)) & 1)
                self.assertEqual((n2 >> k) & 1, (full_subs[k] >> (2 * c + 1)) & 1)


class TestIslandModel(unittest.TestCase):
    def test_island_framing(self):
        p = model.Packet.null()
        toks = model.island_tokens([p, p], hsync=1, vsync=0)
        self.assertEqual(len(toks), 8 + 2 + 64 + 2)
        # preamble: ch0 control(hsync,vsync), ch1/ch2 CTL0=1/CTL2=1
        self.assertEqual(toks[0], (control_tokens[0b01], control_tokens[0b01], control_tokens[0b01]))
        # leading guard band: ch0 TERC4(0b11,vsync,hsync), ch1/2 data GB
        self.assertEqual(toks[8], (terc4_tokens[0b1101], data_gb_token, data_gb_token))
        # first packet character: ch0 bit3 = 0, others bit3 = 1 (HDMI 1.4b CTS)
        self.assertEqual(model.terc4_decode(toks[10][0]) >> 3, 0)
        for t in toks[11:74]:
            self.assertEqual(model.terc4_decode(t[0]) >> 3, 1)
        self.assertEqual(toks[-1], (terc4_tokens[0b1101], data_gb_token, data_gb_token))

    def test_line_tokens_periods(self):
        # blanking needs 12 control + (8+2+32+2) island + 4 control + 8 preamble + 2 guard = 70
        line, periods = model.line_tokens(hactive=16, hblank=80, packets=[model.Packet.null()], hsync_start=4, hsync_len=8)
        self.assertEqual(len(line), 96)
        self.assertEqual(len(periods), 96)
        self.assertEqual(periods[:16], [Period.VIDEO] * 16)
        self.assertIn(Period.DATA_ISLAND, periods)
        self.assertEqual(periods[-10:-2], [Period.VIDEO_PREAMBLE] * 8)
        self.assertEqual(periods[-2:], [Period.VIDEO_GUARD] * 2)
```

Run: `uv run pytest test/test_hdmi_model.py -v` → fail on `model` import.

- [ ] **Step 2: Write `litevideo/hdmi/model.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure-Python golden model of the HDMI link layer.

Everything the gateware does is modelled here first, at the level of 10-bit
TMDS characters, so simulations can compare bit for bit:

* ``tmds_encode`` / ``tmds_decode``: DVI 1.0 §3.2.2 / §3.3 (8b/10b with
  running disparity ``cnt``).
* ``terc4_encode`` / ``terc4_decode``: HDMI 1.3 §5.4.3.
* ``Packet``: header + four subpackets with their BCH ECC (§5.2.3.4, §5.2.3.5).
* ``packet_chars``: the 32 per-character (header bit, ch1 nibble, ch2 nibble)
  triples of one packet (§5.2.3.4 Figure 5-4).
* ``island_tokens``: preamble, guard bands and packets of one data island as
  ``(c0, c1, c2)`` tuples (§5.2.3, Tables 5-2 and 5-6, channel 0 bit 3 per
  the HDMI 1.4b CTS: 0 on the first island character, 1 elsewhere).
* ``line_tokens``: a whole video line with control periods, an optional
  island, the video preamble and guard band, and TMDS-encoded pixels,
  together with the expected ``Period`` per character.
"""

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_ecc

# TMDS 8b/10b ------------------------------------------------------------------------------------

def _ones(v, n=8):
    return bin(v & ((1 << n) - 1)).count("1")


def tmds_encode(d, c, de, cnt):
    """DVI 1.0 §3.2.2 Figure 3-5. Returns (10-bit token, new running disparity)."""
    if not de:
        return control_tokens[c & 3], 0
    n1 = _ones(d)
    q_m = [d & 1]
    if n1 > 4 or (n1 == 4 and (d & 1) == 0):
        for i in range(1, 8):
            q_m.append(q_m[i - 1] ^ ((d >> i) & 1) ^ 1)
        q_m.append(0)
    else:
        for i in range(1, 8):
            q_m.append(q_m[i - 1] ^ ((d >> i) & 1))
        q_m.append(1)
    qm = sum(b << i for i, b in enumerate(q_m))
    n1q = _ones(qm)
    n0q = 8 - n1q
    if cnt == 0 or n1q == n0q:
        q9 = 1 - q_m[8]
        q8 = q_m[8]
        low = qm & 0xFF if q_m[8] else (~qm) & 0xFF
        cnt = cnt + (n1q - n0q) if q_m[8] else cnt + (n0q - n1q)
    elif (cnt > 0 and n1q > n0q) or (cnt < 0 and n0q > n1q):
        q9 = 1
        q8 = q_m[8]
        low = (~qm) & 0xFF
        cnt = cnt + 2 * q_m[8] + (n0q - n1q)
    else:
        q9 = 0
        q8 = q_m[8]
        low = qm & 0xFF
        cnt = cnt - 2 * (1 - q_m[8]) + (n1q - n0q)
    return low | (q8 << 8) | (q9 << 9), cnt


def tmds_decode(token):
    """DVI 1.0 §3.3 Figure 3-6. Returns (d, c, de)."""
    if token in control_tokens:
        return 0, control_tokens.index(token), 0
    low = token & 0xFF
    if token & (1 << 9):
        low = (~low) & 0xFF
    d = low & 1
    for i in range(1, 8):
        bit = (low >> i) & 1
        prev = (low >> (i - 1)) & 1
        if token & (1 << 8):
            d |= (bit ^ prev) << i
        else:
            d |= (bit ^ prev ^ 1) << i
    return d, 0, 1


# TERC4 ------------------------------------------------------------------------------------------

def terc4_encode(nibble):
    return terc4_tokens[nibble & 0xF]


def terc4_decode(token):
    """4-bit word, or None if ``token`` is not a TERC4 character."""
    try:
        return terc4_tokens.index(token)
    except ValueError:
        return None


# Packets ----------------------------------------------------------------------------------------

class Packet:
    """One data island packet: 3 header bytes and 4 subpackets of 7 bytes."""

    def __init__(self, header_bytes, subpacket_bytes):
        assert len(header_bytes) == 3
        assert len(subpacket_bytes) == 4 and all(len(s) == 7 for s in subpacket_bytes)
        self.header_bytes = list(header_bytes)
        self.subpacket_bytes = [list(s) for s in subpacket_bytes]

    @classmethod
    def null(cls):
        return cls([0, 0, 0], [[0] * 7 for _ in range(4)])

    @classmethod
    def from_words(cls, header, subpackets):
        hb = [(header >> (8 * i)) & 0xFF for i in range(3)]
        sb = [[(s >> (8 * i)) & 0xFF for i in range(7)] for s in subpackets]
        return cls(hb, sb)

    @property
    def type(self):
        return self.header_bytes[0]

    @property
    def header(self):
        return sum(b << (8 * i) for i, b in enumerate(self.header_bytes))

    @property
    def header_ecc(self):
        return bch_ecc(self.header_bytes)

    @property
    def subpackets(self):
        return [sum(b << (8 * i) for i, b in enumerate(s)) for s in self.subpacket_bytes]

    @property
    def subpacket_ecc(self):
        return [bch_ecc(s) for s in self.subpacket_bytes]

    def __eq__(self, other):
        return isinstance(other, Packet) and self.header_bytes == other.header_bytes and self.subpacket_bytes == other.subpacket_bytes

    def __repr__(self):
        return f"Packet({[hex(b) for b in self.header_bytes]}, {self.subpacket_bytes})"


def packet_chars(packet, corrupt_header_ecc=False, corrupt_subpacket_ecc=None):
    """32 (header_bit, ch1 nibble, ch2 nibble) triples of one packet."""
    hecc = packet.header_ecc ^ (0x01 if corrupt_header_ecc else 0)
    header = packet.header | (hecc << 24)
    subs = []
    for k, (data, ecc) in enumerate(zip(packet.subpackets, packet.subpacket_ecc)):
        if corrupt_subpacket_ecc == k:
            ecc ^= 0x01
        subs.append(data | (ecc << 56))
    chars = []
    for c in range(PACKET_LENGTH):
        hbit = (header >> c) & 1
        n1 = 0
        n2 = 0
        for k in range(4):
            n1 |= ((subs[k] >> (2 * c)) & 1) << k
            n2 |= ((subs[k] >> (2 * c + 1)) & 1) << k
        chars.append((hbit, n1, n2))
    return chars


# Islands and lines ------------------------------------------------------------------------------

def control_chars(hsync, vsync, ctl=(0, 0)):
    """(c0, c1, c2) of one control character; ``ctl`` = (ch1 {D1,D0}, ch2 {D1,D0})."""
    return (control_tokens[(vsync << 1) | hsync], control_tokens[ctl[0]], control_tokens[ctl[1]])


def island_tokens(packets, hsync=0, vsync=0, **corrupt):
    """Preamble + leading guard band + packets + trailing guard band."""
    assert 1 <= len(packets) <= MAX_PACKETS_PER_ISLAND
    gb0 = terc4_encode(data_gb_ch0_nibble(hsync, vsync))
    toks = [control_chars(hsync, vsync, PREAMBLE_DATA)] * PREAMBLE_LENGTH
    toks += [(gb0, data_gb_token, data_gb_token)] * GUARD_BAND_LENGTH
    first = True
    for p in packets:
        for hbit, n1, n2 in packet_chars(p, **corrupt):
            n0 = ((0 if first else 1) << 3) | (hbit << 2) | (vsync << 1) | hsync
            first = False
            toks.append((terc4_encode(n0), terc4_encode(n1), terc4_encode(n2)))
    toks += [(gb0, data_gb_token, data_gb_token)] * GUARD_BAND_LENGTH
    return toks


def video_tokens(pixels, disparity=None):
    """TMDS-encode ``pixels`` (list of (r, g, b)); channel 0 = b, 1 = g, 2 = r."""
    cnt = disparity or [0, 0, 0]
    toks = []
    for r, g, b in pixels:
        c0, cnt[0] = tmds_encode(b, 0, 1, cnt[0])
        c1, cnt[1] = tmds_encode(g, 0, 1, cnt[1])
        c2, cnt[2] = tmds_encode(r, 0, 1, cnt[2])
        toks.append((c0, c1, c2))
    return toks


def line_tokens(hactive, hblank, packets=(), hsync_start=None, hsync_len=None, vsync=0, pixels=None):
    """One line: active video, then blanking with an optional island, then the
    video preamble and guard band. Returns (tokens, expected periods)."""
    hsync_start = hactive + 4 if hsync_start is None else hactive + hsync_start
    hsync_len = 8 if hsync_len is None else hsync_len
    if pixels is None:
        pixels = [((i * 7) & 0xFF, (i * 13) & 0xFF, (i * 29) & 0xFF) for i in range(hactive)]
    toks = video_tokens(pixels)
    periods = [Period.VIDEO] * hactive

    def hs(x):
        return 1 if hsync_start <= x < hsync_start + hsync_len else 0

    x = hactive
    tail = PREAMBLE_LENGTH + GUARD_BAND_LENGTH
    island = island_tokens(list(packets), hsync=hs(x + MIN_CONTROL_PERIOD), vsync=vsync) if packets else []
    # control, island, control (>= 4), video preamble, video guard band
    n_ctrl_before = MIN_CONTROL_PERIOD
    n_ctrl_after = hblank - n_ctrl_before - len(island) - tail
    assert n_ctrl_after >= MIN_ISLAND_TO_PREAMBLE, "blanking too short for this island"
    for _ in range(n_ctrl_before):
        toks.append(control_chars(hs(x), vsync)); periods.append(Period.CONTROL); x += 1
    for i, t in enumerate(island):
        toks.append(t)
        if i < PREAMBLE_LENGTH:
            periods.append(Period.DATA_PREAMBLE)
        elif i < PREAMBLE_LENGTH + GUARD_BAND_LENGTH:
            periods.append(Period.DATA_LEADING_GUARD)
        elif i >= len(island) - GUARD_BAND_LENGTH:
            periods.append(Period.DATA_TRAILING_GUARD)
        else:
            periods.append(Period.DATA_ISLAND)
        x += 1
    for _ in range(n_ctrl_after):
        toks.append(control_chars(hs(x), vsync)); periods.append(Period.CONTROL); x += 1
    for _ in range(PREAMBLE_LENGTH):
        toks.append(control_chars(hs(x), vsync, PREAMBLE_VIDEO)); periods.append(Period.VIDEO_PREAMBLE); x += 1
    for _ in range(GUARD_BAND_LENGTH):
        toks.append(tuple(video_gb_tokens)); periods.append(Period.VIDEO_GUARD); x += 1
    return toks, periods
```

Note: `line_tokens` keeps HSYNC constant across the island (the island's syncs are sampled at its first character); `hs()` is evaluated per control character. Tests use `hsync_start=4, hsync_len=8` so the sync pulse ends before the island starts.

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_model.py -v`. Expected: all pass (verified while reviewing this plan). If `tmds_encode` ever disagrees with `tmds_decode`, compare against the DVI 1.0 Figure 3-5 flowchart step by step (the `cnt` update uses `2*q_m[8]` and `2*(1-q_m[8])` in the two unbalanced branches).

- [ ] **Step 4: Commit**: `git add litevideo/hdmi/model.py test/test_hdmi_model.py && git commit -m "hdmi: add Python golden model (TMDS, TERC4, packets, islands, lines)"`

### Task 12: TMDS character decoder (`litevideo/hdmi/tmds.py`)

**Files:**
- Create: `litevideo/hdmi/tmds.py`, `test/test_hdmi_tmds.py`

- [ ] **Step 1: Write the failing test**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.tmds import TMDSCharacterDecoder


class TestTMDSCharacterDecoder(unittest.TestCase):
    def run_tokens(self, channel, tokens):
        dut = TMDSCharacterDecoder(channel)
        out = []

        def gen():
            for t in tokens + [0]:
                yield dut.raw.eq(t)
                yield
                out.append({
                    "d": (yield dut.d), "c": (yield dut.c), "control": (yield dut.control),
                    "video_gb": (yield dut.video_gb), "data_gb": (yield dut.data_gb),
                    "terc4": (yield dut.terc4), "terc4_valid": (yield dut.terc4_valid),
                })

        run_simulation(dut, gen())
        return out[1:]   # one cycle of latency

    def test_video_data(self):
        prng = random.Random(5)
        pixels = [prng.randrange(256) for _ in range(300)]
        cnt = 0
        tokens = []
        for p in pixels:
            t, cnt = model.tmds_encode(p, 0, 1, cnt)
            tokens.append(t)
        out = self.run_tokens(0, tokens)
        self.assertEqual([o["d"] for o in out], pixels)
        self.assertTrue(all(o["control"] == 0 for o in out))

    def test_control_guard_terc4(self):
        for channel in range(3):
            tokens = control_tokens + [video_gb_tokens[channel], data_gb_token] + terc4_tokens
            out = self.run_tokens(channel, tokens)
            for i in range(4):
                self.assertEqual((out[i]["control"], out[i]["c"]), (1, i))
            self.assertEqual(out[4]["video_gb"], 1)
            self.assertEqual(out[5]["data_gb"], 1 if channel else 0)
            for n in range(16):
                self.assertEqual((out[6 + n]["terc4_valid"], out[6 + n]["terc4"]), (1, n))
```

- [ ] **Step 2: Write `litevideo/hdmi/tmds.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-channel TMDS character classification and decoding.

One 10-bit character per cycle in, one cycle later out: the 8-bit video data
(DVI 1.0 §3.3), the 2-bit control value and ``control`` flag (HDMI 1.3
§5.4.2), the guard band flags (Tables 5-5 and 5-6) and the TERC4 word with its
validity (§5.4.3). Which flag matters is decided by ``HDMIPeriodDecoder``.
"""

from migen import *

from litex.gen import *

from litevideo.hdmi.common import *


class TMDSCharacterDecoder(LiteXModule):
    def __init__(self, channel):
        assert channel in (0, 1, 2)
        self.raw = Signal(10)

        self.d           = Signal(8)
        self.c           = Signal(2)
        self.control     = Signal()
        self.video_gb    = Signal()
        self.data_gb     = Signal()
        self.terc4       = Signal(4)
        self.terc4_valid = Signal()

        # # #

        raw = self.raw

        # Video data: undo the optional inversion (bit 9) then the XOR/XNOR chain (bit 8).
        data = Signal(8)
        self.comb += data.eq(Mux(raw[9], ~raw[:8], raw[:8]))
        self.sync += self.d[0].eq(data[0])
        for i in range(1, 8):
            self.sync += self.d[i].eq(data[i] ^ data[i - 1] ^ ~raw[8])

        # Control characters.
        self.sync += self.control.eq(0)
        for i, token in enumerate(control_tokens):
            self.sync += If(raw == token, self.control.eq(1), self.c.eq(i))

        # Guard bands.
        self.sync += self.video_gb.eq(raw == video_gb_tokens[channel])
        self.sync += self.data_gb.eq(0 if channel == 0 else (raw == data_gb_token))

        # TERC4.
        self.sync += self.terc4_valid.eq(0)
        for n, token in enumerate(terc4_tokens):
            self.sync += If(raw == token, self.terc4_valid.eq(1), self.terc4.eq(n))
```

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_tmds.py -v` → 2 passed.
- [ ] **Step 4: Commit**: `git add litevideo/hdmi/tmds.py test/test_hdmi_tmds.py && git commit -m "hdmi: add TMDS character decoder"`

### Task 13: period decoder (`litevideo/hdmi/period.py`)

**Files:**
- Create: `litevideo/hdmi/period.py`, `test/test_hdmi_period.py`

Behaviour (HDMI 1.3 §5.2, Figure 5-3): a state machine over the three
classified characters. Outputs are registered, total latency 2 cycles from
`sink` to `source`/`period`.

| State | Leave when | To |
|---|---|---|
| CONTROL | all three `control` and (c1, c2) == PREAMBLE_VIDEO | VIDEO_PREAMBLE |
| CONTROL | all three `control` and (c1, c2) == PREAMBLE_DATA | DATA_PREAMBLE |
| VIDEO_PREAMBLE | all three `video_gb` | VIDEO_GUARD |
| VIDEO_PREAMBLE | any `control` with a different (c1, c2) | CONTROL |
| VIDEO_GUARD | not all `video_gb` | VIDEO (this character is the first pixel) |
| VIDEO | any `control` | CONTROL |
| DATA_PREAMBLE | ch1 and ch2 `data_gb` | DATA_LEADING_GUARD |
| DATA_PREAMBLE | any `control` with a different (c1, c2) | CONTROL |
| DATA_LEADING_GUARD | not (ch1 and ch2 `data_gb`) | DATA_ISLAND (this character is island char 0) |
| DATA_ISLAND | ch1 and ch2 `data_gb` | DATA_TRAILING_GUARD |
| DATA_ISLAND | any `control` | CONTROL (`error` pulse) |
| DATA_TRAILING_GUARD | not (ch1 and ch2 `data_gb`) | CONTROL |

Convention: the FSM reports the *new* period on the character that causes
the transition (the first preamble character is already VIDEO_PREAMBLE /
DATA_PREAMBLE, the first non-guard character after a guard band is already
VIDEO / DATA_ISLAND). The model's `line_tokens` `periods` list uses the same
convention, so the tests compare the two directly. The decoder resets in
CONTROL and only enters VIDEO after seeing a preamble and guard band, so the
tests feed one warm-up line and compare from the second line on.

- [ ] **Step 1: Write the failing test**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.period import HDMIPeriodDecoder


def run_lines(lines, dvi_mode=0):
    """Feed concatenated line token lists; return per-character output dicts."""
    dut = HDMIPeriodDecoder()
    tokens = [t for line in lines for t in line]
    out = []

    def gen():
        yield dut.dvi_mode.eq(dvi_mode)
        for t in tokens + [model.control_chars(0, 0)] * 3:
            yield dut.sink.c0.eq(t[0]); yield dut.sink.c1.eq(t[1]); yield dut.sink.c2.eq(t[2])
            yield dut.sink.valid.eq(1)
            yield
            out.append({
                "period": (yield dut.period), "de": (yield dut.source.de),
                "hsync": (yield dut.source.hsync), "vsync": (yield dut.source.vsync),
                "r": (yield dut.source.r), "g": (yield dut.source.g), "b": (yield dut.source.b),
                "island": (yield dut.island_active), "first": (yield dut.island_first),
                "n0": (yield dut.nibble0), "n1": (yield dut.nibble1), "n2": (yield dut.nibble2),
                "error": (yield dut.error),
            })

    run_simulation(dut, gen())
    # Drop the warm-up line (the first ``len(lines[0])`` characters) and the latency.
    start = dut.latency + len(lines[0])
    return out[start:start + len(tokens) - len(lines[0])]


class TestHDMIPeriodDecoder(unittest.TestCase):
    def test_periods_video_only(self):
        toks, periods = model.line_tokens(hactive=24, hblank=40)
        out = run_lines([toks] * 4)          # 1 warm-up + 3 compared
        self.assertEqual([o["period"] for o in out], periods * 3)
        self.assertEqual([o["de"] for o in out], [1 if p == Period.VIDEO else 0 for p in periods] * 3)

    def test_pixels_and_syncs(self):
        pixels = [(i, 255 - i, (i * 3) & 0xFF) for i in range(24)]
        toks, periods = model.line_tokens(hactive=24, hblank=40, pixels=pixels, hsync_start=4, hsync_len=8)
        out = run_lines([toks, toks])
        got = [(o["r"], o["g"], o["b"]) for o in out if o["de"]]
        self.assertEqual(got, pixels)
        hs = [o["hsync"] for o in out[24:64]]
        self.assertEqual(hs, [1 if 4 <= i < 12 else 0 for i in range(40)])

    def test_island_nibbles(self):
        p = model.Packet([0x82, 0x02, 0x0D], [[0x11 * k + i for i in range(7)] for k in range(4)])
        # blanking: 12 + (8+2+64+2) + 4 + 8 + 2 = 102 minimum
        toks, periods = model.line_tokens(hactive=16, hblank=112, packets=[p, p], hsync_start=4, hsync_len=4)
        out = run_lines([toks] * 3)          # 1 warm-up + 2 compared
        self.assertEqual([o["period"] for o in out], periods * 2)
        chars = model.packet_chars(p) * 2
        island = [o for o in out if o["island"]]
        self.assertEqual(len(island), 128)
        self.assertEqual([o["first"] for o in island[:64]], [1] + [0] * 63)
        for o, (hbit, n1, n2) in zip(island[:64], chars):
            self.assertEqual((o["n0"] >> 2) & 1, hbit)
            self.assertEqual(o["n1"], n1)
            self.assertEqual(o["n2"], n2)
        self.assertFalse(any(o["error"] for o in out))

    def test_dvi_mode(self):
        # DVI mode: DE is "channel 0 is not a control character", so the two
        # video guard band characters (not control tokens) also count as DE.
        toks, periods = model.line_tokens(hactive=24, hblank=40)
        out = run_lines([toks, toks], dvi_mode=1)
        expected = [1 if p in (Period.VIDEO, Period.VIDEO_GUARD) else 0 for p in periods]
        self.assertEqual([o["de"] for o in out], expected)

    def test_island_aborted_by_control(self):
        p = model.Packet.null()
        island = model.island_tokens([p])
        toks = [model.control_chars(0, 0)] * 12 + island[:20] + [model.control_chars(0, 0)] * 12
        out = run_lines([toks])
        self.assertTrue(any(o["error"] for o in out))
        self.assertEqual(out[-1]["period"], Period.CONTROL)
```

- [ ] **Step 2: Write `litevideo/hdmi/period.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI period decoder: three TMDS characters per cycle in, the link period,
syncs, DE, pixel data and data island nibbles out.

The state machine follows HDMI 1.3 §5.2 (Figure 5-3): a Control Period ends
with an 8-character Preamble (Table 5-2) that says whether a Video Data
Period (2-character Video Guard Band, Table 5-5) or a Data Island (Leading
Guard Band, packets, Trailing Guard Band, Table 5-6) follows. HSYNC/VSYNC are
taken from channel 0's control value during Control Periods (§5.4.2 Table
5-34) and from channel 0 TERC4 bits 0 and 1 during islands and their guard
bands (§5.2.3.1); they hold during video. DE is 1 during Video Data Periods.

``dvi_mode`` bypasses the preamble tracking for DVI sources (which never send
preambles or guard bands): DE is then simply "channel 0 is not a control
character".

Latency: 2 cycles (character decode + registered outputs).
"""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.cores.video import video_data_layout

from litevideo.hdmi.common import *
from litevideo.hdmi.tmds import TMDSCharacterDecoder


class HDMIPeriodDecoder(LiteXModule):
    latency = 2

    def __init__(self):
        self.sink   = stream.Endpoint(raw_layout)
        self.source = stream.Endpoint(video_data_layout)
        self.dvi_mode = Signal()

        self.period        = Signal(3)
        self.island_active = Signal()   # a packet character (not a guard band) is on ``nibble*``
        self.island_first  = Signal()   # ... and it is the first character of the island
        self.nibble0       = Signal(4)
        self.nibble1       = Signal(4)
        self.nibble2       = Signal(4)
        self.error         = Signal()   # island ended by a control character instead of a guard band

        # # #

        self.comb += self.sink.ready.eq(1)

        self.dec0 = dec0 = TMDSCharacterDecoder(0)
        self.dec1 = dec1 = TMDSCharacterDecoder(1)
        self.dec2 = dec2 = TMDSCharacterDecoder(2)
        self.comb += [dec0.raw.eq(self.sink.c0), dec1.raw.eq(self.sink.c1), dec2.raw.eq(self.sink.c2)]

        all_control = dec0.control & dec1.control & dec2.control
        any_control = dec0.control | dec1.control | dec2.control
        preamble    = Cat(dec1.c, dec2.c)   # {ch2 D1, ch2 D0, ch1 D1, ch1 D0}
        video_pre   = all_control & (preamble == ((PREAMBLE_VIDEO[1] << 2) | PREAMBLE_VIDEO[0]))
        data_pre    = all_control & (preamble == ((PREAMBLE_DATA[1] << 2) | PREAMBLE_DATA[0]))
        all_video_gb = dec0.video_gb & dec1.video_gb & dec2.video_gb
        data_gb      = dec1.data_gb & dec2.data_gb

        period = Signal(3)
        in_island = Signal()
        first = Signal()
        error = Signal()

        self.fsm = fsm = FSM(reset_state="CONTROL")
        fsm.act("CONTROL",
            period.eq(Period.CONTROL),
            If(video_pre, period.eq(Period.VIDEO_PREAMBLE), NextState("VIDEO_PREAMBLE")),
            If(data_pre,  period.eq(Period.DATA_PREAMBLE),  NextState("DATA_PREAMBLE")),
        )
        fsm.act("VIDEO_PREAMBLE",
            period.eq(Period.VIDEO_PREAMBLE),
            If(all_video_gb, period.eq(Period.VIDEO_GUARD), NextState("VIDEO_GUARD"))
            .Elif(~video_pre, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("VIDEO_GUARD",
            period.eq(Period.VIDEO_GUARD),
            If(~all_video_gb, period.eq(Period.VIDEO), NextState("VIDEO")),
        )
        fsm.act("VIDEO",
            period.eq(Period.VIDEO),
            If(any_control, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("DATA_PREAMBLE",
            period.eq(Period.DATA_PREAMBLE),
            If(data_gb, period.eq(Period.DATA_LEADING_GUARD), NextState("DATA_LEADING_GUARD"))
            .Elif(~data_pre, period.eq(Period.CONTROL), NextState("CONTROL")),
        )
        fsm.act("DATA_LEADING_GUARD",
            period.eq(Period.DATA_LEADING_GUARD),
            If(~data_gb, period.eq(Period.DATA_ISLAND), in_island.eq(1), first.eq(1), NextState("DATA_ISLAND")),
        )
        fsm.act("DATA_ISLAND",
            period.eq(Period.DATA_ISLAND),
            in_island.eq(1),
            If(data_gb, period.eq(Period.DATA_TRAILING_GUARD), in_island.eq(0), NextState("DATA_TRAILING_GUARD"))
            .Elif(any_control, period.eq(Period.CONTROL), in_island.eq(0), error.eq(1), NextState("CONTROL")),
        )
        fsm.act("DATA_TRAILING_GUARD",
            period.eq(Period.DATA_TRAILING_GUARD),
            If(~data_gb, period.eq(Period.CONTROL), NextState("CONTROL")),
        )

        # Syncs: control value on channel 0 during control periods, TERC4 bits
        # 0/1 during islands and their guard bands, held during video.
        hsync = Signal()
        vsync = Signal()
        self.sync += [
            If(dec0.control,
                hsync.eq(dec0.c[0]), vsync.eq(dec0.c[1]),
            ).Elif(dec0.terc4_valid & (period >= Period.DATA_PREAMBLE),
                hsync.eq(dec0.terc4[0]), vsync.eq(dec0.terc4[1]),
            ),
        ]

        de = Signal()
        self.comb += de.eq(Mux(self.dvi_mode, ~dec0.control, period == Period.VIDEO))

        # Registered outputs.
        self.sync += [
            self.period.eq(period),
            self.island_active.eq(in_island & self.sink.valid),
            self.island_first.eq(first),
            self.nibble0.eq(dec0.terc4),
            self.nibble1.eq(dec1.terc4),
            self.nibble2.eq(dec2.terc4),
            self.error.eq(error),
            self.source.valid.eq(self.sink.valid),
            self.source.de.eq(de),
            self.source.hsync.eq(Mux(dec0.control, dec0.c[0], hsync)),
            self.source.vsync.eq(Mux(dec0.control, dec0.c[1], vsync)),
            self.source.b.eq(dec0.d),
            self.source.g.eq(dec1.d),
            self.source.r.eq(dec2.d),
        ]
```

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_period.py -v`. Expected: 5 passed (the review of this plan ran this harness against this FSM: periods, pixels, hsync, island nibbles and `first` all match the model). If a period mismatch appears at a transition character, the FSM must report the new period on that character (see the convention above); never loosen the assert.

- [ ] **Step 4: Commit**: `git add litevideo/hdmi/period.py test/test_hdmi_period.py && git commit -m "hdmi: add period decoder (control/video/data island state machine)"`

### Task 14: data island decoder

**Files:**
- Create: `litevideo/hdmi/island/__init__.py`, `litevideo/hdmi/island/decoder.py`, `test/test_hdmi_island_decoder.py`

- [ ] **Step 1: Write the failing test**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.island.decoder import DataIslandDecoder


def random_packet(prng):
    return model.Packet([prng.randrange(256) for _ in range(3)],
                        [[prng.randrange(256) for _ in range(7)] for _ in range(4)])


def run_islands(islands):
    """islands: list of (packets, corrupt kwargs). Drives nibbles directly."""
    dut = DataIslandDecoder()
    out = []

    def drive():
        for packets, corrupt in islands:
            first = True
            for p in packets:
                for hbit, n1, n2 in model.packet_chars(p, **corrupt):
                    yield dut.active.eq(1)
                    yield dut.first.eq(first)
                    yield dut.nibble0.eq(((0 if first else 1) << 3) | (hbit << 2))
                    yield dut.nibble1.eq(n1)
                    yield dut.nibble2.eq(n2)
                    first = False
                    yield
            yield dut.active.eq(0)
            yield dut.first.eq(0)
            for _ in range(8):
                yield
        for _ in range(4):
            yield

    @passive
    def collect():
        while True:
            if (yield dut.source.valid):
                header = (yield dut.source.header)
                subs = []
                for k in range(4):
                    subs.append((yield getattr(dut.source, f"sub{k}")))
                out.append((model.Packet.from_words(header, subs), (yield dut.source.ecc_ok)))
            yield

    run_simulation(dut, [drive(), collect()])
    return dut, out


class TestDataIslandDecoder(unittest.TestCase):
    def test_single_and_multi_packet_islands(self):
        prng = random.Random(11)
        islands = [([random_packet(prng)], {}), ([random_packet(prng) for _ in range(18)], {}), ([model.Packet.null()], {})]
        _, out = run_islands(islands)
        expected = [p for packets, _ in islands for p in packets]
        self.assertEqual([p for p, _ in out], expected)
        self.assertTrue(all(ok for _, ok in out))

    def test_corrupted_ecc_is_flagged(self):
        prng = random.Random(12)
        p = random_packet(prng)
        _, out = run_islands([([p], {"corrupt_header_ecc": True}), ([p], {"corrupt_subpacket_ecc": 2}), ([p], {})])
        self.assertEqual([ok for _, ok in out], [0, 0, 1])
        self.assertEqual(out[2][0], p)

    def test_truncated_island_emits_nothing(self):
        prng = random.Random(13)
        p = random_packet(prng)
        dut = DataIslandDecoder()
        out = []

        def drive():
            for hbit, n1, n2 in model.packet_chars(p)[:20]:
                yield dut.active.eq(1); yield dut.nibble0.eq(hbit << 2); yield dut.nibble1.eq(n1); yield dut.nibble2.eq(n2)
                yield
            yield dut.active.eq(0)
            for _ in range(40):
                if (yield dut.source.valid):
                    out.append(1)
                yield

        run_simulation(dut, drive())
        self.assertEqual(out, [])
```

- [ ] **Step 2: Write the decoder**

`litevideo/hdmi/island/__init__.py`:
```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

from litevideo.hdmi.island.decoder import DataIslandDecoder
from litevideo.hdmi.island.encoder import DataIslandEncoder
```
(Add the encoder import in Task 15; until then import only the decoder.)

`litevideo/hdmi/island/decoder.py`:
```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Data island packet reassembly with BCH ECC check.

Consumes the per-character island nibbles of ``HDMIPeriodDecoder`` and emits
one ``packet_rx_layout`` beat per 32-character packet (HDMI 1.3 §5.2.3.4):
channel 0 bit 2 carries the header (24 data bits then 8 ECC bits, LSB first);
channel 1 bit k and channel 2 bit k carry BCH block k (56 data bits then 8 ECC
bits, two bits per character, channel 1 first). The five ECCs are recomputed
serially with ``bch_step`` while the packet streams by and compared with the
received ones at character 31 (§5.2.3.5). The source has no back-pressure;
an integrator that cannot keep up drops packets and should count them.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_step


class DataIslandDecoder(LiteXModule):
    def __init__(self):
        self.active  = Signal()     # a packet character is present on the nibbles
        self.first   = Signal()     # ... and it is the first character of the island
        self.nibble0 = Signal(4)
        self.nibble1 = Signal(4)
        self.nibble2 = Signal(4)

        self.source = stream.Endpoint(packet_rx_layout)
        self.packet_count = Signal(32)
        self.ecc_error_count = Signal(32)

        # # #

        char = Signal(5)
        hbit = self.nibble0[2]

        # Character counter: restarts at the first character of an island, wraps every 32.
        self.sync += If(~self.active, char.eq(0)).Elif(self.first, char.eq(1)).Else(char.eq(char + 1))
        index = Signal(5)
        self.comb += index.eq(Mux(self.first, 0, char))

        # Shift registers for received bits.
        header  = Signal(24)
        hecc_rx = Signal(8)
        subs    = [Signal(56) for _ in range(4)]
        secc_rx = [Signal(8) for _ in range(4)]
        self.sync += If(self.active,
            If(index < 24, header.eq(Cat(header[1:], hbit))).Else(hecc_rx.eq(Cat(hecc_rx[1:], hbit))),
        )
        for k in range(4):
            bits = Cat(self.nibble1[k], self.nibble2[k])
            self.sync += If(self.active,
                If(index < 28, subs[k].eq(Cat(subs[k][2:], bits))).Else(secc_rx[k].eq(Cat(secc_rx[k][2:], bits))),
            )

        # Serial ECC over the data bits (reset at character 0).
        hecc = Signal(8)
        secc = [Signal(8) for _ in range(4)]
        hbase = Mux(index == 0, 0, hecc)
        self.sync += If(self.active & (index < 24), hecc.eq(bch_step(hbase, hbit)))
        for k in range(4):
            base = Mux(index == 0, 0, secc[k])
            self.sync += If(self.active & (index < 28),
                secc[k].eq(bch_step(bch_step(base, self.nibble1[k]), self.nibble2[k])))

        # Emit at the cycle after character 31.
        done = Signal()
        self.sync += done.eq(self.active & (index == 31))
        ecc_ok = (hecc == hecc_rx)
        for k in range(4):
            ecc_ok = ecc_ok & (secc[k] == secc_rx[k])
        self.comb += [
            self.source.valid.eq(done),
            self.source.header.eq(header),
            self.source.ecc_ok.eq(ecc_ok),
        ]
        for k in range(4):
            self.comb += getattr(self.source, f"sub{k}").eq(subs[k])
        self.sync += If(done,
            self.packet_count.eq(self.packet_count + 1),
            If(~ecc_ok, self.ecc_error_count.eq(self.ecc_error_count + 1)),
        )
```

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_island_decoder.py -v` → 3 passed. If the emitted header/subpackets are shifted by one bit, the culprit is `index` at `first` (must be 0 while `char` still holds the previous value); check with the `--vcd` option of `run_simulation` (`run_simulation(dut, gens, vcd_name="tmp/x.vcd")`) and delete the file afterwards.

- [ ] **Step 4: Commit**: `git add litevideo/hdmi/island test/test_hdmi_island_decoder.py && git commit -m "hdmi: add data island decoder with serial BCH ECC check"`

### Task 15: data island encoder

**Files:**
- Create: `litevideo/hdmi/island/encoder.py`, `test/test_hdmi_island_encoder.py`, `test/test_hdmi_island_roundtrip.py`
- Modify: `litevideo/hdmi/island/__init__.py` (add import)

Interface: `sink` (`packet_layout`, one beat per packet), inputs `hsync`, `vsync`, `max_packets` (5 bits, how many packets may go into the island that is about to start, 1..18), `start` (level: the framer allows an island to start now). Output `source` (`raw_layout`) with `valid` high from the first preamble character to the last trailing guard band character, plus `busy`. A packet is accepted (`sink.ready` pulse) at island start and, for chained packets, at character 31 of the previous packet if `sink.valid` and fewer than `max_packets` packets have been sent.

- [ ] **Step 1: Write the failing tests**

`test/test_hdmi_island_encoder.py`:
```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.island.encoder import DataIslandEncoder

from test.common import stream_inserter


def random_packet(prng):
    return model.Packet([prng.randrange(256) for _ in range(3)],
                        [[prng.randrange(256) for _ in range(7)] for _ in range(4)])


def encode(packets, max_packets=18, hsync=0, vsync=1, valid_rand=0):
    dut = DataIslandEncoder()
    beats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
    out = []

    @passive
    def collect():
        while True:
            if (yield dut.source.valid):
                out.append(((yield dut.source.c0), (yield dut.source.c1), (yield dut.source.c2)))
            yield

    def control():
        yield dut.hsync.eq(hsync); yield dut.vsync.eq(vsync)
        yield dut.max_packets.eq(max_packets); yield dut.start.eq(1)
        for _ in range(len(packets) * 40 + 40):
            yield

    run_simulation(dut, [stream_inserter(dut.sink, beats, valid_rand=valid_rand), collect(), control()])
    return out


class TestDataIslandEncoder(unittest.TestCase):
    def test_single_packet_matches_model(self):
        p = model.Packet([0x82, 0x02, 0x0D], [[i + 7 * k for i in range(7)] for k in range(4)])
        self.assertEqual(encode([p]), model.island_tokens([p], hsync=0, vsync=1))

    def test_multi_packet_island(self):
        prng = random.Random(21)
        packets = [random_packet(prng) for _ in range(5)]
        self.assertEqual(encode(packets), model.island_tokens(packets, hsync=0, vsync=1))

    def test_max_packets_splits_islands(self):
        prng = random.Random(22)
        packets = [random_packet(prng) for _ in range(3)]
        expected = model.island_tokens(packets[:2], vsync=1) + model.island_tokens(packets[2:], vsync=1)
        self.assertEqual(encode(packets, max_packets=2), expected)

    def test_gap_in_sink_ends_island(self):
        prng = random.Random(23)
        packets = [random_packet(prng) for _ in range(4)]
        out = encode(packets, valid_rand=60)
        # Every emitted character must belong to a well-formed island; count islands by preambles.
        n_pre = sum(1 for t in out if t == model.control_chars(0, 1, PREAMBLE_DATA)) // PREAMBLE_LENGTH
        self.assertGreaterEqual(n_pre, 1)
        self.assertEqual((len(out) - n_pre * (PREAMBLE_LENGTH + 2 * GUARD_BAND_LENGTH)) % PACKET_LENGTH, 0)
```

`test/test_hdmi_island_roundtrip.py`:
```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Encoder -> period decoder -> island decoder, all gateware."""

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandEncoder, DataIslandDecoder

from test.common import stream_inserter


class DUT(Module):
    def __init__(self):
        self.submodules.enc = DataIslandEncoder()
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        idle = model.control_chars(0, 0)
        self.comb += [
            self.period.sink.valid.eq(1),
            If(self.enc.source.valid,
                self.period.sink.c0.eq(self.enc.source.c0),
                self.period.sink.c1.eq(self.enc.source.c1),
                self.period.sink.c2.eq(self.enc.source.c2),
            ).Else(
                self.period.sink.c0.eq(idle[0]), self.period.sink.c1.eq(idle[1]), self.period.sink.c2.eq(idle[2]),
            ),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
        ]


class TestIslandRoundTrip(unittest.TestCase):
    def test_roundtrip(self):
        prng = random.Random(31)
        packets = [model.Packet([prng.randrange(256) for _ in range(3)],
                                [[prng.randrange(256) for _ in range(7)] for _ in range(4)]) for _ in range(30)]
        dut = DUT()
        beats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
        out = []

        @passive
        def collect():
            while True:
                if (yield dut.dec.source.valid):
                    header = (yield dut.dec.source.header)
                    subs = []
                    for k in range(4):
                        subs.append((yield getattr(dut.dec.source, f"sub{k}")))
                    out.append((model.Packet.from_words(header, subs), (yield dut.dec.source.ecc_ok)))
                yield

        def control():
            yield dut.enc.max_packets.eq(7)
            yield dut.enc.start.eq(1)
            for _ in range(len(packets) * 40 + 100):
                yield

        run_simulation(dut, [stream_inserter(dut.enc.sink, beats, valid_rand=30), collect(), control()])
        self.assertEqual([p for p, _ in out], packets)
        self.assertTrue(all(ok for _, ok in out))
```

- [ ] **Step 2: Write `litevideo/hdmi/island/encoder.py`**

```python
#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Data island serialiser.

Turns a stream of packets into framed data islands (HDMI 1.3 §5.2.3): the
8-character Data Island Preamble (Table 5-2: CTL0=1, CTL2=1 on channels 1 and
2, HSYNC/VSYNC on channel 0), the 2-character Leading Guard Band (Table 5-6
on channels 1/2, TERC4(1,1,VSYNC,HSYNC) on channel 0, §5.2.3.3), one to
``max_packets`` packets of 32 TERC4 characters (§5.2.3.4: header bit on
channel 0 bit 2, BCH block k on bit k of channels 1 and 2, ECC generated
serially with ``bch_step``, §5.2.3.5), then the Trailing Guard Band.
Channel 0 bit 3 is 0 on the first character of the island and 1 on every
other packet character (HDMI 1.4b CTS requirement). The caller (the framer)
raises ``start`` only where an island fits and supplies ``max_packets``; it
must send at least ``MIN_ISLAND_TO_PREAMBLE`` control characters after
``source.valid`` falls (§5.2.3.2, Figure 5-3).
"""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_step


class DataIslandEncoder(LiteXModule):
    def __init__(self):
        self.sink   = stream.Endpoint(packet_layout)
        self.source = stream.Endpoint(raw_layout)
        self.hsync       = Signal()
        self.vsync       = Signal()
        self.start       = Signal()
        self.max_packets = Signal(5, reset=MAX_PACKETS_PER_ISLAND)
        self.busy        = Signal()

        # # #

        # Packet registers (shifted out LSB first) and serial ECC accumulators.
        header = Signal(24)
        hecc   = Signal(8)
        subs   = [Signal(56) for _ in range(4)]
        secc   = [Signal(8) for _ in range(4)]
        count  = Signal(5)    # characters within the current phase
        npkt   = Signal(5)    # packets sent in this island
        first  = Signal()     # current character is the first of the island
        hsync_l = Signal()
        vsync_l = Signal()

        def load_packet():
            return [
                NextValue(header, self.sink.header), NextValue(hecc, 0),
                *[NextValue(subs[k], getattr(self.sink, f"sub{k}")) for k in range(4)],
                *[NextValue(secc[k], 0) for k in range(4)],
            ]

        # Current character contents.
        hbit = Mux(count < 24, header[0], hecc[0])
        n1 = Signal(4)
        n2 = Signal(4)
        for k in range(4):
            self.comb += [
                n1[k].eq(Mux(count < 28, subs[k][0], secc[k][0])),
                n2[k].eq(Mux(count < 28, subs[k][1], secc[k][1])),
            ]
        n0 = Cat(hsync_l, vsync_l, hbit, ~first)

        terc4 = Array(terc4_tokens)
        ctl0 = Array(control_tokens)[Cat(hsync_l, vsync_l)]
        gb0  = terc4[Cat(hsync_l, vsync_l, C(0b11, 2))]
        pre  = (ctl0, control_tokens[PREAMBLE_DATA[0]], control_tokens[PREAMBLE_DATA[1]])
        gb   = (gb0, data_gb_token, data_gb_token)

        def emit(c):
            return [self.source.valid.eq(1), self.source.c0.eq(c[0]), self.source.c1.eq(c[1]), self.source.c2.eq(c[2])]

        def shift():
            acts = [
                If(count < 24, NextValue(hecc, bch_step(hecc, header[0]))).Else(NextValue(hecc, Cat(hecc[1:], 0))),
                NextValue(header, Cat(header[1:], 0)),
            ]
            for k in range(4):
                acts += [
                    If(count < 28,
                        NextValue(secc[k], bch_step(bch_step(secc[k], subs[k][0]), subs[k][1])),
                    ).Else(
                        NextValue(secc[k], Cat(secc[k][2:], 0)),
                    ),
                    NextValue(subs[k], Cat(subs[k][2:], 0)),
                ]
            return acts

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(self.start & self.sink.valid & (self.max_packets != 0),
                self.sink.ready.eq(1),
                *load_packet(),
                NextValue(hsync_l, self.hsync), NextValue(vsync_l, self.vsync),
                NextValue(count, 0), NextValue(npkt, 1),
                NextState("PREAMBLE"),
            ),
        )
        fsm.act("PREAMBLE",
            self.busy.eq(1), *emit(pre),
            NextValue(count, count + 1),
            If(count == PREAMBLE_LENGTH - 1, NextValue(count, 0), NextState("LEADING_GUARD")),
        )
        fsm.act("LEADING_GUARD",
            self.busy.eq(1), *emit(gb),
            NextValue(count, count + 1),
            If(count == GUARD_BAND_LENGTH - 1, NextValue(count, 0), NextValue(first, 1), NextState("PACKET")),
        )
        fsm.act("PACKET",
            self.busy.eq(1), *emit((terc4[n0], terc4[n1], terc4[n2])),
            *shift(),
            NextValue(first, 0),
            NextValue(count, count + 1),
            If(count == PACKET_LENGTH - 1,
                NextValue(count, 0),
                If(self.sink.valid & (npkt < self.max_packets),
                    self.sink.ready.eq(1),
                    *load_packet(),
                    NextValue(npkt, npkt + 1),
                ).Else(
                    NextState("TRAILING_GUARD"),
                ),
            ),
        )
        fsm.act("TRAILING_GUARD",
            self.busy.eq(1), *emit(gb),
            NextValue(count, count + 1),
            If(count == GUARD_BAND_LENGTH - 1, NextValue(count, 0), NextState("IDLE")),
        )
```

Add `from litevideo.hdmi.island.encoder import DataIslandEncoder` to `litevideo/hdmi/island/__init__.py`.

- [ ] **Step 3: Run**: `uv run pytest test/test_hdmi_island_encoder.py test/test_hdmi_island_roundtrip.py -v` → 5 passed. Typical first failure: the ECC bits appear one character early or late; the invariant is that `hecc` after the shift at `count == 23` equals `bch_ecc(header bytes)` and its bit 0 is emitted at `count == 24`. Compare `encode([p])[10:42]` against `model.island_tokens([p])[10:42]` element by element to see where they diverge.

- [ ] **Step 4: Run the full suite**: `uv run pytest -q` → all pass.

- [ ] **Step 5: Commit**: `git add litevideo/hdmi/island test/test_hdmi_island_encoder.py test/test_hdmi_island_roundtrip.py && git commit -m "hdmi: add data island encoder and encoder->decoder round trip test"`

### Task 16: `doc/hdmi-protocol.md`

**Files:**
- Create: `doc/hdmi-protocol.md`
- Modify: `doc/README.md` (link already present)

- [ ] **Step 1: Write the document** covering, each with the spec section: the three periods and Figure 5-3 with an ASCII timeline of one line (control, data island preamble 8, leading guard 2, N×32 packet characters, trailing guard 2, ≥4 control, video preamble 8, video guard 2, video); TMDS characters (control tokens table, TERC4 table, guard band values incl. channel 0's TERC4(1,1,V,H)); channel 0 bit assignment inside islands (H, V, header bit, bit 3 rule); packet structure (Figure 5-4 mapping, byte order); BCH ECC (polynomial, LFSR, worked example: header `01 00 00` → ECC `0x4A`); placement rules (12-character control periods, 1..18 packets, ≥4 control after an island, extended control period 32 characters every 50 ms, one island per two fields); packet types table; and a "How the LiteVideo modules map to this" section (`TMDSCharacterDecoder` → `HDMIPeriodDecoder` → `DataIslandDecoder`; `DataIslandEncoder` and the framer to come) with the latency of each. Also a short "Differences found in other implementations" section listing the three netv2-fpga divergences (ECC polynomial, ASP subpacket layout, channel 0 guard band) with the spec references, so readers testing against that tree know why streams disagree.

- [ ] **Step 2: Commit**: `git add doc/hdmi-protocol.md && git commit -m "doc: add HDMI link-layer protocol documentation"`

### Task 17: review and push

- [ ] **Step 1: Push**: `git push origin hdmi-support` and confirm CI green (`gh run list -R mithro/litevideo -b hdmi-support -L 1`).
- [ ] **Step 2: Dispatch a review sub-agent** (superpowers:requesting-code-review) over `git diff master...hdmi-support` with the spec text dump path for protocol checks; ask specifically for: FSM edge cases (islands directly after video, back-to-back islands, syncs changing inside an island), bit-order mistakes, and resource concerns (the encoder's `Array(terc4_tokens)[n]` muxes and the decoder's five LFSRs).
- [ ] **Step 3: Fix findings, re-run `uv run pytest -q`, commit, push.**
- [ ] **Step 4: Update `LOG.md` and `TODO.md` on `claude-notes`** (worktree `.worktrees/notes`) with what landed and the measured numbers; commit and push.
