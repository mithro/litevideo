# NeTV2 tier T4: HDMI transmitter into the Magewell capture

Date: 2026-09-07 00:55 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `a06b96b4994c5027f8b04b17c52a61214e9b45867cb7e85828172d61d1a9530f`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| transmitter running | PASS | status=0xd0104 frames=24967 |
| hdmi mode colour bars captured | PASS | size=(1280, 720) bars=[(253, 253, 253), (251, 255, 9), (19, 255, 251), (17, 255, 6), (235, 0, 245), (231, 0, 1), (1, 0, 243), (0, 0, 0)] |
| dvi mode colour bars captured | PASS | size=(1280, 720) bars=[(253, 253, 253), (251, 255, 9), (19, 255, 251), (17, 255, 6), (235, 0, 245), (231, 0, 1), (1, 0, 243), (0, 0, 0)] |
| AVMUTE capture (informational) | PASS | size=(1280, 720) bars=[(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)] (all black: no signal?) |

## Notes

- Magewell format: Format Video Capture: Width/Height : 1280/720 Pixel Format : 'YUYV' (YUYV 4:2:2) Field : None Bytes per Line : 2560 Size Image : 1843200 Colorspace : sRGB Transfer Function : Rec. 709 YCbCr/HSV Encoding: Rec. 709 Quantization : Default (maps to Limited Range) Flags :
