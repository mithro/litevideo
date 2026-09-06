# Progress log

Newest first. Dates are ISO 8601, times are Adelaide local (ACST, UTC+9:30).

## 2026-09-06

- **Survey.** Fork `mithro/litevideo` was 149 commits behind upstream with
  nothing local; fast-forwarded `master` to `41f3014` and pushed. Read the
  whole tree (5,511 lines), LiteX 2026.04 `soc/cores/video.py`, the
  netv2-fpga `modern` branch's HDMI audio work and reports, the fpgas.online
  NeTV2 hardware docs and the netv2-testsuite notes.
- **Hardware state.** `rpi5-netv2` (XC7A100T) is free for announced one-at-a-
  time volatile loads but has no HDMI cable. `rpi3-netv2` (golden XC7A35T) is
  reserved by the HDCP session until the user releases it; its MS2109 capture
  card is absent from `lsusb`. Both peer sessions replied and agreed the plan.
- **Finding.** The netv2-fpga audio cores use ECC polynomial
  x⁸+x⁷+x⁶+x⁴+1 (mask 0x8B); HDMI 1.3 §5.2.3.5 says G(x)=1+x⁶+x⁷+x⁸ and
  hdl-util/hdmi uses the matching mask 0x83. Their round trip passes because
  both ends agree, but real sinks/sources would not. LiteVideo follows the
  specification; hardware confirmation with a real source is planned.
- **Setup.** Worktrees `.worktrees/notes` (orphan branch `claude-notes`) and
  `.worktrees/hdmi` (branch `hdmi-support`). Memory notes saved for the rig
  topology and machine conventions. Spec references downloaded and section
  numbers extracted (HDMI 1.3, CEA-861-D, DVI 1.0).
- **Design.** Wrote `docs/superpowers/specs/2026-09-06-litevideo-hdmi-design.md`
  (architecture, decisions D1 to D12, phases 0 to 7, hardware tiers T0 to T4,
  references). Sent for sub-agent review.

- **Spec approved** after two sub-agent review rounds (v3). Phase 0+1 plan
  written (`docs/superpowers/plans/2026-09-06-phase0-1-scaffolding-and-protocol-layer.md`).
- **Hardware update (afternoon).** The user connected a Magewell
  XI100DUSB-HDMI capture (video `/dev/video0`, ALSA card `XI100DUSBHDMI`) to
  `rpi5-netv2` with the NeTV2 `hdmi_out` 0 cabled into it. Tier T4 (real
  sink with audio capture) is therefore available on rpi5 from phase 2.
- **Third finding.** HDMI §5.2.3.3: channel 0 carries TERC4(1,1,VSYNC,HSYNC)
  during data island guard bands; the netv2-fpga encoder sends the channel
  1/2 guard token on all channels. Also confirmed from the HDMI 1.4b CTS
  wording: channel 0 bit 3 is 0 on the first island character and 1 on all
  other packet characters.

### Needs the user

1. Plug an HDMI cable into `hdmi_in` 0 on `rpi5-netv2` from a source (or
   from `hdmi_out` 1) to enable receiver tests there (tier T2/T3 style).
2. Say when `rpi3-netv2` may be used again after the HDCP handshake work
   (tier T3: real source `rpiz-3` into the receiver).
3. Decide whether I should tell the netv2-fpga session about the three
   spec divergences (ECC polynomial, ASP subpacket layout, channel 0 guard
   band) or whether you will.
- **Peer observation (afternoon).** With the netv2-fpga fabric-loopback
  bitstream driving 720p on `hdmi_out` 0, the Magewell stays at its no-signal
  default: the physical output path (OSERDES, pads, cable, sink) is
  unverified by that tree. To check in phase 2: which connector is cabled,
  `Inverted()` handling on the `hdmi_out` 0 clock pair, clock-lane pattern,
  OSERDES reset/OCE sequencing, and TMDS signal integrity. rpi5 PCIe FPC is
  not connected (LTSSM stuck in Detect), which does not affect this work.

## 2026-09-06 (afternoon, phases 0 and 1)

- Plan for phases 0+1 approved after two review rounds; the reviewer executed
  every code block of the plan against the pinned environment.
- `hdmi-support` now holds 14 commits: `pyproject.toml` + `uv.lock` pinned to
  LiteX 2026.04 (setup.py removed), `test/` with stream helpers and the ported
  colour-space and output-core benches, `scripts/limited.py` (verified: runs
  the command in a transient `run-*.scope`), GitHub Actions CI, `doc/`
  skeleton, and the protocol layer `litevideo/hdmi/` (constants, BCH ECC,
  Python golden model, TMDS character decoder, period decoder, data island
  decoder and encoder) with 36 passing tests including an all-gateware
  encoder -> period decoder -> island decoder round trip.
- Fixes to existing code: LiteDRAM 2026.04 port attribute names, `phy_layout("raw")`
  `c2` width 11 -> 10 (upstream typo), Pillow `ANTIALIAS` -> `LANCZOS`.
- Sub-agent code review of the protocol layer dispatched; CI run pending.
- **Phase 1 code review** (sub-agent, with probing simulations) found two
  high-severity issues, both fixed: the period decoder left the video guard
  band on a value mismatch, so pixels equal to the guard band characters
  (B,G,R = 0xAB,0x55,0xAB) were swallowed; the island encoder allowed only 9
  control characters between islands (tS,min is 12). Also fixed: syncs
  latched instead of live inside islands (encoder) and reported one
  character late (decoder), inconsistent `sink.valid` handling, unclamped
  `max_packets`, missing island counter. Ten edge-case tests added; the TMDS
  model is now cross-checked against LiteX TMDSEncoder gateware. 46 tests pass.
- Phase 2 (transmitter) plan written and sent for review.

## 2026-09-06 (evening, phase 2)

- Phase 2 plan approved after two review rounds (the reviewer executed the
  plan code; its fixes: 11-stage delay line, ECP flag handoff, passive packet
  inserter, SoC argument overrides, build paths, FrameCRC interface).
- Landed on `hdmi-support`: model InfoFrame/GCP/frame generators, packet
  scheduler, AVI InfoFrame and GCP generators, `HDMIFramer` (HSYNC-anchored
  island placement, measured `hs2de`, Extended Control Period line),
  `HDMITransmitter` with CSRs, `bench/netv2/` (CPU-less uartbone SoC,
  CEA 720p colour-bar transmitter, fabric loopback with period histogram and
  frame CRC, host CSR client, rig helpers, tier T1/T4 scripts),
  `doc/transmitter.md`. 63 tests pass; both bench targets elaborate
  (S7MMCM: VCO 742.19 MHz, pix 74.22 MHz, pix5x 371.09 MHz).
- First Vivado build (loopback bench) started under `scripts/limited.py`,
  announced to the peer sessions.

## 2026-09-07 (early morning)

- **First hardware results.** Loopback bench built with Vivado (LUT 1433,
  FF 2940, 8 OSERDESE2, 1 MMCM + 1 PLL). First build had a duplicated clock
  constraint (WNS -1.9 ns artefact); second build showed the real issue:
  upstream litevideo registers the OSERDES OCE in the pix domain, a 2.7 ns
  crossing to eight IO tiles (WNS -1.26 ns). Fixed by tying OCE high (LiteX
  pattern); rebuild pending the peer session's Vivado hold. Since OCE is static
  after reset, the second bitstream (SHA a06b96b4) was used for preliminary runs.
- **Tier T1 on rpi5-netv2: all 13 checks pass** (60.1 fps, hs2de 260 with
  6 packets per island, AVI InfoFrame every frame with good ECC, GCP added
  under AVMUTE, DVI mode stops islands, frame CRC 0x5757aec7 identical at
  the transmitter, the fabric receiver and the Python reference).
- **Tier T4 on rpi5-netv2: the Magewell locks** to hdmi_out 0, captures the
  colour bars pixel-accurately in HDMI and DVI mode, and blanks on GCP
  Set_AVMUTE: a commercial sink parses LiteVideo's data islands (ECC
  polynomial 0x83, channel-0 guard band TERC4(1,1,V,H)). Reports:
  `doc/reports/2026-09-07-netv2-{loopback,tx}-prelim.md` + captures.
- Coordination: loads announced in `/home/tim/netv2-rpi5-coord/LITEVIDEO-LOAD.md`
  (the ten64 session `rpi-hdcp-output-c1` owns the rig for HDCP tests) and
  to the two desktop sessions using the board. Rig cabling per its RIG.md:
  hdmi_out 0 -> Magewell, Pi 5 HDMI-A-2 -> hdmi_in 1, dormant Pi Zero -> hdmi_in 0.
- Phase 3 plan written; its review sub-agent hit an API rate limit, so the
  implementation proceeds with self-review and a later review pass.
- **Phase 3 audio landed in simulation** (`litevideo/hdmi/audio/`: constants +
  IEC 60958 channel status, packet model, `AudioSamplePacketizer`,
  `ACRGenerator` (constant and measured CTS), `AudioInfoFrameGenerator`,
  `AudioExtract`, `ToneGenerator`; `HDMITransmitter(with_audio=True)`).
  Full round trip tone -> packets -> islands -> decoders -> samples is
  bit-exact; 80 tests pass. Bench: tone + ACR + Audio InfoFrame in the tx
  bench, extract FIFO + checks in the loopback, Magewell ALSA FFT check.
  `doc/audio.md` written. Vivado build of the audio bench stopped at the
  peer session's request (their user-prioritised route was being OOM-killed);
  to rerun when they release Vivado. Observation: after TaskStop killed the
  build wrapper, a Vivado child was found outside the systemd scope; the
  wrapper itself verifies fine, so check `/proc/<pid>/cgroup` after launch.

## 2026-09-07 (01:30 ACST)

- **Phase 5 receiver in simulation.** `litevideo/hdmi/receiver.py`:
  `HDMIReceiver` = period decoder + island decoder + AVI latch +
  `TimingMeasure` + `AudioExtract` with a 512-deep `AsyncFIFO` into `sys`
  drained over CSRs; `test/test_hdmi_receiver.py`; 81 tests pass.
- `litevideo/input/clocking.py` gains `S7MMCMClocking` (LiteX `S7MMCM`,
  any input rate as one parameter, honours `Inverted()` pads). Receiver bench
  `bench/netv2/hdmi_rx.py` on hdmi_in 1 with the Pi 5's HDMI-A-2 as the
  source (EDID-less 1024x768 at 65 MHz today; the bench EDID prefers 720p60 so
  a re-probe should move it to 74.25 MHz). Elaborates: VCO 1300 MHz, pix /20,
  pix1p25x /16, pix5x /4.
- Host side: `uartbone.py align` runs the HDMI2USB `calibrate_delays` /
  `adjust_phase` loop on the Pi itself (per-register ssh would take minutes);
  `run_rx.py` = lock, align, timing, fps, histogram, AVI, ACR checks.
  `doc/receiver.md` written; T3 tier redefined onto hdmi_in 1.
- Still holding Vivado at the HDCP session's request (their route was being
  OOM-killed); two builds queued: audio loopback (phase 3 hardware) and rx 65 MHz.
- Peer `crazy-fpga-usb2-40` loaded a volatile USB link-test bitstream on
  rpi5-netv2 (HDMI pins untouched, ~1 minute); no conflict with our idle state.

## 2026-09-07 (02:45 ACST)

- Vivado released by the HDCP session (their 100T route OOM-killed 5 times at
  the box's swap ceiling; they have handed the swap question to Tim).
- **Phase 3 on hardware.** Audio loopback bench (bitstream fb6384d9, then
  d9c7c3cd): ACR N=6144/CTS=74250 at 1000/s, Audio InfoFrame, 47964 audio
  frames/s in and 2x subframes out with zero overruns/drops over 8-11 s, tone
  recovered from the fabric receiver, and the Magewell captures the 1 kHz tone
  on both channels 44 dB above the next line (+-33 Hz resampling sidebands from
  the 74.219 MHz MMCM clock). Two script fixes on the way: the overrun counter
  accumulates while DVI mode stops islands (measure over a window), and a
  free-running overflowing FIFO is not a contiguous stream after the first drain
  -> `AudioSampleCapture` one-shot armed capture (also in `HDMIReceiver`).
- **Phase 4 done in simulation and on T1.** `csc/colorimetry.py` derives
  matrices from Kr/Kb and the ranges (BT.601-7 §2.5.x and BT.709-6 Table 3
  verified from the ITU PDFs with pdftotext), `CSCMatrix`, `wire422.py`
  (Figure 6-2), `PixelFormatConverter` (latency 8, 64-entry table),
  `AVIFormatControl` (CEA-861-D defaults incl. VIC 1 full range and the SD/HD
  colorimetry split). Transmitter converts per `avi_config` (q now resets to
  full range so the default output is unchanged), receiver converts back per
  the latched AVI (`raw_source` keeps wire values). On hardware all seven
  format settings give the model's wire-side frame CRC. 12 DSP48 for the
  run-time matrix in the tx bench (rx converter trimmed in the rx bench until
  its source was used).
- Receiver bench build 1: WNS -5.54 ns on LiteX's MMCM reset synchroniser
  (sys CSR -> BUFR input clock domain): false path added, build 2 running.
- 107 tests pass; `hdmi-support` pushed.
- Peer `crazy-fpga-usb2-40` briefly rewrote my mailbox rows by mistake and
  restored them; verified.

## 2026-09-07 (04:30 ACST)

- **T3 receiver on hardware**: after cycling the Pi's DRM connector the Pi
  reads the bench EDID and outputs 1280x720 HDMI; the receiver measures
  1280x720/1650x749 (vtotal off-by-one fixed in code, rebuild pending), 60 fps,
  islands with 0 ECC errors, ACR 6144/74250, Audio InfoFrame, and the Pi's
  aplay 1 kHz tone is captured on both channels. Report
  `doc/reports/2026-09-07-netv2-rx-720p.md`. Earlier at 65 MHz DVI: 1024x768 /
  1344x806 exact, stable frame CRC.
- **Phase 6**: Yosys+Vivado tx bench passes T4 (bars + audio). openXC7: the
  snap's nextpnr 0.8.2 lacks OSERDESE2 master/slave support; built
  openXC7/nextpnr-xilinx master in ~/github/openXC7 (cmake, BUILD_PYTHON=OFF,
  system python) and regenerated the xc7a100tfgg484 chipdb (5 min). The
  snap's prjxray-db lacks OSERDES DDR.W10; openXC7/prjxray-db master has it
  (sparse clone, artix7). fasm2frames with the pure-Python fasm parser is
  slow (>10 min). nextpnr's timing model reports the pix domain at 68 MHz
  (74.25 needed); hardware will tell.
- **Phase 7 started**: `scripts/resources.py` (Yosys per-core table) and
  `doc/resources.md`. Scheduler is ~3 LUT/bit for a 5:1 mux of 248 bits (a
  one-hot rewrite measured the same, reverted); serialising the packet
  interface is the real saving.
- Sub-agents still unavailable (rate limit); reviews deferred.
