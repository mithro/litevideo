#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio constants and stream layouts.

References: HDMI 1.3 chapter 7 (N/CTS tables 7-1 to 7-3, packetisation
§7.6), CEA-861-D §6.6 (Audio InfoFrame), IEC 60958-3 consumer channel
status (bit numbers as in ALSA's ``include/sound/asound.h`` /
``iec958.h``: AES0 = bits 0..7, AES1 = 8..15, AES2 = 16..23, AES3 = 24..31,
AES4 = 32..39).
"""

# One IEC 60958 frame = a left and a right 24-bit sample (layout 0, HDMI §7.6).
audio_frame_layout = [("left", 24), ("right", 24)]

# One extracted subframe: sample, channel (0 = left/first, 1 = right/second,
# 2..7 for layout 1), IEC 60958 flags and the block-start flag.
audio_sample_layout = [("sample", 24), ("channel", 3), ("v", 1), ("u", 1), ("c", 1), ("p", 1), ("b", 1)]

CHANNEL_STATUS_BITS = 192          # IEC 60958 channel status block length (frames)

# Recommended N and expected CTS for coherent clocks (HDMI 1.3 §7.2.3
# Tables 7-1 to 7-3): {(fs, pixel clock Hz): (N, CTS)}.
N_CTS = {
    (32000,  25200000): (4096,  25200), (32000,  27000000): (4096,  27000), (32000,  74250000): (4096,  74250), (32000, 148500000): (4096, 148500),
    (44100,  25200000): (6272,  28000), (44100,  27000000): (6272,  30000), (44100,  74250000): (6272,  82500), (44100, 148500000): (6272, 165000),
    (48000,  25200000): (6144,  25200), (48000,  27000000): (6144,  27000), (48000,  74250000): (6144,  74250), (48000, 148500000): (6144, 148500),
}
# "Other" pixel clocks (Tables 7-1 to 7-3, last row): N below, CTS measured.
N_DEFAULT = {32000: 4096, 44100: 6272, 48000: 6144}

# Audio InfoFrame SF codes (CEA-861-D Table 18) and SS codes (Table 18: 1 = 16, 2 = 20, 3 = 24 bit).
SF_CODE = {32000: 1, 44100: 2, 48000: 3}
SS_24BIT = 3

# IEC 60958-3 channel status fields (ALSA iec958.h names in comments).
IEC_FS = {44100: 0x0, 48000: 0x2, 32000: 0x3}     # IEC958_AES3_CON_FS_* (bits 24..27)
IEC_WORD_LENGTH_24 = 0xB                           # IEC958_AES4_CON_WORDLEN_24_20 | MAX_WORDLEN_24 (bits 32..35)
IEC_CHANNEL_LEFT = 1                               # IEC958_AES2_CON_CHANNEL (bits 20..23)
IEC_CHANNEL_RIGHT = 2


def channel_status_block(fs=48000, channel=IEC_CHANNEL_LEFT, word_length=IEC_WORD_LENGTH_24, category=0x00):
    """192-bit IEC 60958-3 consumer channel status as an int (bit i = frame i's C bit).

    bit 0 consumer (0), bit 1 linear PCM (0), bit 2 copyright not asserted
    (1), bits 3..5 no pre-emphasis, bits 6..7 mode 0, bits 8..15 category
    code, bits 16..19 source number, bits 20..23 channel number, bits 24..27
    sampling frequency, bits 28..29 clock accuracy level II, bits 32..35 word
    length, all other bits 0."""
    v = 0
    v |= 1 << 2                                    # IEC958_AES0_CON_NOT_COPYRIGHT
    v |= (category & 0xFF) << 8
    v |= (channel & 0xF) << 20
    v |= (IEC_FS[fs] & 0xF) << 24
    v |= (word_length & 0xF) << 32
    return v
