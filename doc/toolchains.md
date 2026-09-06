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
