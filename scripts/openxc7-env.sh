#!/bin/bash
# Environment for the openXC7 flow used by the NeTV2 benches (doc/toolchains.md).
# Source it, then e.g.:
#   uv run scripts/limited.py --memory-max 12G -- uv run python -m bench.netv2.hdmi_tx --build --toolchain openxc7 \
#       --output-dir build/netv2-hdmi-tx-openxc7 --csr-csv build/netv2-hdmi-tx-openxc7/csr.csv
#
# Tools (2026-09-07):
#  - nextpnr-xilinx: openXC7 master + fixes, built from ~/github/openXC7/nextpnr-xilinx
#    (branch litevideo-fixes, also at https://github.com/mithro/nextpnr-xilinx)
#  - prjxray-db: openXC7/prjxray-db master (artix7 sparse clone) in ~/github/openXC7/prjxray-db
#  - chipdb: regenerated from that database with nextpnr's bbaexport.py + bbasm into ~/github/openXC7/chipdb
#  - fasm2frames / xc7frames2bit / bbasm: from the openXC7 0.8.2 snap unpacked by fpgas-online-test-designs
OPENXC7_SNAP=${OPENXC7_SNAP:-$HOME/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7}
OPENXC7_SRC=${OPENXC7_SRC:-$HOME/github/openXC7}
export PATH="$OPENXC7_SRC/nextpnr-xilinx/build:$OPENXC7_SNAP/bin:$PATH"
export CHIPDB="$OPENXC7_SRC/chipdb"
export PRJXRAY_DB_DIR="$OPENXC7_SRC/prjxray-db"
export NEXTPNR_XILINX_PYTHON_DIR="$OPENXC7_SNAP/squashfs-root/opt/nextpnr-xilinx/python"
