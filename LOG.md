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
