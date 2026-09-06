# TODO

Status: `[ ]` open, `[~]` in progress, `[x]` done, `[!]` blocked (reason).

## Phase 0: scaffolding
- [x] Fast-forward fork to upstream and push
- [x] Worktrees and branches
- [x] Design spec written
- [~] Spec review by sub-agent
- [ ] `pyproject.toml` + uv environment pinned to LiteX 2026.04
- [ ] `test/` with the existing csc benches ported to pytest
- [ ] `.github/workflows/ci.yml`
- [ ] `scripts/limited.py` cgroup wrapper
- [ ] `doc/` skeleton and README update

## Phase 1: protocol layer
- [ ] `hdmi/common.py` constants with spec references
- [ ] `hdmi/bch.py` + vectors vs hdl-util
- [ ] `hdmi/model.py` golden model
- [ ] `hdmi/period.py` period decoder (+ DecodeTERC4 compat)
- [ ] island decoder, island encoder, tests, `doc/hdmi-protocol.md`

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
