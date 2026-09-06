# HDMI transmitter

`litevideo/hdmi/transmitter.py` turns a LiteX video stream into an HDMI
character stream with data islands. It is PHY independent: the characters go
to `litevideo/output/hdmi/s7.py`'s `S7HDMIOutPHY(mode="raw")` (or any other
10-bit-per-channel serialiser).

```
LiteX VideoTimingGenerator ─► ColorBarsPattern / VideoFrameBuffer ─► HDMITransmitter ─► S7HDMIOutPHY(raw) ─► pads
                                       (video_data_layout)              │
                                                                        ├─ HDMIFramer        pixels → TMDS, preambles, guard bands, islands
                                                                        ├─ PacketScheduler   fixed priority: [audio...] GCP, AVI
                                                                        ├─ GCPGenerator      AVMUTE set/clear once per frame
                                                                        └─ AVIInfoFrameGenerator  once per frame from CSRs
```

## Framer

`HDMIFramer` (`litevideo/hdmi/framer.py`) runs one pixel per clock. It
delays the incoming stream by 11 characters so that it sees DE rise before
the TMDS encoders do, and uses that lookahead to send the 8-character video
preamble (CTL0 = 1, HDMI 1.3 Table 5-2) and the 2-character video guard
band (Table 5-5) immediately before the first pixel. Control periods carry
HSYNC/VSYNC on channel 0 (§5.4.2). Total latency from `sink` to `source` is
11 + 4 (encoder) = 15 characters.

### Data island placement

Islands are anchored to the HSYNC leading edge: an island starts
`MIN_CONTROL_PERIOD` (12) characters after the edge, on every line, active
or blanking. The framer measures `hs2de`, the distance from the HSYNC
leading edge to the DE rise, on active lines, and derives how many packets
fit:

```
room        = hs2de - (12 control + 4 control after the island + 8 preamble + 2 guard band + 12 island framing + 2 margin)
max_packets = min(18, room // 32)           (HDMI 1.3 §5.2.3.2: 1 to 18 packets, control periods >= 12)
```

| Timing (CEA-861-D) | sync + back porch = `hs2de` | `max_packets` |
|---|---|---|
| 1280x720p60 (VIC 4): sync 40, back porch 220 | 260 | 6 |
| 1920x1080p60 (VIC 16): sync 44, back porch 148 | 192 | 4 |
| 640x480p60 (VIC 1): sync 96, back porch 48 | 144 | 3 |
| LiteX built-in `1280x720@60Hz` (sync 220 after DE, back porch 110) | 150 | 3 |

Until `hs2de` has been measured (the first line) no island is sent. The
line on which VSYNC rises carries no island, so its blanking is an Extended
Control Period of at least 32 characters (Table 5-4; sufficient at any frame
rate above 20 Hz). `DataIslandEncoder` keeps 4 control characters after
every trailing guard band, so consecutive islands are 12 control characters
apart. `dvi_mode` disables preambles, guard bands and islands.

## Packets

`PacketScheduler` is a fixed-priority arbiter; `HDMITransmitter` orders the
sources per HDMI §7.8.2: audio (phase 3, through `extra_packet_sinks`),
General Control, AVI InfoFrame. Generators produce one packet per VSYNC
leading edge and hold it until the framer accepts it in the next island
slot.

* **AVI InfoFrame** (CEA-861-D §6.4, version 2, 13 bytes): every field is a
  CSR (`avi_config`, `avi_config2`); the checksum is computed in gateware
  (HDMI Table 5-15: header and payload bytes sum to zero). Defaults: RGB,
  16:9, active format same as picture, VIC from the constructor.
* **General Control Packet** (HDMI §5.3.6, Table 5-17): while
  `control.avmute` is set a Set_AVMUTE packet is sent every frame; one
  Clear_AVMUTE packet follows when it is cleared.

## CSRs (`hdmi_tx_*`)

| Register | Fields |
|---|---|
| `control` | `enable_islands` (1), `dvi_mode` (0), `avmute` (0), `avi_enable` (1) |
| `avi_config` | `y, a, b, s, c, m, r, itc, ec, q, sc, vic` (CEA-861-D Tables 8 to 12) |
| `avi_config2` | `yq, cn, pr` |
| `status` | `hs2de` [15:0], `hs2de_valid` [16], `max_packets` [21:17] |
| `island_count`, `frame_count` | 32-bit counters (monitoring only: they cross clock domains bit by bit) |

## Bench on the NeTV2

`bench/netv2/hdmi_tx.py` builds a CPU-less SoC (CSRs over uartbone on the
Pi's `/dev/ttyAMA0`) driving CEA 720p60 colour bars with an AVI InfoFrame
(VIC 4) on `hdmi_out` 0; `bench/netv2/hdmi_loopback.py` adds the receiver
protocol layer in the fabric with counters, a period histogram and a
frame CRC. Host scripts under `bench/netv2/host/` load the bitstream
(volatile), read the CSRs and grab frames from the Magewell capture device.
The pixel clock comes from a LiteX `S7MMCM` fed by the 50 MHz oscillator;
the configuration it chose and the timing/utilisation results are recorded
in `doc/reports/`.

## Verification

Simulation: `test/test_hdmi_framer.py` feeds the framer's characters back
into the phase-1 period and island decoders and checks the pixels, the
packets (ECC good), the control-period rules and the Extended Control
Period line; `test/test_hdmi_transmitter.py` checks the per-frame AVI
InfoFrame and the AVMUTE set/clear sequence through the CSRs.

Hardware: see `doc/reports/` (tier T1 fabric loopback, tier T4 Magewell
capture) once the runs have been made.
