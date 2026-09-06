# Resource usage

## Per core (Yosys estimate)

`scripts/resources.py` elaborates each core standalone, synthesises it with
Yosys 0.52 (`synth_xilinx -family xc7 -flatten`) and tabulates the cells.
MUXF7/MUXF8 are the free slice muxes, listed separately from LUTs. These
are comparison figures; place-and-route numbers for whole benches are in
`doc/toolchains.md`. Generated 2026-09-07 on `hdmi-support`:

| Core | LUTs | MUXF7/8 | FFs | CARRY4 | DSP48E1 | RAMB | LUTRAM |
|---|---|---|---|---|---|---|---|
| `tmds_decoder` | 59 | 14 | 17 | 0 | 0 | 0 | 0 |
| `period_decoder` | 210 | 38 | 103 | 0 | 0 | 0 | 0 |
| `island_decoder` | 79 | 5 | 430 | 26 | 0 | 0 | 0 |
| `island_encoder` | 618 | 13 | 302 | 4 | 0 | 0 | 0 |
| `framer` | 1467 | 743 | 969 | 55 | 0 | 0 | 0 |
| `scheduler_5` | 770 | 754 | 4 | 0 | 0 | 0 | 0 |
| `avi_infoframe` | 150 | 35 | 112 | 2 | 0 | 0 | 0 |
| `gcp` | 3 | 0 | 9 | 0 | 0 | 0 | 0 |
| `audio_packetizer` | 296 | 11 | 247 | 12 | 0 | 0 | 0 |
| `acr` | 102 | 0 | 149 | 35 | 0 | 0 | 0 |
| `audio_infoframe` | 39 | 16 | 35 | 2 | 0 | 0 | 0 |
| `audio_extract` | 97 | 0 | 494 | 41 | 0 | 0 | 0 |
| `tone_generator` | 157 | 70 | 163 | 33 | 0 | 0 | 0 |
| `csc_matrix_const` | 85 | 0 | 66 | 33 | 9 | 0 | 0 |
| `csc_matrix_runtime` | 222 | 0 | 66 | 27 | 9 | 0 | 0 |
| `wire422_pack` | 33 | 0 | 51 | 6 | 0 | 0 | 0 |
| `wire422_unpack` | 17 | 0 | 51 | 0 | 0 | 0 | 0 |
| `pixel_format_conv` | 507 | 4 | 413 | 33 | 9 | 0 | 0 |
| `rgb2ycbcr_xapp930` | 68 | 3 | 188 | 21 | 4 | 0 | 0 |
| `ycbcr2rgb_xapp931` | 66 | 0 | 81 | 11 | 4 | 0 | 0 |

Notes:

* `framer` includes the three TMDS encoders, the island encoder and the
  11-stage delay line; its MUXF count comes from the 30-bit character
  overrides (preambles, guard bands, islands) muxed over the encoder outputs.
* `scheduler_5` is a 5:1 mux of the 248-bit packet: about 3 LUTs per bit,
  which is what a 5-input mux costs; a one-hot AND-OR formulation measured
  the same. Serialising packets between generators and the island encoder
  (9 bits per character instead of 248 per packet) would remove most of it
  and is the main optimisation candidate for phase 7.
* `csc_matrix_const` still infers 9 DSP48E1 for constant multiplies; add
  `(* use_dsp = "no" *)` or a `-nodsp`-style option if DSPs are scarce.
  `csc_matrix_runtime` is the same datapath with coefficient inputs.
* `pixel_format_conv` = unpack + run-time matrix + pack + the 64-entry
  coefficient table (about 220 LUTs of the total).
* `tone_generator`: the 256x24 ROM is LUTs in Yosys (Vivado uses half a
  block RAM tile).

## Whole benches (place and route)

| Bench | Flow | LUTs | FFs | BRAM | DSP | WNS (ns) |
|---|---|---|---|---|---|---|
| `hdmi_tx` (720p bars, audio, format converter) | Vivado 2025.2 | 1795 | 2965 | 0.5 | 12 | 1.206 |
| `hdmi_tx` | Yosys 0.52 + Vivado P&R | 2123 | 3390 | 0 | 9 | 1.206 |
| `hdmi_loopback` (tx + fabric receiver + audio extract + capture) | Vivado | 2511 | 5458 | 1 | 12 | 1.206 |
| `hdmi_rx` 65 MHz (capture front end + receiver + converter + CRCs) | Vivado | 2018 | — | 0.5 | 12 | 0.451 |
