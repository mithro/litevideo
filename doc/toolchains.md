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
| openXC7: Yosys 0.52 (`-nodsp`) + nextpnr-xilinx master (bd9c74c + 2 local fixes) + openXC7/prjxray-db master, full bench incl. converter | — | — | — | 0 | nextpnr: pix 86.8 MHz vs 73.75 needed | **tier T4 pass for video**: bars pixel-exact in HDMI and DVI mode, AVMUTE blanks; tone captured at 993.3 Hz with 24 dB, identical to the Vivado control build with the same integer MMCM clock (`doc/reports/2026-09-07-netv2-tx-openxc7-converter.md`, `-tx-vivado-int.md`) |

### openXC7 findings (2026-09-07)

Fixed in the local nextpnr-xilinx clone (`~/github/openXC7/nextpnr-xilinx`, branch `litevideo-fixes`, commit ef7c4f2, pushed to the fork https://github.com/mithro/nextpnr-xilinx/tree/litevideo-fixes; no upstream pull request has been opened), each confirmed on hardware by patching the FASM first:

1. **MMCM never locked**: `xilinx/fasm.cc` defaulted `CLKFBOUT_PHASE`/`CLKOUTn_PHASE` to 1 degree when the instance omits the parameter (LiteX's `S7MMCM` does), giving `CLKFBOUT_CLKOUT1_PHASE_MUX = 1`; every other MMCM bit matched Vivado's bitstream (`bit2fasm` diff). Default is now 0.
2. **TMDS_33 outputs were slow slew**: Vivado sets `SLEW.FAST` on both sites of a TMDS_33/LVDS_25 pair regardless of the attribute; nextpnr emitted nothing. (Did not change the observed errors, but matches Vivado.)
3. The packaged prjxray-db lacks `OSERDES.DATA_WIDTH.DDR.W10`; openXC7/prjxray-db master has it (sparse clone of `artix7`, 190 MB). The chip database must be regenerated from the same database (`bbaexport.py` + `bbasm`, about 5 minutes for XC7A100T).
4. Fractional MMCM settings (LiteX's default 74.219 MHz) did not lock even with fix 1; the bench uses `S7MMCM(fractional=False)` for the open flow (73.75 MHz). The 24 dB tone figure (44 dB with the 74.219 MHz clock) is the capture card resampling 47.68 kHz audio to 48 kHz and appears identically with Vivado's bitstream.
5. An earlier `-nodsp` build with the *unfixed* nextpnr (FASM patched by hand) showed the green channel stuck at 255 and no data islands; the same design through the fixed nextpnr is exact, so that was most likely a placement/routing difference between runs rather than a property of the design. Worth re-checking across seeds.

**DSP48E1 cascades are broken in nextpnr-xilinx.** `bench/netv2/csc_test.py`
(one `CSCMatrix` with CSR-loaded coefficients and pixels, sys domain only)
reproduces it: Yosys chains the three products of each matrix row through
the DSP48E1 PCIN/PCOUT cascade (MREG absorbed, `keep` on the product
registers does not prevent it), and on hardware two of the three chains
lose one product (rows 0 and 1 of column 0 read as zero: identity gives
(255,255,255) -> (0,255,255)); the same design synthesised with `-nodsp` is
exact for 64 pixels x 4 matrices (`doc/reports/2026-09-07-netv2-csc-test-openxc7-{dsp,lut}.md`).
This explains the tx bench's blue = blue AND red. `bench/netv2/openxc7.py`
therefore adds `-nodsp` for the open flow unless `LITEVIDEO_OPENXC7_DSP` is
set. Not yet fixed in nextpnr (the cascade routing/placement in
`xilinx/pack_dsp*.cc` is the place to look).

**Receiver on openXC7: blocked** (`bench/netv2/hdmi_rx --toolchain openxc7`):
nextpnr-xilinx stops with `IDELAYE2 'IDELAYE2' has disconnected IDATAIN
input`. The 7-series capture path (`litevideo/input/datacapture.py`) feeds
the master and slave IDELAYE2 from the two outputs of an `IBUFDS_DIFF_OUT`,
and `S7MMCMClocking` uses the same primitive for the clock; nextpnr only
implements `IBUFDS_DIFF_OUT` for UltraScale (`xilinx/pack_io_xcup.cc`), the
xc7 packer (`xilinx/pack_io_xc7.cc`) has no handling for the OB output, so
the slave delay has no driver. Adding it needs the IOB33 differential-output
input configuration bits (prjxray `IN_DIFF`/`IBUFDS_DIFF_OUT` features) in
`write_io_config`; the alternative, a slave IDELAY driven from fabric
(`DELAY_SRC=DATAIN`), is not accepted by the packer either. Left for a later
tool-fork task.

Practicalities: `fasm2frames` from the snap falls back to the pure-Python
`fasm` parser (about 4 minutes for this design); the PyPI `fasm` wheel for
Python 3.12 has no ANTLR accelerator either.

Yosys keeps the run-time colour matrix in 9 DSP48E1 (one per 9x15 multiply)
and puts the 256x24 tone ROM in LUTs rather than block RAM; Vivado splits
three of the multiplies and uses half a BRAM tile.

### openXC7 environment

`source scripts/openxc7-env.sh` sets `PATH`, `CHIPDB`, `PRJXRAY_DB_DIR` and
`NEXTPNR_XILINX_PYTHON_DIR` for the working combination (locally built
nextpnr-xilinx with the fixes below, openXC7/prjxray-db master, a chipdb
regenerated from it, and the snap's fasm2frames/xc7frames2bit); then

    uv run scripts/limited.py --memory-max 12G -- uv run python -m bench.netv2.hdmi_tx --build --toolchain openxc7 \
        --output-dir build/netv2-hdmi-tx-openxc7 --csr-csv build/netv2-hdmi-tx-openxc7/csr.csv

The snap alone (`fpgas-online-test-designs/.venv/toolchains/openxc7`) does
not work for this design, see the findings.

`bench/netv2/openxc7.py` applies the litex-boards/openXC7 device-name fixup
(`xc7a100t-fgg484-2` -> `xc7a100tfgg484-2`), a chipdb symlink and the
`$scopeinfo` deletion for Yosys >= 0.40.
