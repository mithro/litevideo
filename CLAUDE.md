# LiteVideo HDMI work: notes branch

This orphan branch (`claude-notes`) holds only planning and progress material
for the HDMI upgrade of `mithro/litevideo`. Code lives on `hdmi-support` and
topic branches; `master` only ever fast-forwards to upstream
`enjoy-digital/litevideo`.

- `LOG.md`: dated progress log, newest entry first. Update and commit at every
  milestone and at least once per working session.
- `TODO.md`: the live task list with status.
- `docs/superpowers/specs/`: design documents.
- `docs/superpowers/plans/`: per-phase implementation plans.

## Working rules (from the user, 2026-09-06)

- Small logical commits on our own branches and worktrees (`.worktrees/`,
  excluded through `.git/info/exclude`); never disturb other checkouts.
- Never push to, open issues on, or PR against repositories outside the
  `mithro` GitHub user. Upstream is read-only.
- LiteX-style Migen; follow the patterns of the better maintained LiteX cores
  (LiteEth, LiteDRAM, `litex/soc/cores/video.py`).
- Everything is tested on real hardware (NeTV2 in the Welland lab). The rigs
  are shared: announce hardware sessions to the peer Claude sessions
  (ListAgents, names starting "netv2"), one volatile load at a time,
  `rpi3-netv2` is the golden unit (volatile loads only, and currently reserved
  by the HDCP work until the user releases it).
- Vivado first; once working, Yosys synthesis into Vivado, then openXC7.
  Every synthesis run goes through the cgroup wrapper (`scripts/limited.py`
  on the code branch) and Vivado runs one at a time.
- Sub-agents review each phase and look for resource savings.
- Important details link to the sources with the full information
  (spec sections, reports, code).
- Python through `uv`; no `python -c`, no heredocs, no `/tmp`, no
  `2>/dev/null` (hooks block them).
