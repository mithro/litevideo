# LiteVideo HDMI phase 3: audio

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject L-PCM stereo audio into the transmitter (Audio Sample Packets with IEC 60958 framing, Audio Clock Regeneration, Audio InfoFrame) and extract it from a received packet stream, bit-exact against a Python model, with a fabric tone generator so the NeTV2 bench can prove it on hardware (tier T1 round trip in the fabric, tier T4 tone captured by the Magewell's audio input).

**Architecture:** New package `litevideo/hdmi/audio/`: `AudioSamplePacketizer` turns an `audio_frame_layout` stream (one L/R pair per beat) into ASPs with the IEC 60958 V/U/C/P/B bits (HDMI 1.3 Table 5-12/5-13, §7.6); `ACRGenerator` emits N/CTS packets at 128·fs/N (§7.2, §7.8.2) with constant CTS for coherent clocks or measured CTS from a 128·fs strobe; `AudioInfoFrameGenerator` (CEA-861-D §6.6); `AudioExtract` reverses ASP/ACR/InfoFrame from `packet_rx_layout`; sources: `ToneGenerator` (NCO in the pixel domain) and `CSRAudioSource` (FIFO fed from `sys`). `HDMITransmitter(with_audio=True)` adds these as the high-priority scheduler sinks and their CSRs.

**Tech Stack:** as phase 2. References: HDMI 1.3 §5.3.3 (Tables 5-10/5-11 ACR), §5.3.4 (Tables 5-12/5-13 ASP), §7.2 (N/CTS, Tables 7-1 to 7-3, Figure 7-1), §7.6 (packetization, Table 7-7 sample_present patterns), §7.8 (delivery rules); CEA-861-D §6.6 (Tables 16 to 22 Audio InfoFrame); IEC 60958-1/-3 subframe and channel status (AES3-2009 is the free equivalent), hdl-util/hdmi `audio_sample_packet.sv` for the channel status assembly.

**Working rules:** as phases 0 to 2. Hardware: announce loads and builds; `rpi5-netv2` only.

**Findings to honour (doc/hdmi-protocol.md §7):** Table 5-13 layout (SB0..2 left sample, SB3..5 right sample, SB6 = PR CR UR VR PL CL UL VL), ECC polynomial 0x83, channel 0 guard band TERC4(1,1,V,H), sample_present contiguous from sp0 (Table 7-7), ASP only when at least one frame is buffered (§7.8.1), ASP priority over ACR (§7.8.2).

---

## File structure

| Path | Responsibility |
|---|---|
| `litevideo/hdmi/audio/__init__.py` | re-exports |
| `litevideo/hdmi/audio/common.py` | `audio_frame_layout`, `audio_sample_layout`, N/CTS table, sample-rate codes (Audio InfoFrame SF, IEC 60958 status), IEC 60958 channel status builder |
| `litevideo/hdmi/audio/model.py` | Python model: `asp_packet`, `acr_packet`, `audio_infoframe`, `channel_status_bits`, `parity`, `unpack_asp` |
| `litevideo/hdmi/audio/packetizer.py` | `AudioSamplePacketizer` |
| `litevideo/hdmi/audio/acr.py` | `ACRGenerator` |
| `litevideo/hdmi/audio/infoframe.py` | `AudioInfoFrameGenerator` |
| `litevideo/hdmi/audio/extract.py` | `AudioExtract` |
| `litevideo/hdmi/audio/sources.py` | `ToneGenerator`, `CSRAudioSource` |
| `litevideo/hdmi/transmitter.py` | `with_audio=True`: sinks, CSRs, tone/CSR source selection |
| `test/test_hdmi_audio_*.py` | tests (model, packetizer, acr, infoframe, extract, round trip) |
| `bench/netv2/hdmi_tx.py`, `hdmi_loopback.py` | tone on, extract in the loopback with a CSR-readable sample FIFO |
| `bench/netv2/host/run_loopback.py`, `run_tx.py` | audio checks (PCM read back; Magewell ALSA capture FFT) |
| `doc/audio.md` | documentation |

---

### Task 1: audio constants, layouts and Python model

**Files:** `litevideo/hdmi/audio/__init__.py`, `litevideo/hdmi/audio/common.py`, `litevideo/hdmi/audio/model.py`, `test/test_hdmi_audio_model.py`

- [ ] **Step 1: `common.py`**

```python
"""Audio constants and stream layouts (HDMI 1.3 chapter 7, CEA-861-D §6.6, IEC 60958-3)."""

from litevideo.hdmi.common import PacketType

# One IEC 60958 frame = a left and a right 24-bit sample (layout 0, §7.6).
audio_frame_layout = [("left", 24), ("right", 24)]

# One extracted subframe: sample, channel (0 = left/first, 1 = right/second,
# 2..7 for layout 1), IEC 60958 flags and the block-start flag.
audio_sample_layout = [("sample", 24), ("channel", 3), ("v", 1), ("u", 1), ("c", 1), ("p", 1), ("b", 1)]

# Recommended N and expected CTS for coherent clocks (HDMI 1.3 §7.2.3
# Tables 7-1 to 7-3): {(fs, pixel clock Hz): (N, CTS)}.
N_CTS = {
    (32000,  25200000): (4096,  25200), (32000,  27000000): (4096,  27000), (32000,  74250000): (4096,  74250), (32000, 148500000): (4096, 148500),
    (44100,  25200000): (6272,  28000), (44100,  27000000): (6272,  30000), (44100,  74250000): (6272,  82500), (44100, 148500000): (6272, 165000),
    (48000,  25200000): (6144,  25200), (48000,  27000000): (6144,  27000), (48000,  74250000): (6144,  74250), (48000, 148500000): (6144, 148500),
}
# Generic values for "other" pixel clocks (Tables 7-1 to 7-3, row "Other"): CTS is measured.
N_DEFAULT = {32000: 4096, 44100: 6272, 48000: 6144}

# Audio InfoFrame SF codes (CEA-861-D Table 18) and IEC 60958-3 channel status
# sampling frequency codes (bits 24..27, LSB first).
SF_CODE  = {32000: 1, 44100: 2, 48000: 3}
IEC_FS   = {44100: 0b0000, 48000: 0b0010, 32000: 0b0011}
IEC_WORD_LENGTH_24 = 0b1011   # bit 32 = 1 (24-bit max), bits 33..35 = 101 (24 bits)


def channel_status_block(fs=48000, channel=1, word_length=IEC_WORD_LENGTH_24, category=0x00):
    """192-bit IEC 60958-3 consumer channel status as an int (bit i = frame i's C bit).

    bit 0 consumer, 1 PCM, 2 copyright not asserted (1), 3..5 no pre-emphasis,
    6..7 mode 0, 8..15 category code, 16..19 source number 0, 20..23 channel
    number (1 = left, 2 = right), 24..27 sampling frequency, 28..29 clock
    accuracy level II, 32..35 word length, rest 0."""
    v = 0
    v |= 1 << 2                       # copyright not asserted
    v |= (category & 0xFF) << 8
    v |= (channel & 0xF) << 20
    v |= (IEC_FS[fs] & 0xF) << 24
    v |= (word_length & 0xF) << 32
    return v
```

- [ ] **Step 2: `model.py`** with `parity(sample, v, u, c)` (even parity over the 24 sample bits and V, U, C so that the 28-bit subframe has an even number of ones), `asp_packet(frames, block_index, fs, layout=0, sample_flat=0)` returning `(Packet, next_block_index)` where `frames` is 1..4 `(left, right)` pairs, header HB1 = sample_present (contiguous from sp0) | layout<<4, HB2 = B flags (bit k set when frame k is block-start, i.e. block_index == 0 for that frame) | sample_flat, subpacket k = Table 5-13 bytes (left in SB0..2, right in SB3..5, SB6 = P_R C_R U_R V_R P_L C_L U_L V_L with C from `channel_status_block` bit `block_index`), `acr_packet(n, cts)` (Table 5-11: SB1[3:0] = CTS[19:16], SB2 = CTS[15:8], SB3 = CTS[7:0], SB4[3:0] = N[19:16], SB5, SB6; four identical subpackets), `audio_infoframe(cc=1, ct=0, sf=3, ss=3, ca=0, lsv=0, dm_inh=0)` via `model.infoframe_packet(0x84, 1, [db1, db2, 0, ca, (dm_inh<<7)|(lsv<<3), 0,0,0,0,0])` with db1 = ct<<4 | cc, db2 = sf<<2 | ss (Tables 17 to 22), and `unpack_asp(packet)` returning the list of `(channel, sample, v, u, c, p, b)` for present subpackets.

- [ ] **Step 3: Tests**: parity even; ASP byte layout against hand-built bytes for one frame (`left=0x123456, right=0xABCDEF` → SB0..5 = 56 34 12 EF CD AB, SB6 = flags); block-start bit set only on frame 0 of 192; channel status bit stream for L and R differs only in bits 20..23; `unpack_asp(asp_packet(...))` round trip; ACR bytes for N=6144, CTS=74250 (`00 01 22 0A 00 18 00`); Audio InfoFrame checksum sums to zero and PB1/PB2 per Tables 17/18.

- [ ] **Step 4: Commit** `hdmi/audio: constants, IEC 60958 channel status and packet model`.

### Task 2: `AudioSamplePacketizer`

**Files:** `litevideo/hdmi/audio/packetizer.py`, `test/test_hdmi_audio_packetizer.py`

Interface: `sink` (`audio_frame_layout`), `source` (`packet_layout`), inputs `fs_code` (2 bits selecting the channel status ROM variant) or simply a `channel_status` 192-bit constant chosen at build time from `fs` (default 48 kHz; CSR-selectable later), `enable`. Behaviour: frames are pulled into a 4-entry register set while `source` is not being accepted; `source.valid` when ≥ 1 frame is buffered (§7.8.1); on `source.ready` the packet carries all buffered frames (1..4) with contiguous `sample_present`, the B flag on the frame whose block counter is 0, C bits from the channel status ROM at the frame's block index (0..191, per channel), P computed per subframe, V = U = 0. The block counter advances per frame. `frames_sent` counter.

Tests: (1) with a steady sink, packets carry 4 frames each and the sequence of unpacked frames equals the input; (2) with one frame available per opportunity, packets have `sample_present = 0b0001`; (3) block-start bit appears every 192 frames on the correct subpacket; (4) C bits over 192 frames equal `channel_status_block(...)` for L and R; (5) P bits verify even parity; all compared through `model.unpack_asp`.

- [ ] Commit `hdmi/audio: add Audio Sample Packet packetizer with IEC 60958 framing`.

### Task 3: `ACRGenerator` and `AudioInfoFrameGenerator`

**Files:** `litevideo/hdmi/audio/acr.py`, `litevideo/hdmi/audio/infoframe.py`, tests

`ACRGenerator(n_reset=6144, cts_reset=74250)`: inputs `n` (20), `cts` (20), `frame_strobe` (one pulse per audio frame consumed by the packetizer), optional `clk128_strobe` (pulse per 128·fs cycle, for measured mode), `measure` select; emits one ACR packet every `n/128` frames (§7.8.2: rate 128·fs/N); in measured mode a divide-by-N counter on `clk128_strobe` latches the number of pixel clocks between its wraps into the CTS field (Figure 7-1). Tests: at N=6144 one ACR per 48 frames, bytes equal `model.acr_packet`; measured mode with a synthetic strobe every 1547 or 1546 cycles (74.25 MHz / 48 kHz) yields CTS 74250 ± 1 per island average (assert the mean over 8 packets within 1).

`AudioInfoFrameGenerator`: like the AVI one, fields record (cc 3, ct 4, sf 3, ss 2, ca 8, lsv 4, dm_inh 1), one packet per trigger, bytes equal `model.audio_infoframe`.

- [ ] Commit `hdmi/audio: add Audio Clock Regeneration and Audio InfoFrame generators`.

### Task 4: `AudioExtract`

**Files:** `litevideo/hdmi/audio/extract.py`, `test/test_hdmi_audio_extract.py`

Sink `packet_rx_layout` (from `DataIslandDecoder`; packets with `ecc_ok = 0` are counted and dropped), outputs: `sample_source` (`audio_sample_layout`, one beat per present subframe, no back-pressure), latches `n`, `cts`, `infoframe` fields (cc, ct, sf, ss, ca, valid), counters `asp_count`, `acr_count`, `infoframe_count`, `dropped_count`. Layout 0 only: subpacket k gives channel 0 (left) then channel 1 (right). Tests: feed `model.asp_packet` packets → samples equal the frames; ACR latch; InfoFrame latch; ECC-bad packets dropped; `b` flag on block start.

- [ ] Commit `hdmi/audio: add audio extract (ASP to samples, ACR and InfoFrame latches)`.

### Task 5: sources and transmitter integration

**Files:** `litevideo/hdmi/audio/sources.py`, `litevideo/hdmi/transmitter.py`, tests

`ToneGenerator(pix_clk_freq, fs=48000, table_bits=8, amplitude=0.5)`: phase accumulator producing one `audio_frame_layout` beat per `pix_clk_freq/fs` cycles on average (32-bit fractional accumulator so the long-term rate is exact), a 256-entry quarter-wave sine ROM, CSR-controlled tone frequency (phase increment) and enable; left and right carry the same tone unless `right_mute`. Also emits `frame_strobe` for the ACR generator.

`CSRAudioSource`: CSR `pcm` (24-bit sample + channel bit + write strobe) into an `AsyncFIFO` (sys → pix), pairs popped as frames; `level` status.

`HDMITransmitter(with_audio=True, pix_clk_freq=...)`: three extra sinks at the head of the scheduler (ASP, ACR, Audio InfoFrame in that order), CSRs: `audio_control` (enable, source: tone/csr, send_infoframe, send_acr), `audio_n`, `audio_cts`, `audio_infoframe` fields, `tone_increment`, `audio_frames_sent`, `audio_islands`. Test: full transmitter → period decoder → island decoder → `AudioExtract` in one simulation; a 1 kHz tone at 48 kHz on a 74.25 MHz clock is impractical in Migen simulation (1546 cycles per sample), so the test uses a small fake pixel clock ratio (e.g. `pix_clk_freq=48000*40`) and the `TIMING` of the framer tests; assert the extracted samples equal the tone ROM sequence, N/CTS decode, InfoFrame fields.

- [ ] Commit `hdmi/audio: tone and CSR sources; HDMITransmitter audio integration`.

### Task 6: bench and hardware

- `hdmi_tx.py`: `with_audio=True`, tone 1 kHz on at reset (CSR default enable), N=6144, CTS=74250 (nominal; the actual pixel clock is 74.22 MHz, −0.04 %, so the sink's recovered fs is 47.98 kHz, within tolerance; record it). Audio InfoFrame 2ch, 48 kHz, 24-bit.
- `hdmi_loopback.py`: `AudioExtract` on the fabric receiver, samples into a 512-deep sys-domain FIFO readable by CSR (`audio_sample_data`, `audio_sample_valid`, `audio_sample_pop`), plus the latch CSRs.
- `run_loopback.py`: read N/CTS back (6144/74250), drain ≥ 256 samples, check left/right sequence equals the tone ROM sequence (bit-exact), block-start every 192 frames.
- `run_tx.py`: `arecord` 2 s from the Magewell, FFT (numpy) of each channel: peak at 1000 Hz ± 2 Hz, second-highest bin ≥ 40 dB down; report the level.
- Build both (announce), run T1 then T4 (announce), write `doc/reports/<date>-netv2-audio.md`.

### Task 7: docs and review

`doc/audio.md` (packet layouts with tables, IEC 60958 bits, N/CTS, delivery rules, the netv2-fpga divergences and how to interoperate), README features line, `LOG.md`/`TODO.md`; sub-agent review of the audio package with the same rigour as phases 1 and 2; fix; commit; push.
