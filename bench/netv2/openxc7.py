#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""openXC7 (Yosys + nextpnr-xilinx + Project X-Ray) build support for the
NeTV2 benches: ``--toolchain openxc7``.

Environment (see doc/toolchains.md): ``CHIPDB`` (nextpnr-xilinx chip
databases), ``PRJXRAY_DB_DIR`` (prjxray-db), ``NEXTPNR_XILINX_PYTHON_DIR``
and ``nextpnr-xilinx``, ``fasm2frames``, ``xc7frames2bit``, ``bbasm`` on
``PATH``. Workarounds, after fpgas-online-test-designs ``designs/_shared``:

* litex-boards names the NeTV2 part ``xc7a100t-fgg484-2``; prjxray-db and
  the chip databases use ``xc7a100tfgg484-2``, so the dash is removed and
  a chipdb symlink is made for the undashed name.
* Yosys >= 0.40 emits ``$scopeinfo`` cells that nextpnr-xilinx cannot
  place: they are deleted before ``write_json``.
"""

import os
import re

from litex.build.yosys_wrapper import YosysWrapper


def fix_device_name(platform):
    """``xc7a100t-fgg484-2`` -> ``xc7a100tfgg484-2``; returns the old name or None."""
    old = platform.device
    new = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", old)
    if new != old:
        platform.device = new
        return old
    return None


def ensure_chipdb_symlink(platform):
    chipdb_dir = os.environ.get("CHIPDB", "")
    if not chipdb_dir:
        return
    undashed = re.sub(r"-\d+L?$", "", platform.device)                        # xc7a100tfgg484
    dashed = re.sub(r"^(xc7[aksz]\d+t)(.*)", r"\1-\2", undashed)               # xc7a100t-fgg484
    old, new = os.path.join(chipdb_dir, dashed + ".bin"), os.path.join(chipdb_dir, undashed + ".bin")
    if os.path.exists(old) and not os.path.exists(new):
        try:
            os.symlink(old, new)
        except FileExistsError:
            pass


def patch_yosys_template(soc):
    """Delete ``$scopeinfo`` cells before the netlist is written."""
    tc = soc.platform.toolchain
    assert hasattr(tc, "_yosys_template"), "LiteX toolchain lacks _yosys_template"
    template = list(YosysWrapper._default_template)
    for i, line in enumerate(template):
        if line.startswith("write_"):
            template.insert(i, "delete t:$scopeinfo")
            break
    tc._yosys_template = template


def prepare_platform(platform):
    fix_device_name(platform)
    ensure_chipdb_symlink(platform)


def prepare_soc(soc):
    patch_yosys_template(soc)
