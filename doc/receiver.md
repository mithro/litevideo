# HDMI receiver

`litevideo/hdmi/receiver.py` turns the three channel-aligned 10-bit TMDS
characters per pixel clock that an input PHY delivers into a LiteX video
stream, a packet stream and CSR-visible state. Like the transmitter it is
PHY independent: on 7-series the characters come from the existing
`litevideo.input` capture path (`S7DataCapture` → `CharSync` → `Decoding`
→ `ChanSync`), whose `data_outN.raw` outputs and `chan_synced` feed
`HDMIReceiver.sink` (`raw_layout`, `valid` = channels synchronised).

```
pads ─► S7MMCMClocking ─► pix / pix1p25x / pix5x
pads ─► S7DataCapture ×3 ─► CharSync ×3 ─► Decoding ×3 ─► ChanSync ─► HDMIReceiver ─► source (video_data_layout)
                                                                          │            ─► packet_source (packet_rx_layout)
                                                                          ├─ TMDSCharacterDecoder ×3   character class per channel
                                                                          ├─ HDMIPeriodDecoder         control / preamble / guard / video / island
                                                                          ├─ DataIslandDecoder         32-character packets, BCH ECC
                                                                          ├─ TimingMeasure             hactive, vactive, htotal, vtotal, frames
                                                                          ├─ AVI InfoFrame capture     y, c, q, vic, m, checksum
                                                                          └─ AudioExtract (+AsyncFIFO) samples, N/CTS, Audio InfoFrame
```

## Period decoding

`HDMIPeriodDecoder` (`litevideo/hdmi/period.py`, latency 2) classifies
every character on the three channels with `TMDSCharacterDecoder`
(`litevideo/hdmi/tmds.py`) and follows HDMI 1.3 §5.2.1 (Figure 5-1):

* **Control period**: any of the four control characters on channel 0
  (Table 5-1); HSYNC/VSYNC are taken from channel 0 (§5.4.2) as they
  arrive, so sync edges inside an island are honoured.
* **Video preamble**: CTL0 = 1, CTL2 = 0 on channels 1 and 2 for 8 characters
  (Table 5-2, §5.2.1.1). The following two characters are the video guard
  band (Table 5-5) and are consumed **by count**, not by matching their
  value, because an ordinary pixel may TMDS-encode to the same 10-bit word
  (0x55/0xAB/0x55). DE rises on the first character after them.
* **Data preamble**: CTL0 = 1, CTL2 = 1 for 8 characters, then the leading
  guard band (channel 0 = TERC4 of `1 1 VSYNC HSYNC`, channels 1 and 2 =
  `0b0100110011`), then the island, ended by the trailing guard band
  (§5.2.3.3, Table 5-6). Islands are 32×n characters; the decoder leaves
  the island when a control character appears (`error` counts islands
  ended without a trailing guard band).
* `dvi_mode` (`control.dvi_mode`) ignores preambles: DE is simply "not a
  control character", the DVI 1.0 rule (no preambles or guard bands).

The source stream carries `de/hsync/vsync/r/g/b` in `video_data_layout`
(`litex.soc.cores.video`); `r/g/b` are the TMDS-decoded 8-bit values of
channels 2/1/0, whatever the pixel encoding, and the AVI InfoFrame says
what they mean (phase 4 converts them).

## Packets

`DataIslandDecoder` (`litevideo/hdmi/island/decoder.py`) reassembles the
32-character packets: the header bit is channel 0 bit 2, subpacket *k*
takes bit *k* of channels 1 and 2 (§5.2.3.4, Figure 5-8). The 8-bit BCH
ECC on the header and each subpacket is checked with the same
`bch_step()` LFSR the encoder uses (`litevideo/hdmi/bch.py`, generator
1 + x⁶ + x⁷ + x⁸ from §7.7). `packet_source` carries `header`, `sub0..3`
and `ecc_ok`; `islands`, `packets` and `ecc_errors` count.

AVI InfoFrames (packet type 0x82, CEA-861-D §6.4 and Tables 7-12) are
latched into the `avi` CSR when the ECC is good: `y` (pixel encoding),
`c` (colorimetry), `q` (RGB quantization range), `vic`, `m` (aspect ratio),
and `checksum_ok` (the InfoFrame checksum over header and payload sums to
zero, CEA-861-D §6.1). `valid` says at least one has been received.

## Timing

`TimingMeasure` latches the active pixels per line at each DE fall, the
total characters per line at each HSYNC leading edge, and the active lines
and total lines per frame at each VSYNC leading edge. `status` and
`timing` expose them; `frames` counts VSYNC edges. A 1024x768@60 source
reports 1024/768 active and 1344/806 total (VESA DMT 1024x768 60 Hz).

## Audio

With `with_audio=True`, `AudioExtract` (`litevideo/hdmi/audio/extract.py`,
see `doc/audio.md`) unpacks Audio Sample Packets into IEC 60958 subframes
and latches N/CTS from Audio Clock Regeneration packets and the Audio
InfoFrame fields. The subframes go to an `AudioSampleCapture`
(`litevideo/hdmi/audio/capture.py`): software writes its `arm` CSR, the
512-entry `AsyncFIFO` is cleared and fills once with the next contiguous
subframes (`sample[23:0]`, `channel[26:24]`, `B/C/P/V` flags) and stops
when full, and software drains it over `sample_data` / `sample_valid` /
`sample_pop`; in a SoC these appear as `<receiver>_audio_capture_*`. A
free-running FIFO that overflows would admit one subframe per pop and its
content would not be a contiguous stream. `audio_dropped` counts packets
discarded because of a BCH ECC error before extraction. This is a bench
interface; a DMA/stream sink is the intended production path (see
`TODO.md` on the `claude-notes` branch).

## Front end and clocking (7-series)

`litevideo/input/clocking.py` `S7MMCMClocking(pads, clkin_freq)` derives
`pix`, `pix1p25x` (ISERDES CLKDIV, 8:10 gearbox) and `pix5x` (DDR bit
clock) from the TMDS clock with LiteX's `S7MMCM`, so any input rate the
MMCM can lock to is one parameter rather than a hand-computed table; the
Pi 5's EDID-less 1024x768 mode (65 MHz) uses VCO 1300 MHz with dividers
20/16/4. The `S7DataCapture` phase detector (master/slave ISERDES with
IDELAYE2, the classic HDMI2USB scheme) still needs software to walk the
delays: `bench/netv2/host/uartbone.py align` implements two methods: the
`calibrate_delays` / `adjust_phase` loop of
[HDMI2USB-litex-firmware `firmware/hdmi_in0.c`](https://github.com/timvideos/HDMI2USB-litex-firmware/blob/master/firmware/hdmi_in0.c)
(reset both IDELAYs, preload the slave by a quarter bit at 78 ps per tap,
then step master and slave together on `too_late` / `too_early`), and the
default `--eye` scan, which sweeps the master tap and uses the channel
synchroniser as the eye indicator (joint sweep, then per-channel
refinement). On the Raspberry Pi 5 source the phase detector reported
"too early" inside the good window and the loop walked out of it, while the
eye scan shows 5-tap windows one bit period (18 taps at 74.25 MHz) apart;
the input MMCM and IDELAYs are reset first, which is needed after the source
clock restarts (`doc/reports/2026-09-07-netv2-rx-720p.md`).

## Testing

* `test/test_hdmi_period.py`, `test_hdmi_period_edges.py`: period FSM
  against `litevideo/hdmi/model.py` token streams, including the guard-band
  spoof pixel and syncs changing inside an island.
* `test/test_hdmi_island_decoder.py`, `test_hdmi_island_roundtrip.py`:
  packet reassembly, ECC verdicts with corrupted header/subpacket bits.
* `test/test_hdmi_receiver.py`: whole receiver on model frames (timing,
  AVI latch, packet counts).
* Hardware: `bench/netv2/hdmi_rx.py` with `bench/netv2/host/run_rx.py`
  (tier T3 in `doc/testing.md`), results under `doc/reports/`.
