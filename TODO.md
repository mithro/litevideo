# TODO

Status: `[ ]` open, `[~]` in progress, `[x]` done, `[!]` blocked (reason).

## Phase 0: scaffolding
- [x] Fast-forward fork to upstream and push
- [x] Worktrees and branches
- [x] Design spec written
- [x] Spec review by sub-agent (2 rounds, approved)
- [x] Phase 0+1 plan (2 review rounds, approved)
- [x] `pyproject.toml` + uv environment pinned to LiteX 2026.04
- [x] `test/` with the existing csc benches ported to pytest
- [x] `.github/workflows/ci.yml` (green)
- [x] `scripts/limited.py` cgroup wrapper
- [x] `doc/` skeleton and README update

## Phase 1: protocol layer
- [x] `hdmi/common.py` constants with spec references
- [x] `hdmi/bch.py` + vectors vs hdl-util
- [x] `hdmi/model.py` golden model
- [x] `hdmi/period.py` period decoder (DecodeTERC4 compat wrapper deferred to phase 5)
- [x] island decoder, island encoder, tests, `doc/hdmi-protocol.md` (reviewed, fixes landed)

## Phase 2: transmitter
- [x] plan (2 review rounds, approved)
- [x] framer, scheduler, InfoFrame generators, `HDMITransmitter` (HDMIOut wrapper deferred to phase 5; raw S7 PHY reused)
- [x] `bench/netv2/hdmi_tx`, fabric loopback target built; T1 (13/13) and T4 (Magewell locks, AVMUTE honoured) pass on rpi5 with the preliminary bitstream
- [~] rebuild with the OCE fix and re-run T1/T4 for the final reports (Vivado hold by peer session)

## Phase 3: audio
- [x] plan written (review sub-agent hit a rate limit; self-reviewed)
- [x] extract, packetizer (embed), ACR, tone source, IEC 60958 status, docs (CSR/DMA sources deferred)
- [x] T1 tone round trip (lossless at 47964 frames/s) and T4 Magewell audio capture (999.3 Hz, 44 dB) on rpi5, 2026-09-07
- [ ] phase-3 code review by sub-agent (rate limit)

## Phase 4: pixel formats
- [x] colorimetry model (BT.601/709, full/limited), CSCMatrix, 4:2:2 wire cores, PixelFormatConverter, AVIFormatControl
- [x] transmitter (avi_config-driven) and receiver (AVI-latch-driven) integration, doc/pixel-formats.md
- [x] T1 wire-side frame CRC for 7 format settings matches the model (2026-09-07)
- [ ] sub-agent review; 4:2:2 chroma interpolation and XAPP930-style multiplier sharing as phase-7 candidates

## Phase 5: receiver integration
- [x] `HDMIReceiver` (period + island decoders, AVI capture, timing measure, audio extract FIFO), `doc/receiver.md`
- [x] `S7MMCMClocking`, `bench/netv2/hdmi_rx.py` (hdmi_in 1, 720p-preferring EDID), `run_rx.py` + on-Pi `align`
- [~] T3 on rpi5 against the Pi 5 HDMI-A-2 source at 65 MHz (build 2 running: build 1 failed timing on LiteX's MMCM reset CDC); then 74.25 MHz after EDID re-probe
- [ ] `HDMIIn`-style wrapper (frame buffer / DMA sink) and stream audio sink; receiver code review by sub-agent

## Phase 6: open-source flows
- [x] Yosys → Vivado for tx: timing clean, T4 pass on hardware (2026-09-07)
- [~] openXC7 for tx: snap nextpnr 0.8.2 rejects the OSERDES cascade -> built nextpnr-xilinx master locally (~/github/openXC7); snap prjxray-db lacks OSERDES DDR.W10 -> openXC7/prjxray-db master sparse clone; chipdb regenerated; bitstream build in progress; nextpnr timing says pix domain 68 MHz vs 74.25 needed (its model), to verify on hardware
- [ ] rx attempt on openXC7 (ISERDES from IDELAY, MMCM); fork fixes if needed; doc/toolchains.md

## Phase 7: optimisation and review
- [x] `scripts/resources.py` + `doc/resources.md` (per-core Yosys estimates, bench P&R numbers)
- [ ] sub-agent optimisation pass (candidates: serialised packet interface to shrink the 248-bit scheduler/encoder muxes; framer override muxes; constant-matrix DSP avoidance)
- [ ] sub-agent code reviews of phases 3-5

## Blocked on the user
- [!] T2 cabled loopback (needs HDMI cable on rpi5-netv2)
- [!] T3 on a second unit: rpi3-netv2 reserved by HDCP work (rpi5's Pi 5 output now serves as the source)
- [!] T4 real sink (MS2109 missing)
