# Phase 4: pixel formats and colour spaces — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> Steps use checkbox syntax for tracking.

**Goal:** LiteVideo streams can be converted between RGB, YCbCr 4:4:4 and
YCbCr 4:2:2 in the HDMI wire mapping, with BT.601/BT.709 colorimetry and
full/limited quantization ranges, selected statically or at run time from
the AVI InfoFrame; the transmitter emits the chosen format with a matching
AVI InfoFrame, the receiver converts what the AVI declares back to RGB.

**Architecture:** a pure-Python colorimetry module derives 3x3 fixed-point
matrices and offsets from (Kr, Kb) and the two ranges (ITU-R BT.601-7
§2.5.1/§2.5.3/§2.5.4, BT.709-6 Table 3 items 3.2–3.5, CEA-861-D §5 for
full-range RGB and the JFIF full-range YCbCr convention). One generic
gateware datapath (`CSCMatrix`) evaluates any such matrix with either
constant or run-time coefficients; a coefficient ROM indexed by
(colorimetry, ranges) gives the run-time selection. The 4:2:2 wire packing
follows HDMI 1.3 §6.5.1 Figure 6-2. `PixelFormatConverter` composes those
over `video_data_layout` with DE/HSYNC/VSYNC delayed in step. The existing
XAPP930 cores stay for the DMA paths (`output/__init__.py`, `input/analysis.py`).

**Tech stack:** Migen/LiteX (`LiteXModule`, `stream.Endpoint`, `video_data_layout`), pytest.

---

### Task 1: colorimetry model
- [ ] `litevideo/csc/colorimetry.py`: `Colorimetry(name, kr, kb)` with `BT601`, `BT709`; `Range` FULL/LIMITED (Y 0–255 / 16–235, C 0–255 / 16–240, scales 255/219 and 255/224); `rgb2ycbcr_matrix(col, rgb_range, ycc_range)` and `ycbcr2rgb_matrix(...)` returning (3x3 floats, offsets, clamp mins/maxs) in the 8-bit integer domain; `quantize(matrix, cw)`; `apply(matrix, pixel)` float reference with round-half-up and clamp.
- [ ] `test/test_csc_colorimetry.py`: known vectors (white/black/red/green/blue for BT.709 limited and BT.601 full), inverse matrices round trip within 1 LSB.
- [ ] commit.

### Task 2: `CSCMatrix` datapath
- [ ] `litevideo/csc/matrix.py`: `CSCMatrix(dw=8, cw=12, coefs=None)`; `coef` Record of 9 signed (cw+3)-bit coefficients and 3 offsets when `coefs` is None (run-time), constants otherwise; pipeline: register → 9 multiplies → sum + offset + rounding → shift + saturate; `latency = 4`; free-running with `ce`.
- [ ] `test/test_csc_matrix.py`: constant BT.709 and BT.601 conversions vs `apply()` over 2000 random pixels, max |diff| ≤ 1; run-time coefficient switching mid-stream.
- [ ] commit.

### Task 3: 4:2:2 wire packing
- [ ] `litevideo/csc/wire422.py`: `YCbCr444ToWire422` (average chroma of each pixel pair per CEA-861-D/BT.601 site convention: Cb/Cr of even pixel = mean of pair, or simple co-sited pick — use the mean, document), output `c2 = Cb|Cr alternating, c1 = Y, c0 = 0`; `Wire422ToYCbCr444` (hold last Cb/Cr, replicate); both keyed on a `first` (even pixel) tracked from DE rise.
- [ ] tests against a Python model of Figure 6-2 with DE gaps.
- [ ] commit.

### Task 4: `PixelFormatConverter`
- [ ] `litevideo/csc/convert.py`: `PixelFormat` enum RGB / YCBCR444 / YCBCR422 matching AVI `Y` codes 0/2/1; `PixelFormatConverter(dw=8, cw=12)` over `video_data_layout` with run-time `fmt_in, fmt_out, colorimetry, rgb_range, ycc_range` inputs: fixed structure `unpack422 → (matrix) → pack422` with bypass muxes and the ROM of matrices; DE/syncs delayed by the constant latency.
- [ ] `test/test_csc_convert.py`: all format pairs on a model frame vs the Python reference; identity pairs are exact.
- [ ] commit.

### Task 5: transmitter integration
- [ ] `HDMITransmitter`: `format` CSR (y, c, q, yq) driving a `PixelFormatConverter` (RGB in) before the framer and the AVI `y/c/q/yq` fields from the same register (`avi_config` fields become the source of truth: the converter reads them).
- [ ] `test_hdmi_transmitter.py`: YCbCr 4:4:4 and 4:2:2 output pixels decode (model) back to the RGB input within 1 LSB.
- [ ] loopback bench: `FrameCRC` on the receiver's converted RGB; commit.

### Task 6: receiver integration
- [ ] `HDMIReceiver`: `PixelFormatConverter` to RGB driven by the AVI latch (`y`, `c`, `q`, `yq`; default RGB when no AVI), `source` carries the converted pixels, `raw_source` the wire values.
- [ ] test: model frame in YCbCr 4:2:2 with AVI → RGB within 1 LSB.
- [ ] commit; `doc/pixel-formats.md`; T1 bench run with the format CSR cycling (frame CRC per format) when the rig is free.
