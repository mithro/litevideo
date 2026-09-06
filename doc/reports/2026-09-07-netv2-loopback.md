# NeTV2 tier T1: HDMI transmitter fabric loopback

Date: 2026-09-07 01:02 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `988b5505e739e6459fc6b62f9c9cfc038863c65181a18f503557c0872f635f5b`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| timing measured | PASS | hs2de=260 valid=1 max_packets=6 |
| frames advance ~60/s | PASS | +253 frames in 4.22 s = 60.0 fps |
| islands advance | PASS | +253 islands |
| rx packets advance | PASS | +254 packets |
| no ECC errors | PASS | +0 |
| no island errors | PASS | +0 |
| last packet is AVI InfoFrame | PASS | header=0x0d0282 |
| tx frame CRC = colour bars | PASS | 0x5757aec7 vs 0x5757aec7 |
| rx frame CRC = tx frame CRC | PASS | 0x5757aec7 |
| period histogram has VIDEO and DATA_ISLAND | PASS | {'video': 49598, 'island': 8128} |
| one packet (AVI) per frame | PASS | 1.00 packets/frame |
| AVMUTE adds a GCP per frame | PASS | 2.00 packets/frame |
| DVI mode stops islands | PASS | 3067 -> 3067 |

## Notes

- openFPGALoader: Warning: remote port forwarding failed for listen path /home/tim/.ssh/clipboard.sock

## Build

- Vivado 2025.2, `bench/netv2/hdmi_loopback.py --toolchain vivado`, a7-100, run under `scripts/limited.py`.
- Timing: all constraints met (0 violations; derived MMCM clocks 74.219 MHz pix / 371.094 MHz pix5x).
- Utilisation (placed): 1448 LUTs, 2939 FFs, 0 BRAM, 0 DSP, 8 OSERDESE2, 1 MMCME2_ADV, 1 PLLE2_ADV, 4 BUFG.
- Earlier builds: the first had a duplicated period constraint on the MMCM outputs (WNS -1.9 ns artefact); the second showed the upstream OSERDES OCE register in the pix domain failing the pix -> pix5x path (WNS -1.26 ns), fixed by tying OCE high (commit 618eee6). The preliminary runs with that second bitstream (`*-prelim.md`) already passed functionally because OCE is static after reset.
