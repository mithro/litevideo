#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Golden-model extensions for the transmitter: InfoFrame and General
Control packets (HDMI 1.3 §5.3.5/§5.3.6, CEA-861-D §6.4) and whole frames of
characters with data islands placed the way ``HDMIFramer`` places them.

Imported into ``litevideo.hdmi.model`` so callers use ``model.avi_infoframe``
and friends.
"""

from litevideo.hdmi.common import *
from litevideo.hdmi.model import (Packet, island_tokens, island_length, video_tokens, control_chars)


def infoframe_packet(type_code, version, data_bytes):
    """HDMI 1.3 Tables 5-14/5-15: HB0 = type, HB1 = version, HB2 = length (<= 27),
    PB0 = checksum so that all header and payload bytes sum to zero mod 256."""
    assert 1 <= len(data_bytes) <= 27
    header = [type_code & 0xFF, version & 0xFF, len(data_bytes)]
    checksum = (-(sum(header) + sum(data_bytes))) & 0xFF
    payload = [checksum] + list(data_bytes) + [0] * (27 - len(data_bytes))
    subs = [payload[7 * k:7 * k + 7] for k in range(4)]
    return Packet(header, subs)


def avi_infoframe(vic, y=0, a=0, b=0, s=0, c=0, m=None, r=8, itc=0, ec=0, q=0, sc=0, pr=0, yq=0, cn=0,
                  bars=(0, 0, 0, 0)):
    """CEA-861-D §6.4 Tables 7 to 12 (version 2, 13 data bytes).

    y: 0 RGB, 1 YCbCr 4:2:2, 2 YCbCr 4:4:4. m: picture aspect (1 4:3, 2 16:9);
    defaults to 16:9 for VIC >= 4 as CEA-861-D Table 3 lists those formats.
    r: active format aspect ratio (8 = same as picture). yq/cn are CEA-861-E
    additions (0 for 861-D). bars: top, bottom, left, right line/pixel
    numbers (only meaningful when b != 0)."""
    if m is None:
        m = 2 if vic >= 4 else 1
    db1 = ((y & 3) << 5) | ((a & 1) << 4) | ((b & 3) << 2) | (s & 3)
    db2 = ((c & 3) << 6) | ((m & 3) << 4) | (r & 0xF)
    db3 = ((itc & 1) << 7) | ((ec & 7) << 4) | ((q & 3) << 2) | (sc & 3)
    db4 = vic & 0x7F
    db5 = ((yq & 3) << 6) | ((cn & 3) << 4) | (pr & 0xF)
    top, bottom, left, right = bars
    db6_13 = [top & 0xFF, top >> 8, bottom & 0xFF, bottom >> 8, left & 0xFF, left >> 8, right & 0xFF, right >> 8]
    return infoframe_packet(PacketType.AVI_INFOFRAME, 2, [db1, db2, db3, db4, db5] + db6_13)


def gcp_packet(set_avmute=0, clear_avmute=0, cd=0, pp=0, default_phase=0):
    """HDMI 1.3 §5.3.6 Tables 5-16/5-17: four identical subpackets."""
    sb0 = (set_avmute & 1) | ((clear_avmute & 1) << 4)
    sb1 = (cd & 0xF) | ((pp & 0xF) << 4)
    sb2 = (default_phase & 1) << 2
    sub = [sb0, sb1, sb2, 0, 0, 0, 0]
    return Packet([PacketType.GCP, 0, 0], [list(sub) for _ in range(4)])


def frame_tokens(timing, nframes=1, islands=None, pixels=None):
    """Whole frames of characters plus per-character (de, hsync, vsync) for
    transmitter tests. ``timing`` keys: hactive hfront hsync hback vactive
    vfront vsync vback (positive sync pulses). ``islands`` is an optional dict
    {line_index: [Packet, ...]} placed 12 characters after the HSYNC leading
    edge of that line (the framer's placement rule).

    Video lines: pixels | control | [island] | control | video preamble | video guard band
    Blank lines : control | [island] | control (no preamble/guard band since no DE follows)
    Returns a list of (c0, c1, c2, de, hsync, vsync)."""
    ha, hf, hs, hb = timing["hactive"], timing["hfront"], timing["hsync"], timing["hback"]
    va, vf, vs, vb = timing["vactive"], timing["vfront"], timing["vsync"], timing["vback"]
    vtotal = va + vf + vs + vb
    islands = islands or {}
    out = []
    for f in range(nframes):
        for y in range(vtotal):
            vsync = 1 if va + vf <= y < va + vf + vs else 0
            active = y < va
            next_active = ((y + 1) % vtotal) < va
            if pixels is None:
                row = [(((x + y) * 7) & 0xFF, ((x * 13) ^ y) & 0xFF, ((x + 2 * y) * 29) & 0xFF) for x in range(ha)]
            else:
                row = pixels[y]
            if active:
                # Disparity restarts at 0 on every line: the TMDS encoder resets it
                # during blanking (DVI 1.0 Figure 3-5).
                for (c0, c1, c2) in video_tokens(row):
                    out.append((c0, c1, c2, 1, 0, vsync))
            else:
                for _ in range(ha):
                    out.append(control_chars(0, vsync) + (0, 0, vsync))
            # blanking: front porch (control), sync pulse, back porch
            blank = []
            for x in range(hf + hs + hb):
                hsync = 1 if hf <= x < hf + hs else 0
                blank.append([control_chars(hsync, vsync), hsync])
            packets = islands.get(y)
            if packets:
                start = hf + MIN_CONTROL_PERIOD
                n = island_length(len(packets))
                toks = island_tokens(packets, syncs=[(blank[start + i][1], vsync) for i in range(n)])
                for i, t in enumerate(toks):
                    blank[start + i][0] = t
            if next_active:
                for i in range(PREAMBLE_LENGTH):
                    x = hf + hs + hb - PREAMBLE_LENGTH - GUARD_BAND_LENGTH + i
                    blank[x][0] = control_chars(blank[x][1], vsync, PREAMBLE_VIDEO)
                for i in range(GUARD_BAND_LENGTH):
                    blank[-GUARD_BAND_LENGTH + i][0] = tuple(video_gb_tokens)
            for (c0, c1, c2), hsync in blank:
                out.append((c0, c1, c2, 0, hsync, vsync))
    return out
