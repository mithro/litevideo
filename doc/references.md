# References

Specifications and external code this library follows. Section and table
numbers quoted in the source refer to these documents.

- **HDMI Specification 1.3** (public copy hosted by the MIT 6.205 course):
  <https://fpga.mit.edu/6205/_static/F24/default_files/CEC_HDMI_Specification.pdf>.
  Used for: §5.2 operating modes and preambles, §5.2.3 data islands
  (placement §5.2.3.2, guard bands §5.2.3.3, packet construction §5.2.3.4,
  ECC §5.2.3.5), §5.3 packet definitions, §5.4.2 control characters, §5.4.3
  TERC4, §5.4.4 video coding, §6.5 pixel encodings, §6.6 quantization
  ranges, §6.7 colorimetry, §7.2 audio clock regeneration (N/CTS tables
  7-1 to 7-3), §7.8 packet delivery rules, §8.2 InfoFrames.
- **CEA-861-D** (archive.org): <https://archive.org/download/CEA-861-D/CEA-861-D.pdf>.
  Used for: §6.4 AVI InfoFrame (Tables 7 to 12), §6.6 Audio InfoFrame
  (Tables 16 to 22), video identification codes.
- **DVI 1.0**: <https://glenwing.github.io/docs/DVI-1.0.pdf>. Used for: §3.2
  TMDS encoder and §3.3 decoder algorithms, control characters.
- **hdl-util/hdmi** (SystemVerilog HDMI 1.4a transmitter with audio):
  <https://github.com/hdl-util/hdmi>. Used as an independent reference for
  the BCH ECC LFSR (`src/packet_assembler.sv`), island placement
  (`src/hdmi.sv`), packet scheduling (`src/packet_picker.sv`) and the audio
  and InfoFrame packet layouts.
- **HDMI 1.4b Compliance Test Specification** requirement (quoted in
  hdl-util/hdmi issue #35): channel 0 bit 3 is 0 on the first character
  after the leading guard band and 1 on every other character before the
  trailing guard band.
- **LiteX video cores** (tag 2026.04): `litex/soc/cores/video.py`
  (`video_timing_layout`, `video_data_layout`, timing generator, frame
  buffer, DVI PHYs) and `litex/soc/cores/code_tmds.py` (TMDS encoder).
- **Xilinx XAPP930**: colour space conversion equations used by
  `litevideo/csc/`.
- **AES3-2009** (free from the AES): <https://www.aes.org/publications/standards/search.cfm?docID=12>.
  IEC 60958 subframe format (V/U/C/P bits, channel status block).
- **NeTV2 modernisation tree**: `AlphamaxMedia/netv2-fpga` branch `modern`
  (`docs/current/hdmi-audio-*.md`, `docs/testing/reports/`): prior HDMI
  audio embed/extract work on the same hardware; see
  `doc/hdmi-protocol.md` for where it diverges from the specification.
- **Board**: litex-boards `litex_boards/platforms/kosagi_netv2.py`;
  `mithro/fpgas-online-test-designs` `docs/hardware/netv2.md` (JTAG, UART,
  connector pinouts).
