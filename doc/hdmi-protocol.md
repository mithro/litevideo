# HDMI link layer

This page describes what LiteVideo's `litevideo/hdmi/` package implements, at
the level of the 10-bit TMDS characters travelling on the three data
channels. Section numbers refer to the HDMI Specification 1.3 unless stated
otherwise; DVI 1.0 is cited for the TMDS coding itself. See
[references.md](references.md) for the documents.

## 1. Periods

An HDMI link is always in one of three periods (§5.2, Figure 5-3):

| Period | Encoding | Content |
|---|---|---|
| Control | 2 bits per channel, 10-bit control characters (§5.4.2) | HSYNC/VSYNC on channel 0, CTL0..CTL3 on channels 1 and 2 |
| Video Data | TMDS 8b/10b (§5.4.4, DVI 1.0 §3.2) | one pixel component per channel per character |
| Data Island | TERC4, 4 bits per channel (§5.4.3) | packets (audio, InfoFrames, control) |

A Control Period lasts at least 12 characters (tS,min, §5.2.3.2) and ends
with an 8-character **Preamble** whose CTL bits announce what follows
(Table 5-2, CTL0 first): `1000` for a Video Data Period, `1010` for a Data
Island. Every Video Data Period starts with a 2-character **Video Leading
Guard Band** (Table 5-5); every Data Island is bracketed by a 2-character
**Leading** and **Trailing Guard Band** (Table 5-6). At least every 50 ms
the source sends an **Extended Control Period** of at least 32 characters
(Table 5-4), and while video is transmitted at least one island per two
video fields (§5.2.3.2).

One line with one island, character by character:

```
 active video ... | control >=12 | DI preamble 8 | lead GB 2 | packet 32 | ... | trail GB 2 | control >=4 | video preamble 8 | video GB 2 | active video ...
 VIDEO            | CONTROL      | DATA_PREAMBLE | DATA_LGB  | DATA_ISLAND ... | DATA_TGB   | CONTROL     | VIDEO_PREAMBLE   | VIDEO_GUARD| VIDEO
```

The second row is the `Period` value `HDMIPeriodDecoder` reports for each
character (`litevideo/hdmi/common.py`).

## 2. Characters

**Control characters** (§5.4.2, Table 5-34), indexed by {D1, D0}:

| D1 D0 | character | channel 0 | channel 1 | channel 2 |
|---|---|---|---|---|
| 0 0 | `1101010100` | HSYNC=0 VSYNC=0 | CTL0=0 CTL1=0 | CTL2=0 CTL3=0 |
| 0 1 | `0010101011` | HSYNC=1 | CTL0=1 | CTL2=1 |
| 1 0 | `0101010100` | VSYNC=1 | CTL1=1 | CTL3=1 |
| 1 1 | `1010101011` | both | both | both |

They have seven or more transitions so a receiver can find character
boundaries during any Control Period (§5.2.1.2).

**Video characters** follow the DVI 1.0 §3.2.2 algorithm: the 8-bit value is
XOR- or XNOR-chained (bit 8 says which) and optionally inverted (bit 9) to
keep the running disparity within ±10 bits. `litevideo/hdmi/model.py`
implements `tmds_encode`/`tmds_decode`; the gateware decoder is
`TMDSCharacterDecoder` (`litevideo/hdmi/tmds.py`); encoding reuses the
existing `litevideo/output/hdmi/encoder.py`.

**TERC4 characters** (§5.4.3) map a 4-bit word to one of sixteen 10-bit
characters chosen for error resilience:

```
0 1010011100  4 0101110001  8 1011001100  C 1010001110
1 1001100011  5 0100011110  9 0100111001  D 1001110001
2 1011100100  6 0110001110  A 0110011100  E 0101100011
3 1011100010  7 0100111100  B 1011000110  F 1011000011
```

**Guard bands.** Video (Table 5-5): channel 0 `1011001100`, channel 1
`0100110011`, channel 2 `1011001100`. Data island (Table 5-6): channels 1
and 2 `0100110011`; channel 0 is not fixed but carries
`TERC4({1, 1, VSYNC, HSYNC})`, i.e. 0xC to 0xF (§5.2.3.3). Note that
channel 1's video and data guard band characters are identical, so the
period decoder recognises a video guard band only when all three channels
carry their video value and a data guard band when channels 1 and 2 both
carry `0100110011`. Guard bands are exactly two characters long, and the
video guard band values are also legal pixel encodings (B,G,R =
0xAB,0x55,0xAB), so after recognising the first character the decoder
consumes the second by count rather than by value.

## 3. Data islands

Inside an island every channel sends TERC4 characters (§5.2.3.1):

| channel 0 bit | content |
|---|---|
| 0 | HSYNC |
| 1 | VSYNC |
| 2 | packet header bit |
| 3 | 0 on the first character after the leading guard band, 1 on every other packet character (HDMI 1.3 Figure 5-3 channel 0 row; spelled out in the HDMI 1.4b CTS) |

Channels 1 and 2 carry the four BCH blocks: block k occupies bit k of both
channels, channel 1 with the even bit and channel 2 with the odd bit
(§5.2.3.4, Figure 5-4).

A **packet** is 32 characters (§5.2.3.4): a 24-bit header (HB0 = packet
type, HB1, HB2) plus 8 ECC bits on channel 0 (one bit per character, LSB
first), and four subpackets of 56 data bits (SB0..SB6, LSB first) plus 8 ECC
bits (two bits per character). An island carries 1 to 18 packets and is
therefore 36 to 580 characters long including its guard bands (§5.2.3.2).

Packet types (Table 5-8, CEA-861-D Table 4) are in `PacketType`
(`litevideo/hdmi/common.py`): Null 0x00, Audio Clock Regeneration 0x01,
Audio Sample 0x02, General Control 0x03, ACP 0x04, ISRC1/2 0x05/0x06, One
Bit Audio 0x07, DST 0x08, HBR 0x09, Gamut Metadata 0x0A, and the InfoFrames
0x81 (vendor), 0x82 (AVI), 0x83 (SPD), 0x84 (Audio), 0x85 (MPEG).

## 4. Error correction

Header and subpackets are protected by BCH(32,24) and BCH(64,56) codes
generated by G(x) = 1 + x⁶ + x⁷ + x⁸ (§5.2.3.5, Figure 5-5). With bits fed
LSB first the generator is a right-shifting reflected LFSR: XOR the data bit
with the register's bit 0, shift right, and if the result was 1 XOR in the
mask 0x83 (0xC1 bit-reversed). `litevideo/hdmi/bch.py` provides `bch_ecc`
(Python) and `bch_step` (Migen). Worked example: the Audio Clock
Regeneration header `01 00 00` gives ECC `0x4A`; `82 02 0D` (AVI InfoFrame
header) gives `0xE4`. `test/test_hdmi_bch.py` cross-checks the LFSR against
polynomial long division and against vectors from hdl-util/hdmi.

## 5. Placement rules the transmitter must keep

From §5.2.3.2, Table 5-4 and Figure 5-3:

- every Control Period is at least 12 characters long, so after an island's
  trailing guard band at least 4 control characters precede the 8-character
  video preamble;
- islands hold 1 to 18 packets, always a whole number of packets;
- an Extended Control Period of at least 32 characters occurs at least every
  50 ms;
- at least one island is sent every two video fields while video is on;
- the Data Island preamble code must never be sent outside a preamble
  (§5.2.1.1);
- HSYNC and VSYNC are carried live on every island character (§5.2.3.1).

`DataIslandEncoder` enforces the first rule between consecutive islands by
staying busy for 4 characters after the trailing guard band (4 + the next
8-character preamble = 12); the framer enforces it against video by placing
islands only where they fit, and supplies live syncs.

## 6. LiteVideo modules

| Module | File | Latency | Role |
|---|---|---|---|
| `TMDSCharacterDecoder(channel)` | `hdmi/tmds.py` | 1 | classify one character: data, control value, guard bands, TERC4 word |
| `HDMIPeriodDecoder` | `hdmi/period.py` | 2 | period state machine; `video_data_layout` source (hsync, vsync, de, r, g, b); island nibbles and `island_active`/`island_first` |
| `DataIslandDecoder` | `hdmi/island/decoder.py` | 1 after character 31 | packets with `ecc_ok`, packet and error counters |
| `DataIslandEncoder` | `hdmi/island/encoder.py` | — | packet stream to framed island characters; `max_packets` (clamped to 18) and `start` from the framer; ignores `source.ready` (one character per cycle once started) |
| model | `hdmi/model.py` | — | Python reference for all of the above |

All modules run in the default clock domain and are meant to be wrapped with
`ClockDomainsRenamer("pix")` by the integrating transmitter or receiver.
Streams use the LiteX `video_data_layout` for pixels and the `raw_layout`
(`c0`, `c1`, `c2`) for characters, so LiteX's own video timing generator and
frame buffer cores can be placed in front of the transmitter.

## 7. Differences found in other implementations

While reviewing prior work on the same hardware (the `netv2-fpga` `modern`
branch audio cores) three departures from the specification were found.
Streams generated by that tree will not decode with LiteVideo (nor with a
commercial sink) and vice versa:

1. ECC polynomial x⁸ + x⁷ + x⁶ + x⁴ + 1 (mask 0x8B) instead of
   1 + x⁶ + x⁷ + x⁸ (mask 0x83), §5.2.3.5.
2. Audio Sample Subpacket layout with V/U/C/P bits after each sample; Table
   5-13 places both 24-bit samples first (SB0 to SB5) and all flags in SB6.
3. The channel 1/2 data guard band character sent on channel 0 too; §5.2.3.3
   requires `TERC4({1, 1, VSYNC, HSYNC})` on channel 0.
