#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Python model of the HDMI audio packets.

* Audio Sample Packet (HDMI 1.3 §5.3.4, Tables 5-12/5-13): HB1[3:0] =
  sample_present (contiguous from subpacket 0, Table 7-7), HB1[4] = layout,
  HB2[3:0] = sample_flat, HB2[7:4] = B (block start per subpacket);
  subpacket = SB0..SB2 left sample (IEC 60958 time slots 4..27, LSB first),
  SB3..SB5 right sample, SB6 = PR CR UR VR PL CL UL VL.
* Parity P: even parity over time slots 4..31 of the subframe, i.e. the
  24 sample bits, V, U, C and P together have an even number of ones.
* Audio Clock Regeneration (§5.3.3, Table 5-11): SB1[3:0] = CTS[19:16],
  SB2 = CTS[15:8], SB3 = CTS[7:0], SB4[3:0] = N[19:16], SB5, SB6; four
  identical subpackets.
* Audio InfoFrame (CEA-861-D §6.6, Tables 16 to 22): 10 data bytes.
"""

from litevideo.hdmi.common import PacketType
from litevideo.hdmi.model import Packet, infoframe_packet
from litevideo.hdmi.audio.common import *


def parity(sample, v=0, u=0, c=0):
    """P bit: even parity over the 24 sample bits and V, U, C."""
    ones = bin(sample & 0xFFFFFF).count("1") + (v & 1) + (u & 1) + (c & 1)
    return ones & 1


def asp_subpacket(left, right, cl, cr, vl=0, vr=0, ul=0, ur=0):
    """7 bytes of one Audio Sample Subpacket (Table 5-13)."""
    pl = parity(left, vl, ul, cl)
    pr = parity(right, vr, ur, cr)
    sb6 = (pr << 7) | (cr << 6) | (ur << 5) | (vr << 4) | (pl << 3) | (cl << 2) | (ul << 1) | vl
    return [left & 0xFF, (left >> 8) & 0xFF, (left >> 16) & 0xFF,
            right & 0xFF, (right >> 8) & 0xFF, (right >> 16) & 0xFF, sb6]


def asp_packet(frames, block_index=0, fs=48000, sample_flat=0, layout=0):
    """Audio Sample Packet for 1 to 4 (left, right) frames starting at
    IEC 60958 block position ``block_index``. Returns (Packet, next_block_index)."""
    assert 1 <= len(frames) <= 4
    status_l = channel_status_block(fs, IEC_CHANNEL_LEFT)
    status_r = channel_status_block(fs, IEC_CHANNEL_RIGHT)
    subs = []
    b = 0
    idx = block_index
    for k, (left, right) in enumerate(frames):
        if idx == 0:
            b |= 1 << k
        cl = (status_l >> idx) & 1
        cr = (status_r >> idx) & 1
        subs.append(asp_subpacket(left, right, cl, cr))
        idx = (idx + 1) % CHANNEL_STATUS_BITS
    while len(subs) < 4:
        subs.append([0] * 7)
    sample_present = (1 << len(frames)) - 1
    hb1 = sample_present | ((layout & 1) << 4)
    hb2 = (b << 4) | (sample_flat & 0xF)
    return Packet([PacketType.ASP, hb1, hb2], subs), idx


def unpack_asp(packet):
    """List of dicts (left, right, v/u/c/p per side, b) for the present subpackets."""
    assert packet.type == PacketType.ASP
    hb1, hb2 = packet.header_bytes[1], packet.header_bytes[2]
    out = []
    for k in range(4):
        if not (hb1 >> k) & 1:
            continue
        s = packet.subpacket_bytes[k]
        out.append({
            "left": s[0] | (s[1] << 8) | (s[2] << 16),
            "right": s[3] | (s[4] << 8) | (s[5] << 16),
            "vl": s[6] & 1, "ul": (s[6] >> 1) & 1, "cl": (s[6] >> 2) & 1, "pl": (s[6] >> 3) & 1,
            "vr": (s[6] >> 4) & 1, "ur": (s[6] >> 5) & 1, "cr": (s[6] >> 6) & 1, "pr": (s[6] >> 7) & 1,
            "b": (hb2 >> (4 + k)) & 1,
            "layout": (hb1 >> 4) & 1,
        })
    return out


def acr_packet(n, cts):
    sub = [0, (cts >> 16) & 0xF, (cts >> 8) & 0xFF, cts & 0xFF, (n >> 16) & 0xF, (n >> 8) & 0xFF, n & 0xFF]
    return Packet([PacketType.ACR, 0, 0], [list(sub) for _ in range(4)])


def unpack_acr(packet):
    s = packet.subpacket_bytes[0]
    cts = ((s[1] & 0xF) << 16) | (s[2] << 8) | s[3]
    n = ((s[4] & 0xF) << 16) | (s[5] << 8) | s[6]
    return n, cts


def audio_infoframe(cc=1, ct=0, sf=SF_CODE[48000], ss=SS_24BIT, ca=0, lsv=0, dm_inh=0):
    """CEA-861-D Table 16: PB1 = CT<<4 | CC, PB2 = SF<<2 | SS, PB3 = 0 (CT
    dependent), PB4 = CA, PB5 = DM_INH<<7 | LSV<<3, PB6..PB10 = 0."""
    data = [((ct & 0xF) << 4) | (cc & 0x7), ((sf & 0x7) << 2) | (ss & 0x3), 0, ca & 0xFF,
            ((dm_inh & 1) << 7) | ((lsv & 0xF) << 3), 0, 0, 0, 0, 0]
    return infoframe_packet(PacketType.AUDIO_INFOFRAME, 1, data)


def sine_frames(n, freq=1000.0, fs=48000, amplitude=0.5):
    """``n`` (left, right) frames of a sine as 24-bit two's complement ints."""
    import math
    full = (1 << 23) - 1
    frames = []
    for i in range(n):
        v = round(amplitude * full * math.sin(2 * math.pi * freq * i / fs)) & 0xFFFFFF
        frames.append((v, v))
    return frames
