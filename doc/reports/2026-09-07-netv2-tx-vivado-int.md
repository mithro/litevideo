# NeTV2 tier T4: HDMI transmitter into the Magewell capture

Date: 2026-09-07 05:11 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `117209942f75b4e3e552efdebf0ad7594fbff704dc33b5b8c03f5eaf95d8c622`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| transmitter running | PASS | status=0xd0104 frames=566 |
| hdmi mode colour bars captured | PASS | size=(1280, 720) bars=[(253, 253, 253), (251, 255, 9), (19, 255, 251), (17, 255, 6), (235, 0, 245), (231, 0, 1), (1, 0, 243), (0, 0, 0)] |
| dvi mode colour bars captured | PASS | size=(1280, 720) bars=[(253, 253, 253), (251, 255, 9), (19, 255, 251), (17, 255, 6), (235, 0, 245), (231, 0, 1), (1, 0, 243), (0, 0, 0)] |
| AVMUTE capture (informational) | PASS | size=(1280, 720) bars=[(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)] (all black: no signal?) |
| Magewell audio capture: 1 kHz tone on both channels | FAIL | 48000 Hz, 96000 frames; ch0: peak 993.3 Hz, 24 dB above the next line, rms 0.354 FS; ch1: peak 993.3 Hz, 24 dB above the next line, rms 0.354 FS |

## Notes

- openFPGALoader: Warning: remote port forwarding failed for listen path /home/tim/.ssh/clipboard.sock
- Magewell format: Format Video Capture: Width/Height : 1280/720 Pixel Format : 'YUYV' (YUYV 4:2:2) Field : None Bytes per Line : 2560 Size Image : 1843200 Colorspace : sRGB Transfer Function : Rec. 709 YCbCr/HSV Encoding: Rec. 709 Quantization : Default (maps to Limited Range) Flags :
