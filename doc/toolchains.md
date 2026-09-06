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

## Results (2026-09-07, `bench/netv2/hdmi_tx`, XC7A100T-2, 720p bars + tone)

| Flow | LUTs | FFs | BRAM | DSP | WNS (ns) | Hardware |
|---|---|---|---|---|---|---|
| Vivado 2025.2 synth + P&R | 1795 | 2965 | 0.5 | 12 | 1.206 | (same design as the loopback runs) |
| Yosys 0.52 synth (`--synth-mode yosys`) + Vivado P&R | 2123 | 3390 | 0 | 9 | 1.206 | tier T4 pass: Magewell bars in HDMI/DVI, AVMUTE blanks, 1 kHz tone 43 dB (`doc/reports/2026-09-07-netv2-tx-yosys.md`) |
| openXC7 0.8.2 snap (Yosys + nextpnr-xilinx 0.8.2) | — | — | — | — | — | nextpnr rejects the cascaded 10:1 OSERDESE2 ("has disconnected OQ/OFB output ports" on the SLAVE half); master/slave support exists in openXC7/nextpnr-xilinx master (`xilinx/pack_io_xc7.cc`), so a newer nextpnr is built locally (see below) |

Yosys keeps the run-time colour matrix in 9 DSP48E1 (one per 9x15 multiply)
and puts the 256x24 tone ROM in LUTs rather than block RAM; Vivado splits
three of the multiplies and uses half a BRAM tile.

### openXC7 environment

The snap-derived toolchain from `fpgas-online-test-designs` lives in
`~/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7`:

    export PATH=$T/bin:$PATH
    export CHIPDB=$T/chipdb
    export PRJXRAY_DB_DIR=$T/squashfs-root/opt/nextpnr-xilinx/external/prjxray-db
    export NEXTPNR_XILINX_PYTHON_DIR=$T/squashfs-root/opt/nextpnr-xilinx/python
    uv run scripts/limited.py -- uv run python -m bench.netv2.hdmi_tx --build --toolchain openxc7

`bench/netv2/openxc7.py` applies the litex-boards/openXC7 device-name fixup
(`xc7a100t-fgg484-2` -> `xc7a100tfgg484-2`), a chipdb symlink and the
`$scopeinfo` deletion for Yosys >= 0.40.
