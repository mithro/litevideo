#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure-Python golden model of the HDMI link layer.

Everything the gateware does is modelled here first, at the level of 10-bit
TMDS characters, so simulations can compare bit for bit:

* ``tmds_encode`` / ``tmds_decode``: DVI 1.0 §3.2.2 / §3.3 (8b/10b with
  running disparity ``cnt``).
* ``terc4_encode`` / ``terc4_decode``: HDMI 1.3 §5.4.3.
* ``Packet``: header + four subpackets with their BCH ECC (§5.2.3.4, §5.2.3.5).
* ``packet_chars``: the 32 per-character (header bit, ch1 nibble, ch2 nibble)
  triples of one packet (§5.2.3.4 Figure 5-4).
* ``island_tokens``: preamble, guard bands and packets of one data island as
  ``(c0, c1, c2)`` tuples (§5.2.3, Tables 5-2 and 5-6, channel 0 bit 3 per
  the HDMI 1.4b CTS: 0 on the first island character, 1 elsewhere).
* ``line_tokens``: a whole video line with control periods, an optional
  island, the video preamble and guard band, and TMDS-encoded pixels,
  together with the expected ``Period`` per character.
"""

from litevideo.hdmi.common import *
from litevideo.hdmi.bch import bch_ecc

# TMDS 8b/10b ------------------------------------------------------------------------------------

def _ones(v, n=8):
    return bin(v & ((1 << n) - 1)).count("1")


def tmds_encode(d, c, de, cnt):
    """DVI 1.0 §3.2.2 Figure 3-5. Returns (10-bit token, new running disparity)."""
    if not de:
        return control_tokens[c & 3], 0
    n1 = _ones(d)
    q_m = [d & 1]
    if n1 > 4 or (n1 == 4 and (d & 1) == 0):
        for i in range(1, 8):
            q_m.append(q_m[i - 1] ^ ((d >> i) & 1) ^ 1)
        q_m.append(0)
    else:
        for i in range(1, 8):
            q_m.append(q_m[i - 1] ^ ((d >> i) & 1))
        q_m.append(1)
    qm = sum(b << i for i, b in enumerate(q_m))
    n1q = _ones(qm)
    n0q = 8 - n1q
    if cnt == 0 or n1q == n0q:
        q9 = 1 - q_m[8]
        q8 = q_m[8]
        low = qm & 0xFF if q_m[8] else (~qm) & 0xFF
        cnt = cnt + (n1q - n0q) if q_m[8] else cnt + (n0q - n1q)
    elif (cnt > 0 and n1q > n0q) or (cnt < 0 and n0q > n1q):
        q9 = 1
        q8 = q_m[8]
        low = (~qm) & 0xFF
        cnt = cnt + 2 * q_m[8] + (n0q - n1q)
    else:
        q9 = 0
        q8 = q_m[8]
        low = qm & 0xFF
        cnt = cnt - 2 * (1 - q_m[8]) + (n1q - n0q)
    return low | (q8 << 8) | (q9 << 9), cnt


def tmds_decode(token):
    """DVI 1.0 §3.3 Figure 3-6. Returns (d, c, de)."""
    if token in control_tokens:
        return 0, control_tokens.index(token), 0
    low = token & 0xFF
    if token & (1 << 9):
        low = (~low) & 0xFF
    d = low & 1
    for i in range(1, 8):
        bit = (low >> i) & 1
        prev = (low >> (i - 1)) & 1
        if token & (1 << 8):
            d |= (bit ^ prev) << i
        else:
            d |= (bit ^ prev ^ 1) << i
    return d, 0, 1


# TERC4 ------------------------------------------------------------------------------------------

def terc4_encode(nibble):
    return terc4_tokens[nibble & 0xF]


def terc4_decode(token):
    """4-bit word, or None if ``token`` is not a TERC4 character."""
    try:
        return terc4_tokens.index(token)
    except ValueError:
        return None


# Packets ----------------------------------------------------------------------------------------

class Packet:
    """One data island packet: 3 header bytes and 4 subpackets of 7 bytes."""

    def __init__(self, header_bytes, subpacket_bytes):
        assert len(header_bytes) == 3
        assert len(subpacket_bytes) == 4 and all(len(s) == 7 for s in subpacket_bytes)
        self.header_bytes = list(header_bytes)
        self.subpacket_bytes = [list(s) for s in subpacket_bytes]

    @classmethod
    def null(cls):
        return cls([0, 0, 0], [[0] * 7 for _ in range(4)])

    @classmethod
    def from_words(cls, header, subpackets):
        hb = [(header >> (8 * i)) & 0xFF for i in range(3)]
        sb = [[(s >> (8 * i)) & 0xFF for i in range(7)] for s in subpackets]
        return cls(hb, sb)

    @property
    def type(self):
        return self.header_bytes[0]

    @property
    def header(self):
        return sum(b << (8 * i) for i, b in enumerate(self.header_bytes))

    @property
    def header_ecc(self):
        return bch_ecc(self.header_bytes)

    @property
    def subpackets(self):
        return [sum(b << (8 * i) for i, b in enumerate(s)) for s in self.subpacket_bytes]

    @property
    def subpacket_ecc(self):
        return [bch_ecc(s) for s in self.subpacket_bytes]

    def __eq__(self, other):
        return (isinstance(other, Packet) and self.header_bytes == other.header_bytes
                and self.subpacket_bytes == other.subpacket_bytes)

    def __repr__(self):
        return f"Packet({[hex(b) for b in self.header_bytes]}, {self.subpacket_bytes})"


def packet_chars(packet, corrupt_header_ecc=False, corrupt_subpacket_ecc=None):
    """32 (header_bit, ch1 nibble, ch2 nibble) triples of one packet."""
    hecc = packet.header_ecc ^ (0x01 if corrupt_header_ecc else 0)
    header = packet.header | (hecc << 24)
    subs = []
    for k, (data, ecc) in enumerate(zip(packet.subpackets, packet.subpacket_ecc)):
        if corrupt_subpacket_ecc == k:
            ecc ^= 0x01
        subs.append(data | (ecc << 56))
    chars = []
    for c in range(PACKET_LENGTH):
        hbit = (header >> c) & 1
        n1 = 0
        n2 = 0
        for k in range(4):
            n1 |= ((subs[k] >> (2 * c)) & 1) << k
            n2 |= ((subs[k] >> (2 * c + 1)) & 1) << k
        chars.append((hbit, n1, n2))
    return chars


# Islands and lines ------------------------------------------------------------------------------

def control_chars(hsync, vsync, ctl=(0, 0)):
    """(c0, c1, c2) of one control character; ``ctl`` = (ch1 {D1,D0}, ch2 {D1,D0})."""
    return (control_tokens[(vsync << 1) | hsync], control_tokens[ctl[0]], control_tokens[ctl[1]])


def island_tokens(packets, hsync=0, vsync=0, **corrupt):
    """Preamble + leading guard band + packets + trailing guard band."""
    assert 1 <= len(packets) <= MAX_PACKETS_PER_ISLAND
    gb0 = terc4_encode(data_gb_ch0_nibble(hsync, vsync))
    toks = [control_chars(hsync, vsync, PREAMBLE_DATA)] * PREAMBLE_LENGTH
    toks += [(gb0, data_gb_token, data_gb_token)] * GUARD_BAND_LENGTH
    first = True
    for p in packets:
        for hbit, n1, n2 in packet_chars(p, **corrupt):
            n0 = ((0 if first else 1) << 3) | (hbit << 2) | (vsync << 1) | hsync
            first = False
            toks.append((terc4_encode(n0), terc4_encode(n1), terc4_encode(n2)))
    toks += [(gb0, data_gb_token, data_gb_token)] * GUARD_BAND_LENGTH
    return toks


def video_tokens(pixels, disparity=None):
    """TMDS-encode ``pixels`` (list of (r, g, b)); channel 0 = b, 1 = g, 2 = r."""
    cnt = disparity or [0, 0, 0]
    toks = []
    for r, g, b in pixels:
        c0, cnt[0] = tmds_encode(b, 0, 1, cnt[0])
        c1, cnt[1] = tmds_encode(g, 0, 1, cnt[1])
        c2, cnt[2] = tmds_encode(r, 0, 1, cnt[2])
        toks.append((c0, c1, c2))
    return toks


def line_tokens(hactive, hblank, packets=(), hsync_start=None, hsync_len=None, vsync=0, pixels=None):
    """One line: active video, then blanking with an optional island, then the
    video preamble and guard band. Returns (tokens, expected periods)."""
    hsync_start = hactive + 4 if hsync_start is None else hactive + hsync_start
    hsync_len = 8 if hsync_len is None else hsync_len
    if pixels is None:
        pixels = [((i * 7) & 0xFF, (i * 13) & 0xFF, (i * 29) & 0xFF) for i in range(hactive)]
    toks = video_tokens(pixels)
    periods = [Period.VIDEO] * hactive

    def hs(x):
        return 1 if hsync_start <= x < hsync_start + hsync_len else 0

    x = hactive
    tail = PREAMBLE_LENGTH + GUARD_BAND_LENGTH
    island = island_tokens(list(packets), hsync=hs(x + MIN_CONTROL_PERIOD), vsync=vsync) if packets else []
    # control, island, control (>= 4), video preamble, video guard band
    n_ctrl_before = MIN_CONTROL_PERIOD
    n_ctrl_after = hblank - n_ctrl_before - len(island) - tail
    assert n_ctrl_after >= MIN_ISLAND_TO_PREAMBLE, "blanking too short for this island"
    for _ in range(n_ctrl_before):
        toks.append(control_chars(hs(x), vsync)); periods.append(Period.CONTROL); x += 1
    for i, t in enumerate(island):
        toks.append(t)
        if i < PREAMBLE_LENGTH:
            periods.append(Period.DATA_PREAMBLE)
        elif i < PREAMBLE_LENGTH + GUARD_BAND_LENGTH:
            periods.append(Period.DATA_LEADING_GUARD)
        elif i >= len(island) - GUARD_BAND_LENGTH:
            periods.append(Period.DATA_TRAILING_GUARD)
        else:
            periods.append(Period.DATA_ISLAND)
        x += 1
    for _ in range(n_ctrl_after):
        toks.append(control_chars(hs(x), vsync)); periods.append(Period.CONTROL); x += 1
    for _ in range(PREAMBLE_LENGTH):
        toks.append(control_chars(hs(x), vsync, PREAMBLE_VIDEO)); periods.append(Period.VIDEO_PREAMBLE); x += 1
    for _ in range(GUARD_BAND_LENGTH):
        toks.append(tuple(video_gb_tokens)); periods.append(Period.VIDEO_GUARD); x += 1
    return toks, periods
