# Pixel formats and colour spaces

`litevideo/csc/` gained a parameterised colour pipeline for the HDMI
transmitter and receiver. The older XAPP930-style cores
(`rgb2ycbcr.py`, `ycbcr2rgb.py`, `ycbcr444to422.py`, `ycbcr422to444.py`)
still serve the DMA paths in `output/__init__.py` and `input/analysis.py`;
their coefficient set (ca = 0.1819, cb = 0.0618, cc = 0.5512, cd = 0.6495) is
neither a full-range nor a limited-range BT.709 conversion, so the new code
derives everything from the standards instead.

## Colorimetry model (`csc/colorimetry.py`)

Pure Python, used both to build gateware constants and as the test
reference. From the luma coefficients (Kr, Kb):

    E'Y  = Kr E'R + Kg E'G + Kb E'B        Kg = 1 - Kr - Kb
    E'CB = (E'B - E'Y) / (2 (1 - Kb))       E'CR = (E'R - E'Y) / (2 (1 - Kr))

| Colorimetry | Kr | Kb | Source |
|---|---|---|---|
| BT.601 | 0.299 | 0.114 | ITU-R BT.601-7 §2.5.1 (E'CR = (E'R − E'Y)/1.402, E'CB = (E'B − E'Y)/1.772) |
| BT.709 | 0.2126 | 0.0722 | ITU-R BT.709-6 Table 3 items 3.2, 3.3 (divisors 1.5748, 1.8556) |

Quantization to 8 bits:

| Range | R, G, B, Y | Cb, Cr | Source |
|---|---|---|---|
| limited | 219 E' + 16 (16..235) | 224 E'C + 128 (16..240) | BT.601-7 §2.5.3, BT.709-6 item 3.4 |
| full | 255 E' (0..255) | 255 E'C + 128 (0..255, clamped) | CEA-861-D §5.1 (RGB); JFIF convention for YCbCr, signalled by CEA-861-E's AVI YQ |

Because Kr + Kg + Kb = 1 the matrices act on the integer codes directly
(BT.601-7 §2.5.4, BT.709-6 item 3.5): a limited-range RGB input only shifts
the luma offset. `rgb2ycbcr_matrix`, `ycbcr2rgb_matrix` and
`rgb_range_matrix` return 3x3 float matrices with offsets and clamp
limits; `quantize(matrix, cw)` makes the fixed-point version and
`apply_quantized` is the bit-exact model of the gateware. With 12
fractional bits the fixed-point result is within one code of the float
model (`test/test_csc_colorimetry.py`), and hand-computed vectors from the
standards are checked (BT.709 full RGB red → (63, 102, 240); white → (235,
128, 128); BT.601 full→full equals the JFIF equations).

## Gateware

* `CSCMatrix` (`csc/matrix.py`): generic 3x3 fixed-point matrix, four
  pipeline stages (register, nine signed multiplies, sum + offset +
  rounding, shift + saturate), `cw` = 12 fractional bits, coefficients
  either constants (`matrix=`) or run-time inputs. With `dw = 8` each
  multiply is 9 x 15 bits, one DSP48E1 on 7-series when the coefficients
  are signals; constants fold into LUTs.
* `YCbCr444ToWire422` / `Wire422ToYCbCr444` (`csc/wire422.py`): the HDMI
  4:2:2 wire mapping (HDMI 1.3 §6.5.1 Figure 6-2: Cb then Cr on channel 2,
  Y on channel 1, low nibbles on channel 0, zero for 8-bit components).
  Pairs are averaged going out and replicated coming in; parity restarts at
  every DE rise. Latency 2 each.
* `PixelFormatConverter` (`csc/convert.py`): fixed pipeline `unpack → matrix
  → pack` (latency 8) over `video_data_layout`, in the wire channel order
  (`r` = channel 2, `g` = channel 1, `b` = channel 0), with run-time
  controls coded like the AVI InfoFrame: `fmt_in`/`fmt_out` (`PixelFormat`
  RGB 0, YCbCr 4:2:2 1, 4:4:4 2), `colorimetry` (1 BT.601, 2 BT.709), the
  RGB range on each side and the YCC range. A 64-entry constant table
  selects the matrix (identity, RGB→YCC, YCC→RGB, RGB range rescale ×
  colorimetry × ranges). Controls are quasi-static: change them in blanking.
* `AVIFormatControl`: AVI fields to those controls, applying the CEA-861-D
  defaults: C = 0 means BT.601 for the SD formats (VIC 1–15 and 17–30 minus
  the 720p/1080i codes 4, 5, 19, 20) and BT.709 otherwise (CEA-861-D §6.4
  Table 9 note); Q = 0 means limited-range RGB for CE formats except VIC 1
  (640x480p), which is full range (CEA-861-D §5.1, HDMI 1.3 §6.6); YQ = 1 is
  full-range YCC (CEA-861-E); Y = 3 is reserved and treated as RGB.

## Transmitter and receiver

`HDMITransmitter` puts a converter in front of the framer and derives its
controls from `avi_config`/`avi_config2` through `AVIFormatControl`, so the
InfoFrame and the pixels always agree. The sink is full-range RGB by default
(`input_format`, `input_rgb_limited` say otherwise). `avi_config.q` resets to
2 (full range) so the default output is the input untouched; `dvi_mode`
forces full-range RGB. `HDMIReceiver.raw_source` carries the wire values and
`source` the conversion to full-range RGB from the latched AVI (RGB full
assumed until an InfoFrame arrives; `control.convert` = 0 bypasses).

## Testing

* `test/test_csc_colorimetry.py`, `test_csc_matrix.py`, `test_csc_wire422.py`,
  `test_csc_convert.py`: models and gateware, bit-exact.
* `test/test_hdmi_transmitter.py::test_output_formats`, `test/test_hdmi_receiver.py::test_convert_back_to_rgb`:
  end-to-end through the HDMI encoders and decoders.
* Hardware: `bench/netv2/host/run_loopback.py` cycles `avi_config` through the
  formats and compares the wire-side frame CRC of the colour bars with the
  model (`doc/reports/`).
