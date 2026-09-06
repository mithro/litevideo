# HDMI audio

`litevideo/hdmi/audio/` carries L-PCM audio in data islands: the transmitter
packs samples into Audio Sample Packets and tells the sink how to recover the
audio clock; the receiver side unpacks them. Section numbers refer to the
HDMI Specification 1.3 unless stated otherwise (see
[references.md](references.md)).

```
ToneGenerator / your PCM stream ─► AudioSamplePacketizer ─┐
   (audio_frame_layout: left, right)                     ├─► PacketScheduler ─► HDMIFramer
ACRGenerator (N, CTS, cadence from frame_strobe) ────────┤     (priority: ASP, ACR, Audio InfoFrame, GCP, AVI)
AudioInfoFrameGenerator (once per frame) ────────────────┘

DataIslandDecoder ─► AudioExtract ─► audio_sample_layout (sample, channel, V, U, C, P, B) + N/CTS + InfoFrame
```

## Audio Sample Packet (§5.3.4, §7.6)

Layout 0 (two channels): each of the four subpackets carries one IEC 60958
frame, that is a left and a right subframe.

| Header | Meaning |
|---|---|
| HB0 = 0x02 | packet type |
| HB1[3:0] | `sample_present`: which subpackets carry a frame, filled contiguously from subpacket 0 (Table 7-7: 0000, 0001, 0011, 0111, 1111) |
| HB1[4] | layout (0) |
| HB2[3:0] | `sample_flat` (0) |
| HB2[7:4] | B: subpacket k carries the first frame of an IEC 60958 channel status block |

| Subpacket byte | Content (Table 5-13) |
|---|---|
| SB0, SB1, SB2 | left sample, IEC 60958 time slots 4..27, LSB first (24 bits) |
| SB3, SB4, SB5 | right sample |
| SB6 | `PR CR UR VR PL CL UL VL` (bit 7 to bit 0): parity, channel status, user, validity for right then left |

Flags: V = 0 (valid PCM), U = 0, C = the bit of the 192-bit consumer channel
status block for this frame position (left and right differ only in the
channel number field), P = even parity over the 24 sample bits and V, U, C.

Channel status (IEC 60958-3, bit numbers as in ALSA `iec958.h`): bit 0
consumer, bit 1 linear PCM, bit 2 copyright not asserted, bits 8..15
category, bits 20..23 channel number (1 left, 2 right), bits 24..27
sampling frequency (48 kHz = `0x2`), bits 32..35 word length (24 bit = `0xB`).
`litevideo/hdmi/audio/common.py` builds the block; the packetizer holds it
in two 192-entry ROMs.

Delivery (§7.8.1): the packetizer offers a packet as soon as one frame is
buffered and sends every buffered frame (up to four) when the scheduler
takes it. It never sends empty or padding packets.

## Audio Clock Regeneration (§5.3.3, §7.2)

The sink reconstructs 128·fs = f_TMDS · N / CTS from the packet's N and
CTS. `ACRGenerator` sends one packet every N/128 audio frames (§7.8.2), with
Audio Sample Packets taking priority over it in the scheduler.

| Subpacket byte | Content (Table 5-11) |
|---|---|
| SB0 | 0 |
| SB1[3:0], SB2, SB3 | CTS[19:16], CTS[15:8], CTS[7:0] |
| SB4[3:0], SB5, SB6 | N[19:16], N[15:8], N[7:0] |

Coherent clocks use the recommended N and expected CTS of Tables 7-1 to 7-3
(`N_CTS` in `common.py`, for instance 48 kHz at 74.25 MHz: N = 6144,
CTS = 74250). With a real audio clock the generator can instead measure CTS
as the number of pixel clocks per N cycles of a 128·fs strobe (Figure 7-1,
`measure` = 1).

## Audio InfoFrame (CEA-861-D §6.6)

HB0 = 0x84, HB1 = 1, HB2 = 10, PB0 checksum; PB1 = CT<<4 | CC (CC = 1 for
two channels), PB2 = SF<<2 | SS (SF 3 = 48 kHz, SS 3 = 24 bit), PB4 = CA
(0 = front left/right), PB5 = DM_INH<<7 | LSV<<3. Sent once per frame while
audio is enabled.

## Sources

`ToneGenerator` derives the sample rate from the pixel clock with a 32-bit
accumulator (`rate_increment` = fs / f_pix · 2³²) and reads a 256-entry
sine ROM with a 32-bit phase accumulator (`tone_increment` = f / fs · 2³²),
so every sample is predictable (`audio.model.tone_sequence`). It is the
hardware test signal: the tier-1 loopback drains the extracted samples and
checks them against the ROM, the tier-4 run captures the tone through the
Magewell's audio interface.

## CSRs added by `HDMITransmitter(with_audio=True)`

| Register | Fields |
|---|---|
| `audio_control` | `enable`, `tone_enable`, `send_acr`, `send_infoframe`, `acr_measure` |
| `audio_n`, `audio_cts` | ACR values (defaults from Tables 7-1 to 7-3 for the given pixel clock) |
| `audio_infoframe` | `cc, ct, ss, sf, ca, lsv, dm_inh` |
| `tone_increment` | tone frequency |
| `audio_frames`, `audio_acrs`, `audio_overruns` | counters |

## Interoperating with the netv2-fpga audio cores

The `netv2-fpga` `modern` tree's embed/extract pair differs from the
specification in three places (`hdmi-protocol.md` §7): ECC polynomial,
subpacket layout (it interleaves V/U/C/P after each sample instead of the
SB6 flag byte), and the channel-0 guard band. Its streams therefore do not
decode with LiteVideo or a commercial sink, and vice versa; the LiteVideo
layout was verified against a Magewell capture device (see
`doc/reports/`).
