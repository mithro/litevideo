# NeTV2 tier T1: HDMI transmitter fabric loopback

Date: 2026-09-07 02:19 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `d9c7c3cd8f6c8f50e551e251f3e53d3edb60c5c22e3d868e9ecbdfc21d760780`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| timing measured | PASS | hs2de=260 valid=1 max_packets=6 |
| frames advance ~60/s | PASS | +292 frames in 4.87 s = 60.0 fps |
| islands advance | PASS | +219129 islands |
| rx packets advance | PASS | +228411 packets |
| no ECC errors | PASS | +0 |
| no island errors | PASS | +0 |
| last packet is a known type | PASS | header=0x000102 (ASP) |
| tx frame CRC = colour bars | PASS | 0x5757aec7 vs 0x5757aec7 |
| rx frame CRC = tx frame CRC | PASS | 0x5757aec7 |
| period histogram has VIDEO and DATA_ISLAND | PASS | {'video': 54839, 'island': 34880} |
| two non-audio packets (AVI, Audio InfoFrame) per frame | PASS | 2.00 packets/frame |
| AVMUTE adds a GCP per frame | PASS | 3.00 packets/frame |
| DVI mode stops islands | PASS | 2312914 -> 2312914 |
| format RGB full (default): rx frame CRC = model | PASS | 0x5757aec7 vs 0x5757aec7 (tx input 0x5757aec7) |
| format RGB limited (Q=1): rx frame CRC = model | PASS | 0x57e066cb vs 0x57e066cb (tx input 0x5757aec7) |
| format RGB default Q on 720p: rx frame CRC = model | PASS | 0x57e066cb vs 0x57e066cb (tx input 0x5757aec7) |
| format YCbCr 4:4:4 BT.709: rx frame CRC = model | PASS | 0x4f2a0e01 vs 0x4f2a0e01 (tx input 0x5757aec7) |
| format YCbCr 4:4:4 BT.601: rx frame CRC = model | PASS | 0x4124fd3c vs 0x4124fd3c (tx input 0x5757aec7) |
| format YCbCr 4:2:2 BT.709: rx frame CRC = model | PASS | 0xcad0f7cf vs 0xcad0f7cf (tx input 0x5757aec7) |
| format YCbCr 4:2:2 C default: rx frame CRC = model | PASS | 0xcad0f7cf vs 0xcad0f7cf (tx input 0x5757aec7) |
| ACR N/CTS received | PASS | N=6144 CTS=74250 (acr packets 141871) |
| Audio InfoFrame received (2ch, 48 kHz, 24 bit) | PASS | cc=1 ct=0 sf=3 ss=3 ca=0 valid=1 |
| audio lossless in steady state | PASS | over 8.2 s: frames +392762 (47964/s), subframes extracted +785522, asps +378143, acrs +8182 (999/s), overruns +0, dropped +0 |
| extracted tone is the 1 kHz ROM sine | PASS | 256 frames, peak 938 Hz (bin 188 Hz), block starts [168] |

## Notes

- openFPGALoader: Warning: remote port forwarding failed for listen path /home/tim/.ssh/clipboard.sock
