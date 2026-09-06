#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Colour space matrices for RGB <-> YCbCr with selectable colorimetry and
quantization ranges (pure Python: used to build gateware constants and as the
reference model in the tests).

Luma and colour-difference definitions (E' are the gamma-corrected analogue
signals, nominal range 0..1 for E'R/E'G/E'B/E'Y and -0.5..0.5 for E'CB/E'CR):

    E'Y  = Kr E'R + Kg E'G + Kb E'B          Kg = 1 - Kr - Kb
    E'CB = (E'B - E'Y) / (2 (1 - Kb))
    E'CR = (E'R - E'Y) / (2 (1 - Kr))

* ITU-R BT.601-7 §2.5.1: Kr = 0.299, Kb = 0.114 (E'CR = (E'R - E'Y)/1.402,
  E'CB = (E'B - E'Y)/1.772).
* ITU-R BT.709-6 Table 3 items 3.2 and 3.3: Kr = 0.2126, Kb = 0.0722
  (divisors 1.5748 and 1.8556).

Quantization to 8 bits ("limited" or "video" range, BT.601-7 §2.5.3 and
BT.709-6 item 3.4):

    Y = int(219 E'Y + 16)      CB = int(224 E'CB + 128)      CR = int(224 E'CR + 128)
    R = int(219 E'R + 16)      (same for G, B when RGB is limited range)

"Full" range uses the whole code space: R = 255 E'R, Y = 255 E'Y,
CB = 255 E'CB + 128 (CEA-861-D §5.1 "Full Range" for RGB; the JFIF/JPEG
convention for YCbCr, which CEA-861-E's AVI YQ field can signal). ``int``
rounds to nearest as in BT.601-7 §2.5.3; ties round up.

Because Kr + Kg + Kb = 1 the matrices below work on the integer codes
directly (BT.601-7 §2.5.4, BT.709-6 item 3.5): an RGB black offset cancels
in the colour-difference rows and only shifts the luma offset.
"""

from collections import namedtuple


class Colorimetry(namedtuple("Colorimetry", "name kr kb")):
    __slots__ = ()

    @property
    def kg(self):
        return 1.0 - self.kr - self.kb


BT601 = Colorimetry("BT.601", 0.299,  0.114)   # ITU-R BT.601-7 §2.5.1
BT709 = Colorimetry("BT.709", 0.2126, 0.0722)  # ITU-R BT.709-6 Table 3 item 3.2


# Quantization range: code = scale * E' + offset for the achromatic components
# (R, G, B, Y) and the colour-difference components (Cb, Cr).
Range = namedtuple("Range", "name ymin ymax yscale yoffset cmin cmax cscale coffset")

LIMITED = Range("limited", 16, 235, 219, 16, 16, 240, 224, 128)   # BT.601-7 §2.5.3, BT.709-6 item 3.4
FULL    = Range("full",     0, 255, 255,  0,  0, 255, 255, 128)   # CEA-861-D §5.1 (RGB), JFIF (YCbCr)


Matrix = namedtuple("Matrix", "m offsets mins maxs")
"""out[i] = sum_j m[i][j] * in[j] + offsets[i], then clamp to [mins[i], maxs[i]]."""


def rgb2ycbcr_matrix(col, rgb_range=FULL, ycc_range=LIMITED):
    """Integer-domain matrix taking (R, G, B) in ``rgb_range`` to (Y, Cb, Cr)
    in ``ycc_range`` (8-bit codes)."""
    kr, kg, kb = col.kr, col.kg, col.kb
    ys = ycc_range.yscale / rgb_range.yscale
    cb_s = ycc_range.cscale / (rgb_range.yscale * 2 * (1 - kb))
    cr_s = ycc_range.cscale / (rgb_range.yscale * 2 * (1 - kr))
    m = [
        [ys * kr,         ys * kg,       ys * kb],
        [-cb_s * kr,     -cb_s * kg,     cb_s * (1 - kb)],
        [ cr_s * (1 - kr), -cr_s * kg,  -cr_s * kb],
    ]
    # E'R = (R - rgb.yoffset)/rgb.yscale: the offset only survives in the luma row.
    offsets = [ycc_range.yoffset - ys * rgb_range.yoffset, ycc_range.coffset, ycc_range.coffset]
    return Matrix(m, offsets,
                  [ycc_range.ymin, ycc_range.cmin, ycc_range.cmin],
                  [ycc_range.ymax, ycc_range.cmax, ycc_range.cmax])


def ycbcr2rgb_matrix(col, ycc_range=LIMITED, rgb_range=FULL):
    """Integer-domain matrix taking (Y, Cb, Cr) in ``ycc_range`` to (R, G, B)
    in ``rgb_range``: E'R = E'Y + 2(1-Kr) E'CR, E'B = E'Y + 2(1-Kb) E'CB,
    E'G = E'Y - (Kr 2(1-Kr) E'CR + Kb 2(1-Kb) E'CB) / Kg."""
    kr, kg, kb = col.kr, col.kg, col.kb
    ys = rgb_range.yscale / ycc_range.yscale
    cs = rgb_range.yscale / ycc_range.cscale
    r_cr = cs * 2 * (1 - kr)
    b_cb = cs * 2 * (1 - kb)
    g_cb = -cs * 2 * (1 - kb) * kb / kg
    g_cr = -cs * 2 * (1 - kr) * kr / kg
    m = [
        [ys, 0.0,  r_cr],
        [ys, g_cb, g_cr],
        [ys, b_cb, 0.0],
    ]
    base = rgb_range.yoffset - ys * ycc_range.yoffset
    offsets = [base - r_cr * ycc_range.coffset,
               base - (g_cb + g_cr) * ycc_range.coffset,
               base - b_cb * ycc_range.coffset]
    return Matrix(m, offsets, [rgb_range.ymin] * 3, [rgb_range.ymax] * 3)


def identity_matrix(mins=(0, 0, 0), maxs=(255, 255, 255)):
    return Matrix([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]], [0, 0, 0], list(mins), list(maxs))


def apply(matrix, pixel):
    """Reference conversion of one pixel (tuple of 3 ints): round half up, clamp."""
    out = []
    for row, off, lo, hi in zip(matrix.m, matrix.offsets, matrix.mins, matrix.maxs):
        v = sum(c * p for c, p in zip(row, pixel)) + off
        v = int(v + 0.5) if v >= 0 else -int(-v + 0.5)
        out.append(min(hi, max(lo, v)))
    return tuple(out)


def quantize(matrix, cw):
    """Fixed-point version with ``cw`` fractional bits: integer coefficients
    and offsets (offsets are pre-scaled by 2**cw so the datapath adds them
    before the final shift)."""
    q = lambda v: int(round(v * 2**cw))
    return Matrix([[q(c) for c in row] for row in matrix.m],
                  [q(o) for o in matrix.offsets], list(matrix.mins), list(matrix.maxs))


def apply_quantized(qmatrix, cw, pixel):
    """Bit-exact model of ``CSCMatrix``: integer multiply-accumulate, add
    2**(cw-1) for rounding, arithmetic shift, clamp."""
    out = []
    for row, off, lo, hi in zip(qmatrix.m, qmatrix.offsets, qmatrix.mins, qmatrix.maxs):
        acc = sum(c * p for c, p in zip(row, pixel)) + off + (1 << (cw - 1))
        out.append(min(hi, max(lo, acc >> cw)))
    return tuple(out)
