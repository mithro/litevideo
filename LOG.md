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

### Needs the user

1. Plug an HDMI cable from `hdmi_out` 0 to `hdmi_in` 0 on `rpi5-netv2`
   (enables tier T2: real TMDS loopback).
2. Say when `rpi3-netv2` may be used again after the HDCP handshake work
   (tier T3: real source), and reconnect the MS2109 capture card to its
   `hdmi_out` 0 (tier T4: real sink with audio capture).
3. Tell the netv2-fpga session about the ECC polynomial finding (or confirm I
   should message it).
