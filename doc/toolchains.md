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
| openXC7: Yosys 0.52 + nextpnr-xilinx master (bd9c74c + 2 local fixes) + openXC7/prjxray-db master, `LITEVIDEO_NO_CONVERTER=1` | — | — | — | 0 | nextpnr: pix 85 MHz vs 73.75 needed | **tier T4 pass for video**: bars pixel-exact in HDMI and DVI mode, AVMUTE blanks; tone captured at 993.3 Hz with 24 dB, identical to the Vivado control build with the same integer MMCM clock (`doc/reports/2026-09-07-netv2-tx-openxc7.md`, `-tx-vivado-int.md`) |

### openXC7 findings (2026-09-07)

Fixed in the local nextpnr-xilinx clone (`~/github/openXC7/nextpnr-xilinx`, branch `litevideo-fixes`, commit ef7c4f2), each confirmed on hardware by patching the FASM first:

1. **MMCM never locked**: `xilinx/fasm.cc` defaulted `CLKFBOUT_PHASE`/`CLKOUTn_PHASE` to 1 degree when the instance omits the parameter (LiteX's `S7MMCM` does), giving `CLKFBOUT_CLKOUT1_PHASE_MUX = 1`; every other MMCM bit matched Vivado's bitstream (`bit2fasm` diff). Default is now 0.
2. **TMDS_33 outputs were slow slew**: Vivado sets `SLEW.FAST` on both sites of a TMDS_33/LVDS_25 pair regardless of the attribute; nextpnr emitted nothing. (Did not change the observed errors, but matches Vivado.)
3. The packaged prjxray-db lacks `OSERDES.DATA_WIDTH.DDR.W10`; openXC7/prjxray-db master has it (sparse clone of `artix7`, 190 MB). The chip database must be regenerated from the same database (`bbaexport.py` + `bbasm`, about 5 minutes for XC7A100T).
4. Fractional MMCM settings (LiteX's default 74.219 MHz) did not lock even with fix 1; the bench uses `S7MMCM(fractional=False)` for the open flow (73.75 MHz).

Open: with the `PixelFormatConverter` present the open-flow bitstream produces
wrong pixel arithmetic while Yosys+Vivado from the same Yosys front end is
correct: with DSP48E1 inference the blue output became (blue AND red); with
`-nodsp` the green output stuck at 255 and the data islands disappeared. The
same design without the converter is pixel-exact, so this is a
nextpnr-xilinx issue around the matrix's multiply/accumulate logic (DSP48E1
cell support and/or CARRY4 chains) that needs a small reproduction design
with a CRC readable over uartbone; not yet characterised.

Practicalities: `fasm2frames` from the snap falls back to the pure-Python
`fasm` parser (about 4 minutes for this design); the PyPI `fasm` wheel for
Python 3.12 has no ANTLR accelerator either.

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
