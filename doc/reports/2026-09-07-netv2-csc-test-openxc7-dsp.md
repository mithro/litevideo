# NeTV2 CSC matrix toolchain test

Date: 2026-09-07 05:28 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `54e8a54a3098bf6d9903b78811a12ef51aceb768cc353b92757265a4d053ad3c`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| matrix identity: 64 pixels | FAIL | 60 wrong, e.g. (255, 255, 255) -> (0, 255, 255) expected (255, 255, 255); (255, 0, 0) -> (0, 0, 0) expected (255, 0, 0); (255, 0, 255) -> (0, 0, 255) expected (255, 0, 255) |
| matrix bt709 rgb->ycc: 64 pixels | FAIL | 60 wrong, e.g. (255, 255, 255) -> (188, 128, 128) expected (235, 128, 128); (255, 0, 0) -> (16, 128, 235) expected (63, 102, 235); (255, 0, 255) -> (32, 235, 230) expected (78, 214, 230) |
| matrix bt601 ycc->rgb: 64 pixels | FAIL | 58 wrong, e.g. (255, 255, 255) -> (184, 125, 255) expected (255, 125, 255); (255, 0, 0) -> (0, 136, 20) expected (74, 255, 20); (255, 0, 255) -> (184, 0, 20) expected (255, 225, 20) |
| matrix rgb full->limited: 64 pixels | FAIL | 60 wrong, e.g. (255, 255, 255) -> (16, 235, 235) expected (235, 235, 235); (255, 0, 0) -> (16, 16, 16) expected (235, 16, 16); (255, 0, 255) -> (16, 16, 235) expected (235, 16, 235) |

## Notes

- openFPGALoader: Warning: remote port forwarding failed for listen path /home/tim/.ssh/clipboard.sock
