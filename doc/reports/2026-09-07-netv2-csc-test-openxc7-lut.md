# NeTV2 CSC matrix toolchain test

Date: 2026-09-07 05:27 ACST. Host: `tim@rpi5-netv2.welland.mithis.com`. Bitstream: `kosagi_netv2.bit` (SHA-256 `51034f98f2173a26090577bbaaf31ec35d73df1689472f274de69633b0a93ceb`), volatile JTAG load.

| Check | Result | Detail |
|---|---|---|
| matrix identity: 64 pixels | PASS | all match |
| matrix bt709 rgb->ycc: 64 pixels | PASS | all match |
| matrix bt601 ycc->rgb: 64 pixels | PASS | all match |
| matrix rgb full->limited: 64 pixels | PASS | all match |
