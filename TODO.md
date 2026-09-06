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
- [~] `.github/workflows/ci.yml` (pushed, first run pending)
- [x] `scripts/limited.py` cgroup wrapper
- [x] `doc/` skeleton and README update

## Phase 1: protocol layer
- [x] `hdmi/common.py` constants with spec references
- [x] `hdmi/bch.py` + vectors vs hdl-util
- [x] `hdmi/model.py` golden model
- [x] `hdmi/period.py` period decoder (DecodeTERC4 compat wrapper deferred to phase 5)
- [~] island decoder, island encoder, tests, `doc/hdmi-protocol.md` (done; sub-agent review pending)

## Phase 2: transmitter
- [ ] framer, scheduler, InfoFrame generators, `HDMIOut`, S7 PHY hdmi mode
- [ ] `bench/netv2/hdmi_tx`, fabric loopback target, T1 run on rpi5

## Phase 3: audio
- [ ] extract, embed, ACR, sources (tone/CSR/DMA), IEC 60958 status, docs
- [ ] T1 tone round trip on rpi5

## Phase 4: pixel formats
- [ ] colorimetry/range parameterisation, converter, AVI-driven rx path, docs

## Phase 5: receiver integration
- [ ] `HDMIIn` sources, InfoFrame capture, `hdmi_rx` target

## Phase 6: open-source flows
- [ ] Yosys → Vivado for tx
- [ ] openXC7 for tx; rx attempt with measured blockers; fork fixes

## Phase 7: optimisation and review
- [ ] resource tables per core and part, sub-agent optimisation pass

## Blocked on the user
- [!] T2 cabled loopback (needs HDMI cable on rpi5-netv2)
- [!] T3 real source (rpi3-netv2 reserved by HDCP work)
- [!] T4 real sink (MS2109 missing)
