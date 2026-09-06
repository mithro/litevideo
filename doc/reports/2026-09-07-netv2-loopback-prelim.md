# NeTV2 tier T1: HDMI transmitter fabric loopback

Date: 2026-09-07 00:54 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `a06b96b4994c5027f8b04b17c52a61214e9b45867cb7e85828172d61d1a9530f`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| timing measured | PASS | hs2de=260 valid=1 max_packets=6 |
| frames advance ~60/s | PASS | +252 frames in 4.20 s = 60.1 fps |
| islands advance | PASS | +252 islands |
| rx packets advance | PASS | +252 packets |
| no ECC errors | PASS | +0 |
| no island errors | PASS | +0 |
| last packet is AVI InfoFrame | PASS | header=0x0d0282 |
| tx frame CRC = colour bars | PASS | 0x5757aec7 vs 0x5757aec7 |
| rx frame CRC = tx frame CRC | PASS | 0x5757aec7 |
| period histogram has VIDEO and DATA_ISLAND | PASS | {'video': 17119, 'island': 8064} |
| one packet (AVI) per frame | PASS | 1.00 packets/frame |
| AVMUTE adds a GCP per frame | PASS | 2.00 packets/frame |
| DVI mode stops islands | PASS | 20381 -> 20381 |
