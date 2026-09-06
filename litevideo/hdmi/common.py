#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Constants and stream layouts of the HDMI link layer.

References: HDMI Specification 1.3 (sections quoted per constant), DVI 1.0
§3.2 for the TMDS control characters. See doc/references.md for the URLs.
"""

from litex.soc.interconnect import stream

# TMDS characters ------------------------------------------------------------------------------

# Control characters, indexed by {D1, D0}: HDMI 1.3 §5.4.2 Table 5-34 and the
# "case (D1, D0)" table; on channel 0 D0=HSYNC, D1=VSYNC; on channel 1
# D0=CTL0, D1=CTL1; on channel 2 D0=CTL2, D1=CTL3.
control_tokens = [
    0b1101010100,  # D1=0 D0=0
    0b0010101011,  # D1=0 D0=1
    0b0101010100,  # D1=1 D0=0
    0b1010101011,  # D1=1 D0=1
]

# TERC4 characters indexed by the 4-bit data word: HDMI 1.3 §5.4.3.
terc4_tokens = [
    0b1010011100, 0b1001100011, 0b1011100100, 0b1011100010,
    0b0101110001, 0b0100011110, 0b0110001110, 0b0100111100,
    0b1011001100, 0b0100111001, 0b0110011100, 0b1011000110,
    0b1010001110, 0b1001110001, 0b0101100011, 0b1011000011,
]

# Video leading guard band, one value per channel: HDMI 1.3 Table 5-5.
video_gb_tokens = [0b1011001100, 0b0100110011, 0b1011001100]

# Data island guard band on channels 1 and 2: HDMI 1.3 Table 5-6. Channel 0
# carries TERC4(0b11, VSYNC, HSYNC) during both guard bands (§5.2.3.3).
data_gb_token = 0b0100110011


def data_gb_ch0_nibble(hsync, vsync):
    """The 4-bit TERC4 word channel 0 carries during data island guard bands."""
    return 0b1100 | ((vsync & 1) << 1) | (hsync & 1)


# Period structure -----------------------------------------------------------------------------

PREAMBLE_LENGTH              = 8    # HDMI 1.3 §5.2.1.1: 8 characters
GUARD_BAND_LENGTH            = 2    # §5.2.2.1, §5.2.3.3
PACKET_LENGTH                = 32   # §5.2.3.4: 32 characters per packet
MAX_PACKETS_PER_ISLAND       = 18   # §5.2.3.2
MIN_CONTROL_PERIOD           = 12   # §5.2.3.2: tS,min
MIN_EXTENDED_CONTROL_PERIOD  = 32   # Table 5-4: tEXTS,min
EXTENDED_CONTROL_MAX_DELAY_S = 50e-3  # Table 5-4: tEXTS,max_delay
MIN_ISLAND_TO_PREAMBLE       = 4    # tS,min (12) minus the 8-character preamble that ends the
                                    # control period after an island (§5.2.3.2, Figure 5-3)

# Preamble values as (channel 1 {D1,D0}, channel 2 {D1,D0}): Table 5-2,
# CTL0=1 for both, CTL2=1 only for a data island.
PREAMBLE_VIDEO = (0b01, 0b00)
PREAMBLE_DATA  = (0b01, 0b01)


class Period:
    """Link period, as decoded by HDMIPeriodDecoder (HDMI 1.3 §5.2)."""
    CONTROL             = 0
    VIDEO_PREAMBLE      = 1
    VIDEO_GUARD         = 2
    VIDEO               = 3
    DATA_PREAMBLE       = 4
    DATA_LEADING_GUARD  = 5
    DATA_ISLAND         = 6
    DATA_TRAILING_GUARD = 7


# Packets --------------------------------------------------------------------------------------

class PacketType:
    """Packet type codes: HDMI 1.3 Table 5-8 and CEA-861-D Table 4."""
    NULL             = 0x00
    ACR              = 0x01  # Audio Clock Regeneration
    ASP              = 0x02  # Audio Sample Packet
    GCP              = 0x03  # General Control Packet
    ACP              = 0x04  # Audio Content Protection
    ISRC1            = 0x05
    ISRC2            = 0x06
    ONE_BIT_AUDIO    = 0x07
    DST_AUDIO        = 0x08
    HBR_AUDIO        = 0x09
    GAMUT_METADATA   = 0x0A
    VENDOR_INFOFRAME = 0x81
    AVI_INFOFRAME    = 0x82
    SPD_INFOFRAME    = 0x83
    AUDIO_INFOFRAME  = 0x84
    MPEG_INFOFRAME   = 0x85


# Stream layouts -------------------------------------------------------------------------------

# Three 10-bit TMDS characters, one per channel, one beat per pixel clock.
raw_layout = [("c0", 10), ("c1", 10), ("c2", 10)]

# One data island packet: 24 header bits (HB0 | HB1 << 8 | HB2 << 16) and four
# 56-bit subpackets (SB0 in bits 0..7 ... SB6 in bits 48..55). ECC is not part
# of the layout: the encoder computes it, the decoder checks it.
packet_layout = [
    ("header", 24),
    ("sub0",   56),
    ("sub1",   56),
    ("sub2",   56),
    ("sub3",   56),
]

# Received packet: adds the ECC verdict (1 = header and all subpackets valid).
packet_rx_layout = packet_layout + [("ecc_ok", 1)]


def packet_endpoint():
    return stream.Endpoint(packet_layout)


def packet_rx_endpoint():
    return stream.Endpoint(packet_rx_layout)
