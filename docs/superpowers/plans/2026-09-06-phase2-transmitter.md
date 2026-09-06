# LiteVideo HDMI phase 2: transmitter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A complete HDMI transmitter protocol stack (framer with data island placement, packet scheduler, AVI InfoFrame and General Control Packet generators, CSR-controlled `HDMITransmitter`) verified in simulation against the phase-1 receiver protocol layer, then on the NeTV2 in the fabric (tier T1) and through the 7-series SERDES into the Magewell capture device (tier T4).

**Architecture:** `HDMIFramer` takes a LiteX `video_data_layout` stream (one pixel per pixel clock) and a packet stream, and produces the three 10-bit characters per clock: TMDS-encoded pixels, control characters with the right CTL codes, video preamble and guard band before every DE rise (found by looking 10 characters ahead through a delay line), and data islands anchored 12 characters after each HSYNC leading edge, sized from the measured sync-to-DE distance so they always fit. `PacketScheduler` arbitrates generators by fixed priority. `HDMITransmitter` wraps framer, scheduler and generators with CSRs. Board glue (clocking, PHY, uartbone, host scripts) lives under `bench/netv2/`.

**Tech Stack:** as phase 0/1, plus `litex-boards` (NeTV2 platform), `pyserial` (host client), Vivado 2025.2 through `scripts/limited.py`, openFPGALoader on `rpi5-netv2`, ffmpeg/v4l2 on the Pi for Magewell capture.

**Working rules:** same as the phase 0/1 plan (worktree `.worktrees/hdmi`, branch `hdmi-support`, `uv run`, no `python -c`/heredocs//tmp, commit trailer, file headers, spec citations). Hardware rules: announce every `rpi5-netv2` load to the peer session "netv2 firmware upgrade and hdcp work" through SendMessage and wait for no objection; one Vivado run at a time under `scripts/limited.py`; never touch `rpi3-netv2`.

---

## File structure

| Path | Responsibility |
|---|---|
| `litevideo/hdmi/framer.py` | `HDMIFramer`: pixels + packets → characters; preamble/guard band insertion; island placement |
| `litevideo/hdmi/scheduler.py` | `PacketScheduler`: fixed-priority arbiter of packet sources |
| `litevideo/hdmi/infoframe.py` | `infoframe_bytes` helpers, `AVIInfoFrameGenerator`, `GCPGenerator` |
| `litevideo/hdmi/transmitter.py` | `HDMITransmitter`: framer + scheduler + generators + CSRs |
| `litevideo/hdmi/model.py` | + `infoframe_packet`, `avi_infoframe`, `gcp_packet`, `frame_tokens` |
| `litevideo/hdmi/island/encoder.py` | live HSYNC/VSYNC instead of latched (fix) |
| `test/test_hdmi_framer.py`, `test/test_hdmi_scheduler.py`, `test/test_hdmi_infoframe.py`, `test/test_hdmi_transmitter.py` | tests |
| `bench/netv2/__init__.py`, `bench/netv2/common.py` | NeTV2 platform, CRG (sys 50 MHz, pix/pix5x from a fractional MMCM), CPU-less SoC with uartbone |
| `bench/netv2/hdmi_loopback.py` | T1: transmitter characters fed to the phase-1 decoders in fabric; counters and frame CRC over CSRs |
| `bench/netv2/hdmi_tx.py` | T4: colour bars + InfoFrames on `hdmi_out` 0 |
| `bench/netv2/host/uartbone.py` | self-contained CSR client over `/dev/ttyAMA0` (runs on the Pi with pyserial) |
| `bench/netv2/host/rig.py` | desktop-side helpers: build, copy, load, run client, capture frames |
| `bench/netv2/host/run_loopback.py`, `bench/netv2/host/run_tx.py` | tier T1 and T4 test scripts producing `doc/reports/<date>-netv2-*.md` |
| `doc/transmitter.md` | block diagram, CSRs, placement algorithm, clocking, latencies |

---

### Task 1: live syncs in the island encoder

**Files:** `litevideo/hdmi/island/encoder.py`, `test/test_hdmi_island_encoder.py`

HDMI §5.2.3.1: every island character carries the current HSYNC/VSYNC on channel 0 bits 0 and 1. The phase-1 encoder latched them at island start; with islands anchored 12 characters after the HSYNC leading edge the sync pulse (40 characters at 720p) ends inside the island, so the latch would misreport it.

- [ ] **Step 1: Test.** In `test/test_hdmi_island_encoder.py` add:

```python
    def test_live_syncs_inside_island(self):
        prng = random.Random(24)
        p = random_packet(prng)
        dut = DataIslandEncoder()
        beats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}}]
        out = []

        @passive
        def collect():
            while True:
                if (yield dut.source.valid):
                    out.append(((yield dut.source.c0), (yield dut.hsync), (yield dut.vsync)))
                yield

        def control():
            yield dut.start.eq(1)
            yield dut.hsync.eq(1)
            for i in range(80):
                if i == 30:
                    yield dut.hsync.eq(0)   # sync ends during the packet
                yield

        run_simulation(dut, [stream_inserter(dut.sink, beats), collect(), control()])
        self.assertEqual(len(out), 8 + 2 + 32 + 2)
        for c0, hs, vs in out:
            n = model.terc4_decode(c0)
            if n is None:            # preamble control character
                self.assertEqual(c0, control_tokens[(vs << 1) | hs])
            else:
                self.assertEqual(n & 0b11, (vs << 1) | hs)
```

- [ ] **Step 2: Run** `uv run pytest test/test_hdmi_island_encoder.py -v` → the new test fails (characters after cycle 30 still carry HSYNC=1).

- [ ] **Step 3: Fix.** In `encoder.py` delete `hsync_l`/`vsync_l` and their `NextValue`s; use `self.hsync`/`self.vsync` directly in `n0`, `ctl0` and `gb0`. Update the docstring ("carry the live HSYNC/VSYNC inputs on every character").

- [ ] **Step 4: Run** the whole suite: `uv run pytest -q` → all pass (the model's `island_tokens` uses constant syncs, so existing tests are unaffected).

- [ ] **Step 5: Commit** `hdmi/island: carry live HSYNC/VSYNC on every island character`.

### Task 2: model additions (InfoFrames, GCP, frames)

**Files:** `litevideo/hdmi/model.py`, `test/test_hdmi_model.py`

- [ ] **Step 1: Tests** (append to `test/test_hdmi_model.py`):

```python
class TestInfoFrameModel(unittest.TestCase):
    def test_checksum_makes_sum_zero(self):
        p = model.infoframe_packet(PacketType.AVI_INFOFRAME, 2, [0x10, 0x28, 0x00, 0x04, 0x00] + [0] * 8)
        total = sum(p.header_bytes) + sum(b for s in p.subpacket_bytes for b in s)
        self.assertEqual(total & 0xFF, 0)
        self.assertEqual(p.header_bytes, [0x82, 0x02, 13])

    def test_avi_defaults(self):
        p = model.avi_infoframe(vic=4)
        # CEA-861-D Table 8..12: PB1 = {0, Y1 Y0, A0, B1 B0, S1 S0}; RGB, no bars, no scan info.
        self.assertEqual(p.subpacket_bytes[0][1], 0x00)
        # PB2 = {C1 C0, M1 M0, R3..R0}: colorimetry none, aspect 16:9 for VIC 4, active format same as picture.
        self.assertEqual(p.subpacket_bytes[0][2], 0x28)
        self.assertEqual(p.subpacket_bytes[0][4], 4)        # PB4 = VIC

    def test_gcp(self):
        p = model.gcp_packet(set_avmute=1)
        self.assertEqual(p.header_bytes, [0x03, 0, 0])
        self.assertEqual([s[0] for s in p.subpacket_bytes], [0x01] * 4)   # SB0 bit0 = Set_AVMUTE
        p = model.gcp_packet(clear_avmute=1)
        self.assertEqual([s[0] for s in p.subpacket_bytes], [0x10] * 4)   # SB0 bit4 = Clear_AVMUTE


class TestFrameModel(unittest.TestCase):
    def test_frame_tokens_shape(self):
        timing = dict(hactive=16, hfront=4, hsync=8, hback=20, vactive=2, vfront=1, vsync=1, vback=1)
        frames = model.frame_tokens(timing, nframes=1)
        line = 16 + 4 + 8 + 20
        self.assertEqual(len(frames), line * 5)
```

- [ ] **Step 2: Implement** in `model.py`:

```python
# InfoFrames and control packets ------------------------------------------------------------------

def infoframe_packet(type_code, version, data_bytes):
    """HDMI 1.3 Tables 5-14/5-15: HB0 = type, HB1 = version, HB2 = length (≤ 27),
    PB0 = checksum so that all header and payload bytes sum to zero mod 256."""
    assert 1 <= len(data_bytes) <= 27
    header = [type_code & 0xFF, version & 0xFF, len(data_bytes)]
    checksum = (-(sum(header) + sum(data_bytes))) & 0xFF
    payload = [checksum] + list(data_bytes) + [0] * (27 - len(data_bytes))
    subs = [payload[7 * k:7 * k + 7] for k in range(4)]
    return Packet(header, subs)


def avi_infoframe(vic, y=0, a=0, b=0, s=0, c=0, m=None, r=8, itc=0, ec=0, q=0, sc=0, pr=0, yq=0, cn=0, bars=(0, 0, 0, 0)):
    """CEA-861-D §6.4 Tables 7 to 12 (version 2, 13 data bytes).

    y: 0 RGB, 1 YCbCr 4:2:2, 2 YCbCr 4:4:4. m: picture aspect (1 4:3, 2 16:9);
    defaults to 16:9 for VIC >= 4 as CEA-861-D Table 3 lists those formats.
    r: active format aspect ratio (8 = same as picture). bars: top, bottom,
    left, right line/pixel numbers (only meaningful when b != 0)."""
    if m is None:
        m = 2 if vic >= 4 else 1
    db1 = ((y & 3) << 5) | ((a & 1) << 4) | ((b & 3) << 2) | (s & 3)
    db2 = ((c & 3) << 6) | ((m & 3) << 4) | (r & 0xF)
    db3 = ((itc & 1) << 7) | ((ec & 7) << 4) | ((q & 3) << 2) | (sc & 3)
    db4 = vic & 0x7F
    db5 = ((yq & 3) << 6) | ((cn & 3) << 4) | (pr & 0xF)
    top, bottom, left, right = bars
    db6_13 = [top & 0xFF, top >> 8, bottom & 0xFF, bottom >> 8, left & 0xFF, left >> 8, right & 0xFF, right >> 8]
    return infoframe_packet(PacketType.AVI_INFOFRAME, 2, [db1, db2, db3, db4, db5] + db6_13)


def gcp_packet(set_avmute=0, clear_avmute=0, cd=0, pp=0, default_phase=0):
    """HDMI 1.3 §5.3.6 Tables 5-16/5-17: four identical subpackets."""
    sb0 = (set_avmute & 1) | ((clear_avmute & 1) << 4)
    sb1 = (cd & 0xF) | ((pp & 0xF) << 4)
    sb2 = (default_phase & 1) << 2
    sub = [sb0, sb1, sb2, 0, 0, 0, 0]
    return Packet([PacketType.GCP, 0, 0], [list(sub) for _ in range(4)])


def frame_tokens(timing, nframes=1, islands=None, pixels=None):
    """Whole frames of characters plus per-character (de, hsync, vsync) for
    transmitter tests. ``timing`` keys: hactive hfront hsync hback vactive
    vfront vsync vback (positive sync pulses). ``islands`` is an optional dict
    {line_index: [Packet, ...]} placed 12 characters after the HSYNC leading
    edge of that line (the framer's placement rule).

    Video lines: pixels | control | [island] | control | video preamble | video guard band
    Blank lines : control | [island] | control (no preamble/guard band since no DE follows)
    Returns a list of (c0, c1, c2, de, hsync, vsync)."""
    ha, hf, hs, hb = timing["hactive"], timing["hfront"], timing["hsync"], timing["hback"]
    va, vf, vs, vb = timing["vactive"], timing["vfront"], timing["vsync"], timing["vback"]
    vtotal = va + vf + vs + vb
    islands = islands or {}
    out = []
    disparity = [0, 0, 0]
    for f in range(nframes):
        for y in range(vtotal):
            vsync = 1 if va + vf <= y < va + vf + vs else 0
            active = y < va
            next_active = ((y + 1) % vtotal) < va
            if pixels is None:
                row = [(((x + y) * 7) & 0xFF, ((x * 13) ^ y) & 0xFF, ((x + 2 * y) * 29) & 0xFF) for x in range(ha)]
            else:
                row = pixels[y]
            if active:
                for (c0, c1, c2) in video_tokens(row, disparity):
                    out.append((c0, c1, c2, 1, 0, vsync))
            else:
                for _ in range(ha):
                    out.append(control_chars(0, vsync) + (0, 0, vsync))
            # blanking: front porch (control), sync pulse, back porch
            blank = []
            for x in range(hf + hs + hb):
                hsync = 1 if hf <= x < hf + hs else 0
                blank.append([control_chars(hsync, vsync), hsync])
            packets = islands.get(y)
            if packets:
                start = hf + MIN_CONTROL_PERIOD
                toks = island_tokens(packets, hsync=1, vsync=vsync)
                # syncs are live inside the island: rebuild channel 0 per character
                for i, (c0, c1, c2) in enumerate(toks):
                    hsync = blank[start + i][1]
                    if i < PREAMBLE_LENGTH:
                        c0 = control_tokens[(vsync << 1) | hsync]
                    elif i < PREAMBLE_LENGTH + GUARD_BAND_LENGTH or i >= len(toks) - GUARD_BAND_LENGTH:
                        c0 = terc4_encode(data_gb_ch0_nibble(hsync, vsync))
                    else:
                        n0 = terc4_decode(c0) & 0b1100 | (vsync << 1) | hsync
                        c0 = terc4_encode(n0)
                    blank[start + i][0] = (c0, c1, c2)
            if next_active:
                for i in range(PREAMBLE_LENGTH):
                    x = hf + hs + hb - PREAMBLE_LENGTH - GUARD_BAND_LENGTH + i
                    blank[x][0] = control_chars(blank[x][1], vsync, PREAMBLE_VIDEO)
                for i in range(GUARD_BAND_LENGTH):
                    blank[-GUARD_BAND_LENGTH + i][0] = tuple(video_gb_tokens)
            for (c0, c1, c2), hsync in blank:
                out.append((c0, c1, c2, 0, hsync, vsync))
    return out
```

- [ ] **Step 3: Run** `uv run pytest test/test_hdmi_model.py -v` → all pass. If `test_avi_defaults` disagrees on PB2, re-derive from CEA-861-D Table 9 (C1 C0 bits 7:6, M1 M0 bits 5:4, R3..R0 bits 3:0) in `cea861d.txt` and fix the model, not the expected value, unless the table says otherwise.

- [ ] **Step 4: Commit** `hdmi/model: add InfoFrame, GCP and frame token generators`.

### Task 3: packet scheduler

**Files:** `litevideo/hdmi/scheduler.py`, `test/test_hdmi_scheduler.py`

- [ ] **Step 1: Test**

```python
#
# (header)
"""Fixed-priority packet arbiter."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi.scheduler import PacketScheduler

from test.common import stream_inserter, stream_collector


class TestPacketScheduler(unittest.TestCase):
    def test_priority_and_completeness(self):
        dut = PacketScheduler(n=3)
        a = [{"header": 0xA0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        b = [{"header": 0xB0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        c = [{"header": 0xC0 + i, "sub0": i, "sub1": 0, "sub2": 0, "sub3": 0} for i in range(4)]
        out = []
        run_simulation(dut, [
            stream_inserter(dut.sinks[0], a, valid_rand=50, seed=1),
            stream_inserter(dut.sinks[1], b, valid_rand=50, seed=2),
            stream_inserter(dut.sinks[2], c, valid_rand=50, seed=3),
            stream_collector(dut.source, ["header"], out, ready_rand=30),
        ])
        headers = [o["header"] for o in out]
        self.assertEqual(sorted(headers), sorted(x["header"] for x in a + b + c))
        # Within each source the order is preserved.
        for prefix in (0xA0, 0xB0, 0xC0):
            self.assertEqual([h for h in headers if h & 0xF0 == prefix], [prefix + i for i in range(4)])

    def test_highest_priority_wins_when_both_valid(self):
        dut = PacketScheduler(n=2)
        out = []

        def drive():
            yield dut.sinks[0].valid.eq(1); yield dut.sinks[0].header.eq(1)
            yield dut.sinks[1].valid.eq(1); yield dut.sinks[1].header.eq(2)
            yield dut.source.ready.eq(1)
            yield
            out.append((yield dut.source.header))
            self_ready0 = (yield dut.sinks[0].ready)
            out.append(self_ready0)
            yield

        run_simulation(dut, drive())
        self.assertEqual(out, [1, 1])
```

- [ ] **Step 2: Implement**

```python
"""Fixed-priority arbiter for data island packets.

``sinks[0]`` has the highest priority. A packet is handed to ``source`` whole
(one beat per packet, ``packet_layout``); the selected sink stays selected
until the beat is accepted, so a packet is never split or dropped. Priority
order in ``HDMITransmitter`` follows HDMI §7.8.2: Audio Sample Packets first,
then Audio Clock Regeneration, then General Control, then InfoFrames.
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *


class PacketScheduler(LiteXModule):
    def __init__(self, n):
        self.sinks  = [stream.Endpoint(packet_layout) for _ in range(n)]
        self.source = stream.Endpoint(packet_layout)

        # # #

        sel = Signal(max=max(n, 2))
        locked = Signal()
        # Pick the highest-priority valid sink while not locked on one.
        cases = {}
        for i in reversed(range(n)):
            self.comb += If(~locked & self.sinks[i].valid, sel.eq(i))
        self.sync += [
            If(self.source.valid & ~self.source.ready, locked.eq(1)),
            If(self.source.valid & self.source.ready, locked.eq(0)),
        ]
        sel_r = Signal(max=max(n, 2))
        self.sync += If(~locked, sel_r.eq(sel))
        current = Signal(max=max(n, 2))
        self.comb += current.eq(Mux(locked, sel_r, sel))
        for i in range(n):
            cases[i] = self.sinks[i].connect(self.source)
        self.comb += Case(current, cases)
```

Note: `stream.Endpoint.connect` returns a list of statements; using it inside `Case` connects valid/ready/payload of the selected sink only, so unselected sinks see `ready = 0`.

- [ ] **Step 3: Run** `uv run pytest test/test_hdmi_scheduler.py -v` → 2 passed. If `Case` refuses the `connect` lists, replace with explicit `If`/`Elif` chains assigning `source.valid`, `source.payload` fields and each `sink.ready`.

- [ ] **Step 4: Commit** `hdmi: add fixed-priority packet scheduler`.

### Task 4: InfoFrame and GCP generators

**Files:** `litevideo/hdmi/infoframe.py`, `test/test_hdmi_infoframe.py`

Generators run in the pixel domain and produce one `packet_layout` beat per `trigger` pulse (the transmitter pulses it on each VSYNC leading edge). Configuration arrives as a packed bus already synchronised into the pixel domain by the transmitter (which owns the CSRs), so the generators themselves are domain-agnostic and easy to test.

- [ ] **Step 1: Test**

```python
"""AVI InfoFrame and General Control Packet generators against the model."""

import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.infoframe import AVIInfoFrameGenerator, GCPGenerator, avi_fields_layout


def packet_from_source(src):
    header = (yield src.header)
    subs = []
    for k in range(4):
        subs.append((yield getattr(src, f"sub{k}")))
    return model.Packet.from_words(header, subs)


class TestAVIInfoFrameGenerator(unittest.TestCase):
    def test_matches_model(self):
        dut = AVIInfoFrameGenerator()
        got = []

        def gen():
            yield dut.fields.vic.eq(16); yield dut.fields.y.eq(2); yield dut.fields.c.eq(2)
            yield dut.fields.m.eq(2); yield dut.fields.r.eq(8); yield dut.fields.q.eq(1)
            yield dut.source.ready.eq(1)
            yield
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            for _ in range(8):
                if (yield dut.source.valid):
                    got.append((yield from packet_from_source(dut.source)))
                yield

        run_simulation(dut, gen())
        self.assertEqual(got, [model.avi_infoframe(vic=16, y=2, c=2, m=2, r=8, q=1)])

    def test_holds_until_accepted(self):
        dut = AVIInfoFrameGenerator()
        seen = []

        def gen():
            yield dut.fields.vic.eq(4)
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            for i in range(10):
                seen.append((yield dut.source.valid))
                if i == 6:
                    yield dut.source.ready.eq(1)
                yield
            yield dut.source.ready.eq(0)
            yield
            seen.append((yield dut.source.valid))

        run_simulation(dut, gen())
        self.assertIn(1, seen[:6])
        self.assertEqual(seen[-1], 0)


class TestGCPGenerator(unittest.TestCase):
    def test_set_and_clear(self):
        dut = GCPGenerator()
        got = []

        def gen():
            yield dut.source.ready.eq(1)
            # frame 1: avmute on -> Set_AVMUTE; frame 2: still on -> Set again; frame 3: off -> Clear; frame 4: nothing
            for avmute in (1, 1, 0, 0):
                yield dut.avmute.eq(avmute)
                yield dut.trigger.eq(1)
                yield
                yield dut.trigger.eq(0)
                for _ in range(6):
                    if (yield dut.source.valid):
                        got.append((yield from packet_from_source(dut.source)))
                    yield

        run_simulation(dut, gen())
        self.assertEqual(got, [model.gcp_packet(set_avmute=1), model.gcp_packet(set_avmute=1), model.gcp_packet(clear_avmute=1)])
```

- [ ] **Step 2: Implement**

```python
"""InfoFrame and General Control Packet generators.

An InfoFrame packet (HDMI 1.3 §5.3.5, Tables 5-14/5-15) has HB0 = type,
HB1 = version, HB2 = length and PB0 = checksum, chosen so that the byte-wise
sum of the three header bytes and all payload bytes is zero. The AVI
InfoFrame fields are CEA-861-D §6.4 Tables 7 to 12 (version 2, 13 bytes).
The General Control Packet (§5.3.6, Tables 5-16/5-17) carries AVMUTE and
colour depth in four identical subpackets.

Each generator emits one packet per ``trigger`` pulse and holds it valid
until the scheduler accepts it. A new trigger while a packet is pending
replaces it (InfoFrames describe the current state, so the latest wins).
"""

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from litevideo.hdmi.common import *

# AVI InfoFrame fields, CEA-861-D Table 8 to Table 12 order.
avi_fields_layout = [
    ("y",   2), ("a", 1), ("b", 2), ("s", 2),          # PB1
    ("c",   2), ("m", 2), ("r", 4),                    # PB2
    ("itc", 1), ("ec", 3), ("q", 2), ("sc", 2),        # PB3
    ("vic", 7),                                        # PB4
    ("yq",  2), ("cn", 2), ("pr", 4),                  # PB5
    ("bar_top", 16), ("bar_bottom", 16), ("bar_left", 16), ("bar_right", 16),   # PB6..PB13
]


def _checksum(header_bytes, data_bytes):
    """Migen expression: -(sum of bytes) mod 256 as an 8-bit value."""
    total = Signal(12)
    return total, (-(sum(header_bytes) + sum(data_bytes)))[:8]


class _PacketHolder(LiteXModule):
    """Latches ``packet_comb`` (header, sub0..3 expressions) on ``trigger`` and
    presents it on ``source`` until accepted."""
    def __init__(self, header, subs):
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        self.sync += [
            If(self.trigger,
                self.source.valid.eq(1),
                self.source.header.eq(header),
                *[getattr(self.source, f"sub{k}").eq(subs[k]) for k in range(4)],
            ).Elif(self.source.ready,
                self.source.valid.eq(0),
            ),
        ]


class AVIInfoFrameGenerator(LiteXModule):
    def __init__(self):
        self.fields  = Record(avi_fields_layout)
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        f = self.fields
        db = [
            Cat(f.s, f.b, f.a, f.y, C(0, 1)),          # PB1
            Cat(f.r, f.m, f.c),                        # PB2
            Cat(f.sc, f.q, f.ec, f.itc),               # PB3
            Cat(f.vic, C(0, 1)),                       # PB4
            Cat(f.pr, f.cn, f.yq),                     # PB5
            f.bar_top[:8], f.bar_top[8:], f.bar_bottom[:8], f.bar_bottom[8:],
            f.bar_left[:8], f.bar_left[8:], f.bar_right[:8], f.bar_right[8:],
        ]
        header_bytes = [C(PacketType.AVI_INFOFRAME, 8), C(2, 8), C(13, 8)]
        total = Signal(12)
        self.comb += total.eq(sum(header_bytes) + sum(db))
        checksum = Signal(8)
        self.comb += checksum.eq(-total)
        payload = [checksum] + db + [C(0, 8)] * (27 - 13)
        subs = [Cat(*payload[7 * k:7 * k + 7]) for k in range(4)]
        self.holder = _PacketHolder(Cat(*header_bytes), subs)
        self.comb += [self.holder.trigger.eq(self.trigger), self.holder.source.connect(self.source)]


class GCPGenerator(LiteXModule):
    def __init__(self):
        self.avmute  = Signal()
        self.cd      = Signal(4)     # colour depth, 0 = not indicated (24 bit)
        self.trigger = Signal()
        self.source  = stream.Endpoint(packet_layout)

        # # #

        avmute_d = Signal()
        set_mute = Signal()
        clear_mute = Signal()
        self.sync += If(self.trigger, avmute_d.eq(self.avmute))
        self.comb += [
            set_mute.eq(self.avmute),
            clear_mute.eq(~self.avmute & avmute_d),
        ]
        sb0 = Cat(set_mute, C(0, 3), clear_mute, C(0, 3))
        sb1 = Cat(self.cd, C(0, 4))
        sub = Cat(sb0, sb1, C(0, 40))
        self.holder = _PacketHolder(C(PacketType.GCP, 24), [sub] * 4)
        self.comb += [
            self.holder.trigger.eq(self.trigger & (set_mute | clear_mute)),
            self.holder.source.connect(self.source),
        ]
```

Delete the unused `_checksum` helper when writing the file.

- [ ] **Step 3: Run** `uv run pytest test/test_hdmi_infoframe.py -v` → 3 passed. If the AVI packet differs from the model in PB0 only, the adder width is the culprit (`total` must hold 16 × 255): keep 12 bits and take the low 8 bits of the negation.

- [ ] **Step 4: Commit** `hdmi: add AVI InfoFrame and General Control Packet generators`.

### Task 5: the framer

**Files:** `litevideo/hdmi/framer.py`, `test/test_hdmi_framer.py`

Placement algorithm (see `doc/transmitter.md`):

1. The pixel stream is delayed by `LOOKAHEAD = PREAMBLE_LENGTH + GUARD_BAND_LENGTH = 10` characters. "Delayed time" is when the TMDS encoders see a pixel; "output time" is delayed time + `Encoder.latency` (4).
2. Video preamble: when the *undelayed* DE rises, the next 8 delayed characters get the video preamble CTL codes on channels 1 and 2 (through the encoders' `c` inputs), then 2 characters are overridden with the video guard band tokens, then the delayed DE is high.
3. Islands: on each delayed HSYNC leading edge a counter starts; at count `MIN_CONTROL_PERIOD` the island encoder is started with `max_packets` if `hs2de` has been measured, islands are enabled, DVI mode is off, and this is not the extended-control line. `hs2de` is the number of characters from the HSYNC leading edge to the DE rise, measured on every active line (delayed time). `max_packets = min(18, (hs2de - MIN_CONTROL_PERIOD - MIN_ISLAND_TO_PREAMBLE - LOOKAHEAD - 12 - 2) // 32)` where 12 is the island's own preamble and guard bands and 2 a safety margin; if that is < 1 no island is started.
4. Extended Control Period: the line on which VSYNC rises gets no island (its blanking then contains ≥ 32 control characters), satisfying Table 5-4 at any frame rate above 20 Hz.
5. Overrides (guard bands, island characters) are pipelined by `Encoder.latency` cycles and muxed over the encoder outputs at output time. Precedence: island encoder output > video guard band > TMDS encoder.

- [ ] **Step 1: Test**

```python
"""HDMIFramer: pixels + packets in, characters out, checked by feeding the
characters back into the phase-1 period and island decoders and against
``model.frame_tokens`` for the video path."""

import random
import unittest

from migen import *

from litevideo.hdmi.common import *
from litevideo.hdmi import model
from litevideo.hdmi.framer import HDMIFramer
from litevideo.hdmi.period import HDMIPeriodDecoder
from litevideo.hdmi.island import DataIslandDecoder

from test.common import stream_inserter

TIMING = dict(hactive=32, hfront=6, hsync=8, hback=60, vactive=3, vfront=1, vsync=1, vback=2)


class DUT(Module):
    def __init__(self):
        self.submodules.framer = HDMIFramer()
        self.submodules.period = HDMIPeriodDecoder()
        self.submodules.dec = DataIslandDecoder()
        self.comb += [
            self.framer.source.connect(self.period.sink),
            self.dec.active.eq(self.period.island_active),
            self.dec.first.eq(self.period.island_first),
            self.dec.nibble0.eq(self.period.nibble0),
            self.dec.nibble1.eq(self.period.nibble1),
            self.dec.nibble2.eq(self.period.nibble2),
        ]


def video_beats(timing, nframes):
    frames = model.frame_tokens(timing, nframes=nframes)
    beats = []
    for (c0, c1, c2, de, hs, vs) in frames:
        beats.append({"de": de, "hsync": hs, "vsync": vs})
    # pixel values: regenerate the same pattern frame_tokens uses
    ha = timing["hactive"]; vt = sum(timing[k] for k in ("vactive", "vfront", "vsync", "vback"))
    line = ha + timing["hfront"] + timing["hsync"] + timing["hback"]
    for i, b in enumerate(beats):
        y = (i // line) % vt; x = i % line
        if b["de"]:
            b["r"], b["g"], b["b"] = (((x + y) * 7) & 0xFF, ((x * 13) ^ y) & 0xFF, ((x + 2 * y) * 29) & 0xFF)
        else:
            b["r"] = b["g"] = b["b"] = 0
    return beats


def run_framer(timing, nframes, packets, valid_rand_packets=0):
    dut = DUT()
    beats = video_beats(timing, nframes)
    pbeats = [{"header": p.header, **{f"sub{k}": p.subpackets[k] for k in range(4)}} for p in packets]
    rx = {"video": [], "packets": [], "periods": [], "errors": 0}

    @passive
    def collect():
        while True:
            if (yield dut.period.source.valid):
                rx["periods"].append((yield dut.period.period))
                if (yield dut.period.source.de):
                    rx["video"].append(((yield dut.period.source.r), (yield dut.period.source.g), (yield dut.period.source.b)))
            if (yield dut.period.error):
                rx["errors"] += 1
            if (yield dut.dec.source.valid):
                header = (yield dut.dec.source.header)
                subs = []
                for k in range(4):
                    subs.append((yield getattr(dut.dec.source, f"sub{k}")))
                rx["packets"].append((model.Packet.from_words(header, subs), (yield dut.dec.source.ecc_ok)))
            yield

    run_simulation(dut, [
        stream_inserter(dut.framer.sink, beats, drain=40),
        stream_inserter(dut.framer.packet_sink, pbeats, valid_rand=valid_rand_packets, drain=0),
        collect(),
    ])
    return dut, beats, rx


class TestHDMIFramer(unittest.TestCase):
    def test_video_only_roundtrip(self):
        dut, beats, rx = run_framer(TIMING, nframes=2, packets=[])
        expected = [(b["r"], b["g"], b["b"]) for b in beats if b["de"]]
        # The first frame has no measured timing yet but video needs none; all pixels must come back.
        self.assertEqual(rx["video"], expected)
        self.assertEqual(rx["errors"], 0)
        self.assertNotIn(Period.DATA_ISLAND, rx["periods"])

    def test_islands_delivered_and_placed(self):
        prng = random.Random(41)
        packets = [model.Packet([prng.randrange(256) for _ in range(3)],
                                [[prng.randrange(256) for _ in range(7)] for _ in range(4)]) for _ in range(12)]
        dut, beats, rx = run_framer(TIMING, nframes=3, packets=packets)
        self.assertEqual([p for p, _ in rx["packets"]], packets)
        self.assertTrue(all(ok for _, ok in rx["packets"]))
        self.assertEqual(rx["errors"], 0)
        # Video is untouched.
        expected = [(b["r"], b["g"], b["b"]) for b in beats if b["de"]]
        self.assertEqual(rx["video"], expected)
        # No island on frame 1 (timing not yet measured on line 0) and none on the VSYNC line.
        periods = rx["periods"]
        line = sum(TIMING[k] for k in ("hactive", "hfront", "hsync", "hback"))
        self.assertNotIn(Period.DATA_ISLAND, periods[:line])

    def test_control_period_rules(self):
        prng = random.Random(42)
        packets = [model.Packet.null() for _ in range(40)]
        dut, beats, rx = run_framer(TIMING, nframes=2, packets=packets)
        periods = rx["periods"]
        # Every run of CONTROL between a trailing guard band and a video preamble is >= 4,
        # and every CONTROL run is >= 12 except the one directly before a video preamble
        # (preamble + that run form one control period >= 12).
        runs = []
        i = 0
        while i < len(periods):
            j = i
            while j < len(periods) and periods[j] == periods[i]:
                j += 1
            runs.append((periods[i], j - i))
            i = j
        for k, (p, n) in enumerate(runs):
            if p == Period.CONTROL:
                nxt = runs[k + 1][0] if k + 1 < len(runs) else None
                prv = runs[k - 1][0] if k > 0 else None
                if prv == Period.DATA_TRAILING_GUARD:
                    self.assertGreaterEqual(n, MIN_ISLAND_TO_PREAMBLE)
                if nxt == Period.DATA_PREAMBLE:
                    self.assertGreaterEqual(n, MIN_CONTROL_PERIOD)
        self.assertGreaterEqual(dut.framer.max_packets_value, 1)

    def test_dvi_mode_has_no_preambles(self):
        dut = DUT()
        beats = video_beats(TIMING, 2)
        periods = []

        @passive
        def collect():
            while True:
                if (yield dut.period.source.valid):
                    periods.append((yield dut.period.period))
                yield

        def setup():
            yield dut.framer.dvi_mode.eq(1)
            yield dut.period.dvi_mode.eq(1)

        run_simulation(dut, [setup(), stream_inserter(dut.framer.sink, beats, drain=40), collect()])
        self.assertNotIn(Period.VIDEO_PREAMBLE, periods)
        self.assertNotIn(Period.DATA_PREAMBLE, periods)
```

`max_packets_value` is a test hook: the framer stores the last computed value in a Python attribute-free way; expose it as the Signal `self.max_packets` and read it in the test with `(yield dut.framer.max_packets)` inside `collect()` instead (adjust the assertion to check the last collected value ≥ 1).

- [ ] **Step 2: Implement**

```python
"""HDMI framer: pixels and packets in, TMDS characters out.

Turns a LiteX ``video_data_layout`` stream (one pixel per pixel clock; the
framer is always ready and expects ``valid`` to stay high while enabled) and
a ``packet_layout`` stream into the three 10-bit characters per clock of an
HDMI link:

* active pixels are TMDS encoded (channel 0 = B, 1 = G, 2 = R);
* blanking carries control characters with HSYNC/VSYNC on channel 0 (HDMI
  1.3 §5.4.2 Table 5-34);
* every Video Data Period is preceded by the 8-character video preamble
  (Table 5-2) and the 2-character video guard band (Table 5-5): the pixel
  stream is delayed by ``LOOKAHEAD`` = 10 characters so the framer sees DE
  rise 10 characters before the encoders do;
* data islands are placed ``MIN_CONTROL_PERIOD`` characters after each
  HSYNC leading edge, sized from the measured HSYNC-to-DE distance so that
  the island, four control characters, the video preamble and guard band
  always fit before DE (§5.2.3.2, Figure 5-3); the line on which VSYNC rises
  carries no island so its blanking is an Extended Control Period (Table 5-4);
* ``dvi_mode`` disables preambles, guard bands and islands for DVI sinks.

Overrides (guard bands, island characters) are aligned with the TMDS
encoders' latency and muxed over their outputs. Total latency from ``sink``
to ``source`` is ``LOOKAHEAD + Encoder.latency`` characters.
"""

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.cores.video import video_data_layout

from litevideo.output.hdmi.encoder import Encoder
from litevideo.hdmi.common import *
from litevideo.hdmi.island.encoder import DataIslandEncoder

LOOKAHEAD = PREAMBLE_LENGTH + GUARD_BAND_LENGTH   # 10
ENCODER_LATENCY = 4                               # litevideo.output.hdmi.encoder.Encoder


class HDMIFramer(LiteXModule):
    latency = LOOKAHEAD + ENCODER_LATENCY

    def __init__(self):
        self.sink        = stream.Endpoint(video_data_layout)
        self.packet_sink = stream.Endpoint(packet_layout)
        self.source      = stream.Endpoint(raw_layout)
        self.enable_islands = Signal(reset=1)
        self.dvi_mode       = Signal()
        # Status
        self.hs2de        = Signal(16)   # measured HSYNC leading edge -> DE rise, characters
        self.hs2de_valid  = Signal()
        self.max_packets  = Signal(5)    # packets an island may carry on this timing
        self.island_count = Signal(32)

        # # #

        self.comb += self.sink.ready.eq(1)
        sink = self.sink

        # Delay line: undelayed sink -> delayed pixel/sync/DE (delayed time).
        names = ["de", "hsync", "vsync", "r", "g", "b"]
        stages = [Record([(n, len(getattr(sink, n))) for n in names]) for _ in range(LOOKAHEAD)]
        prev = sink
        for st in stages:
            for n in names:
                self.sync += getattr(st, n).eq(getattr(prev, n))
            prev = st
        d = stages[-1]        # delayed by LOOKAHEAD

        # Video preamble window: 8 characters starting when the undelayed DE rises,
        # then 2 guard band characters, then the delayed DE is high.
        de_u_r = Signal()
        self.sync += de_u_r.eq(sink.de)
        pre_cnt = Signal(4)
        pre_active = Signal()
        gb_active = Signal()
        self.sync += [
            If(sink.de & ~de_u_r & ~self.dvi_mode,
                pre_cnt.eq(1),
            ).Elif(pre_cnt != 0,
                pre_cnt.eq(pre_cnt + 1),
                If(pre_cnt == LOOKAHEAD, pre_cnt.eq(0)),
            ),
        ]
        self.comb += [
            pre_active.eq((pre_cnt >= 1) & (pre_cnt <= PREAMBLE_LENGTH)),
            gb_active.eq((pre_cnt > PREAMBLE_LENGTH) & (pre_cnt <= LOOKAHEAD)),
        ]

        # HSYNC-anchored island placement (delayed time).
        hsync_r = Signal()
        self.sync += hsync_r.eq(d.hsync)
        hs_edge = d.hsync & ~hsync_r
        since_hs = Signal(16)
        de_r = Signal()
        self.sync += de_r.eq(d.de)
        self.sync += [
            If(hs_edge, since_hs.eq(1)).Elif(since_hs != 0, since_hs.eq(since_hs + 1)),
            If(d.de & ~de_r & (since_hs != 0),
                self.hs2de.eq(since_hs),
                self.hs2de_valid.eq(1),
            ),
        ]
        room = Signal((17, True))
        self.comb += room.eq(self.hs2de - (MIN_CONTROL_PERIOD + MIN_ISLAND_TO_PREAMBLE + LOOKAHEAD + 12 + 2))
        npk = Signal((17, True))
        self.comb += npk.eq(room >> 5)
        self.comb += If(~self.hs2de_valid | (room < 0), self.max_packets.eq(0)
                     ).Elif(npk > MAX_PACKETS_PER_ISLAND, self.max_packets.eq(MAX_PACKETS_PER_ISLAND)
                     ).Else(self.max_packets.eq(npk))

        vsync_r = Signal()
        self.sync += vsync_r.eq(d.vsync)
        ecp_line = Signal()      # no island on the line where VSYNC rose
        self.sync += [
            If(d.vsync & ~vsync_r, ecp_line.eq(1)),
            If(hs_edge & ~(d.vsync & ~vsync_r), ecp_line.eq(0)),
        ]

        self.island = island = DataIslandEncoder()
        self.comb += [
            self.packet_sink.connect(island.sink),
            island.hsync.eq(d.hsync),
            island.vsync.eq(d.vsync),
            island.max_packets.eq(self.max_packets),
            island.start.eq((since_hs == MIN_CONTROL_PERIOD) & self.enable_islands & ~self.dvi_mode
                            & ~ecp_line & (self.max_packets != 0)),
        ]
        island_started = Signal()
        self.sync += island_started.eq(island.start & island.sink.valid)
        self.sync += If(island_started, self.island_count.eq(self.island_count + 1))

        # TMDS encoders on the delayed stream. Channel 1 carries CTL0/CTL1,
        # channel 2 CTL2/CTL3: the video preamble is CTL0=1.
        self.enc0 = enc0 = Encoder()
        self.enc1 = enc1 = Encoder()
        self.enc2 = enc2 = Encoder()
        self.comb += [
            enc0.d.eq(d.b), enc1.d.eq(d.g), enc2.d.eq(d.r),
            enc0.de.eq(d.de), enc1.de.eq(d.de), enc2.de.eq(d.de),
            enc0.c.eq(Cat(d.hsync, d.vsync)),
            enc1.c.eq(Mux(pre_active, PREAMBLE_VIDEO[0], 0)),
            enc2.c.eq(Mux(pre_active, PREAMBLE_VIDEO[1], 0)),
        ]

        # Overrides in delayed time, pipelined to output time.
        ovr_valid = Signal()
        ovr = Record(raw_layout)
        self.comb += [
            If(island.source.valid,
                ovr_valid.eq(1),
                ovr.c0.eq(island.source.c0), ovr.c1.eq(island.source.c1), ovr.c2.eq(island.source.c2),
            ).Elif(gb_active,
                ovr_valid.eq(1),
                ovr.c0.eq(video_gb_tokens[0]), ovr.c1.eq(video_gb_tokens[1]), ovr.c2.eq(video_gb_tokens[2]),
            ),
        ]
        pv = ovr_valid
        pr = ovr
        for _ in range(ENCODER_LATENCY):
            nv = Signal()
            nr = Record(raw_layout)
            self.sync += [nv.eq(pv), nr.c0.eq(pr.c0), nr.c1.eq(pr.c1), nr.c2.eq(pr.c2)]
            pv, pr = nv, nr

        self.comb += [
            self.source.valid.eq(1),
            If(pv,
                self.source.c0.eq(pr.c0), self.source.c1.eq(pr.c1), self.source.c2.eq(pr.c2),
            ).Else(
                self.source.c0.eq(enc0.out), self.source.c1.eq(enc1.out), self.source.c2.eq(enc2.out),
            ),
        ]
```

Check `Encoder` (litevideo/output/hdmi/encoder.py) really has 4 cycles from `d/c/de` to `out` before relying on `ENCODER_LATENCY`: write a five-line probe in `tmp/` that pulses `de` and counts cycles until `out` changes from a control token; delete it afterwards. If it is 4, keep; otherwise set the constant accordingly and note it in the docstring.

- [ ] **Step 3: Run** `uv run pytest test/test_hdmi_framer.py -v`. Expected: 4 passed. Debugging guidance: (a) if video pixels are shifted by a constant, the override pipeline depth differs from the encoder latency: fix `ENCODER_LATENCY`; (b) if the period decoder reports `error`, dump the first 200 characters of `framer.source` and compare with `model.frame_tokens` around the first island; (c) if `test_control_period_rules` fails on the ≥12 rule before an island, the island is anchored too early: `since_hs == MIN_CONTROL_PERIOD` must count from the HSYNC edge in delayed time and the front porch adds to it, so check the model's `hfront`.

- [ ] **Step 4: Commit** `hdmi: add framer with video preamble/guard band insertion and HSYNC-anchored island placement`.

### Task 6: `HDMITransmitter` with CSRs

**Files:** `litevideo/hdmi/transmitter.py`, `test/test_hdmi_transmitter.py`

- [ ] **Step 1: Test**: instantiate `HDMITransmitter()` under `ClockDomainsRenamer({"pix": "sys"})`, drive `sink` with `video_beats(TIMING, 3)`, set `avi.fields` defaults through the CSR storage signals (`dut.avi_config.storage`), enable, and check through the phase-1 decoders that (a) exactly one AVI InfoFrame packet equal to `model.avi_infoframe(vic=<default>)` arrives per frame after the first, (b) a GCP `set_avmute` arrives when `control.avmute` is set, (c) `island_count` CSR status increases. Use the DUT pattern of `test_hdmi_framer.py`.

- [ ] **Step 2: Implement**

```python
"""HDMI transmitter: framer, scheduler and packet generators with CSRs.

Runs in the ``pix`` clock domain (rename with ``ClockDomainsRenamer`` if the
integrator uses another name); CSRs live in ``sys`` and are synchronised with
``MultiReg``. Priority of packet sources (HDMI §7.8.2): audio samples, audio
clock regeneration (both added in phase 3), General Control, AVI InfoFrame.
"""

from migen import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer

from litex.gen import *
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import *
from litex.soc.cores.video import video_data_layout

from litevideo.hdmi.common import *
from litevideo.hdmi.framer import HDMIFramer
from litevideo.hdmi.scheduler import PacketScheduler
from litevideo.hdmi.infoframe import AVIInfoFrameGenerator, GCPGenerator, avi_fields_layout


class HDMITransmitter(LiteXModule):
    def __init__(self, default_vic=4, extra_packet_sinks=0):
        self.sink   = stream.Endpoint(video_data_layout)
        self.source = stream.Endpoint(raw_layout)

        self.control = CSRStorage(fields=[
            CSRField("enable_islands", 1, reset=1, description="Insert data islands."),
            CSRField("dvi_mode",       1, reset=0, description="DVI output: no preambles, guard bands or islands."),
            CSRField("avmute",         1, reset=0, description="Send General Control Packets with Set_AVMUTE."),
            CSRField("avi_enable",     1, reset=1, description="Send the AVI InfoFrame once per frame."),
        ])
        self.avi_config = CSRStorage(fields=[
            CSRField("y",   2, reset=0, description="Pixel encoding: 0 RGB, 1 YCbCr 4:2:2, 2 YCbCr 4:4:4 (CEA-861-D Table 8)."),
            CSRField("a",   1, reset=0), CSRField("b", 2, reset=0), CSRField("s", 2, reset=0),
            CSRField("c",   2, reset=0, description="Colorimetry: 0 none, 1 BT.601, 2 BT.709 (Table 9)."),
            CSRField("m",   2, reset=2, description="Picture aspect: 1 4:3, 2 16:9."),
            CSRField("r",   4, reset=8, description="Active format aspect (8 = same as picture)."),
            CSRField("itc", 1, reset=0), CSRField("ec", 3, reset=0),
            CSRField("q",   2, reset=0, description="RGB quantization: 0 default, 1 limited, 2 full (Table 11)."),
            CSRField("sc",  2, reset=0),
            CSRField("vic", 7, reset=default_vic, description="Video identification code (CEA-861-D Table 3)."),
        ])
        self.avi_config2 = CSRStorage(fields=[
            CSRField("yq", 2, reset=0), CSRField("cn", 2, reset=0), CSRField("pr", 4, reset=0),
        ])
        self.status = CSRStatus(fields=[
            CSRField("hs2de",       16, description="Measured HSYNC leading edge to DE rise, in characters."),
            CSRField("hs2de_valid",  1),
            CSRField("max_packets",  5, description="Packets per island that fit on this timing."),
        ])
        self.island_count = CSRStatus(32, description="Data islands sent.")
        self.frame_count  = CSRStatus(32, description="VSYNC leading edges seen.")

        # # #

        self.framer = framer = ClockDomainsRenamer("pix")(HDMIFramer())
        self.comb += [self.sink.connect(framer.sink), framer.source.connect(self.source)]

        n_sinks = 2 + extra_packet_sinks
        self.scheduler = sched = ClockDomainsRenamer("pix")(PacketScheduler(n_sinks))
        self.comb += sched.source.connect(framer.packet_sink)
        self.extra_packet_sinks = sched.sinks[:extra_packet_sinks]   # higher priority (audio, phase 3)
        gcp_sink, avi_sink = sched.sinks[extra_packet_sinks:]

        # Configuration into pix.
        ctl = Signal(4)
        avi = Signal(len(self.avi_config.storage))
        avi2 = Signal(len(self.avi_config2.storage))
        self.specials += [
            MultiReg(self.control.storage, ctl, "pix"),
            MultiReg(self.avi_config.storage, avi, "pix"),
            MultiReg(self.avi_config2.storage, avi2, "pix"),
        ]
        self.comb += [framer.enable_islands.eq(ctl[0]), framer.dvi_mode.eq(ctl[1])]

        # Frame trigger: VSYNC leading edge at the framer input.
        vsync_r = Signal()
        frame = Signal()
        self.sync.pix += vsync_r.eq(self.sink.vsync & self.sink.valid)
        self.comb += frame.eq(self.sink.vsync & self.sink.valid & ~vsync_r)

        self.avi = avig = ClockDomainsRenamer("pix")(AVIInfoFrameGenerator())
        self.gcp = gcpg = ClockDomainsRenamer("pix")(GCPGenerator())
        f = avig.fields
        self.comb += [
            Cat(f.y, f.a, f.b, f.s, f.c, f.m, f.r, f.itc, f.ec, f.q, f.sc, f.vic).eq(avi),
            Cat(f.yq, f.cn, f.pr).eq(avi2),
            avig.trigger.eq(frame & ctl[3]),
            avig.source.connect(avi_sink),
            gcpg.avmute.eq(ctl[2]),
            gcpg.trigger.eq(frame),
            gcpg.source.connect(gcp_sink),
        ]

        # Status back to sys.
        frame_count = Signal(32)
        self.sync.pix += If(frame, frame_count.eq(frame_count + 1))
        self.specials += [
            MultiReg(framer.hs2de, self.status.fields.hs2de),
            MultiReg(framer.hs2de_valid, self.status.fields.hs2de_valid),
            MultiReg(framer.max_packets, self.status.fields.max_packets),
            MultiReg(framer.island_count, self.island_count.status),
            MultiReg(frame_count, self.frame_count.status),
        ]
```

Check that the `Cat(...)` of the `avi_fields_layout` order matches the CSR field order (both are y, a, b, s, c, m, r, itc, ec, q, sc, vic); `MultiReg` on multi-bit counters is only for monitoring (values may tear), which the docstring says.

- [ ] **Step 3: Run** the test and the whole suite. **Step 4: Commit** `hdmi: add HDMITransmitter with CSR control of islands, AVI InfoFrame and AVMUTE`.

### Task 7: bench scaffolding for the NeTV2

**Files:** `pyproject.toml` (dev extra: `litex-boards`, `pyserial`; `[tool.uv.sources]` litex-boards tag 2026.04), `bench/__init__.py`, `bench/netv2/__init__.py`, `bench/netv2/common.py`, `bench/netv2/host/uartbone.py`

- [ ] **Step 1: Dependencies.** Add `"litex-boards", "pyserial"` to the `dev` extra and `litex-boards = { git = "https://github.com/litex-hub/litex-boards.git", tag = "2026.04" }` to `[tool.uv.sources]`; run `uv sync --extra dev`; commit `pyproject: add litex-boards and pyserial for the bench targets` with the updated `uv.lock`.

- [ ] **Step 2: `bench/netv2/common.py`**

```python
"""NeTV2 bench SoC: CPU-less, CSRs over uartbone, pixel clocks from a fractional MMCM."""

from migen import *

from litex.gen import *
from litex.build.parser import LiteXArgumentParser
from litex.soc.cores.clock import S7PLL, S7MMCM
from litex.soc.integration.soc_core import SoCMini
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

# 720p60 (CEA VIC 4): 74.25 MHz pixel clock, 371.25 MHz serial clock. From the
# 50 MHz oscillator a fractional MMCM gives 74.375 MHz (+0.17 %, within the
# +/-0.5 % HDMI tolerance): VCO = 50 * 14.875 = 743.75 MHz, /10 and /2.
PIX_CLK_FREQ = 74.25e6
VIC_720P60   = 4


class CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst      = Signal()
        self.cd_sys   = ClockDomain()
        self.cd_pix   = ClockDomain()
        self.cd_pix5x = ClockDomain()

        clk50 = platform.request("clk50")
        self.pll = pll = S7PLL(speedgrade=-2)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)

        self.mmcm = mmcm = S7MMCM(speedgrade=-2)
        self.comb += mmcm.reset.eq(self.rst)
        mmcm.register_clkin(clk50, 50e6)
        mmcm.create_clkout(self.cd_pix,   PIX_CLK_FREQ,     margin=2e-3)
        mmcm.create_clkout(self.cd_pix5x, 5 * PIX_CLK_FREQ, margin=2e-3, with_reset=False)
        platform.add_false_path_constraints(self.cd_sys.clk, self.cd_pix.clk)


class BenchSoC(SoCMini):
    def __init__(self, variant="a7-100", toolchain="vivado", sys_clk_freq=50e6, ident="LiteVideo NeTV2 bench", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)
        SoCMini.__init__(self, platform, sys_clk_freq, ident=ident, ident_version=True, **kwargs)
        self.crg = CRG(platform, sys_clk_freq)
        self.add_uartbone(uart_name="serial", baudrate=115200)


def bench_main(soc_cls, description, default_build_name):
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description=description)
    parser.add_target_argument("--variant", default="a7-100", choices=["a7-35", "a7-100"])
    args = parser.parse_args()
    soc = soc_cls(variant=args.variant, toolchain=args.toolchain, **parser.soc_argdict)
    builder_kwargs = parser.builder_argdict
    builder_kwargs.setdefault("output_dir", f"build/{default_build_name}")
    builder_kwargs.setdefault("csr_csv", f"build/{default_build_name}/csr.csv")
    builder = Builder(soc, **builder_kwargs)
    builder.build(**parser.toolchain_argdict, run=args.build)
```

After writing it, elaborate once without building (`uv run python -m bench.netv2.hdmi_tx` after Task 8) to see whether `S7MMCM` accepts `margin=2e-3` for 74.25 MHz from 50 MHz; if it cannot find a config, relax to `margin=5e-3` and record the achieved frequency the MMCM prints (`compute_config` logs it) in `doc/transmitter.md`. `SoCMini` with `add_uartbone` and no CPU is the standard LiteX pattern; confirm `parser.soc_argdict` does not inject `cpu_type` (it may; pass `cpu_type="None"` explicitly in `BenchSoC` if the build complains).

- [ ] **Step 3: `bench/netv2/host/uartbone.py`** (self-contained; runs on the Pi with only pyserial):

```python
#!/usr/bin/env python3
"""Minimal LiteX uartbone client: CSR read/write by name over a serial port.

Protocol (litex/tools/remote/comm_uart.py): command byte 0x02 (read) or 0x01
(write), length byte (words), 4-byte big-endian *word* address, then for
writes the big-endian 32-bit words; a read returns the words back to back.
The CSR map comes from the csr.csv the LiteX builder writes.

    uartbone.py --port /dev/ttyAMA0 --csr csr.csv read hdmi_tx_status
    uartbone.py --port /dev/ttyAMA0 --csr csr.csv write hdmi_tx_control 0x0b
    uartbone.py ... regs            # list registers
"""

import argparse
import csv
import json
import sys

import serial


class CSRMap:
    def __init__(self, path):
        self.regs = {}
        self.consts = {}
        with open(path) as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#"):
                    continue
                if row[0] == "csr_register":
                    _, name, addr, size, mode, *_ = row
                    self.regs[name] = (int(addr, 0), int(size))
                elif row[0] == "constant":
                    self.consts[row[1]] = row[2]
        self.data_width = int(self.consts.get("config_csr_data_width", 32))


class UARTBone:
    def __init__(self, port, baudrate=115200, timeout=1.0):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)

    def read_words(self, addr, n=1):
        self.ser.reset_input_buffer()
        self.ser.write(bytes([0x02, n]) + (addr // 4).to_bytes(4, "big"))
        raw = self.ser.read(4 * n)
        if len(raw) != 4 * n:
            raise TimeoutError(f"short read at {addr:#x}: {len(raw)} bytes")
        return [int.from_bytes(raw[4 * i:4 * i + 4], "big") for i in range(n)]

    def write_words(self, addr, words):
        self.ser.write(bytes([0x01, len(words)]) + (addr // 4).to_bytes(4, "big")
                       + b"".join(w.to_bytes(4, "big") for w in words))


class CSR:
    def __init__(self, bone, csrmap):
        self.bone, self.map = bone, csrmap

    def read(self, name):
        addr, size = self.map.regs[name]
        words = self.bone.read_words(addr, size)
        value = 0
        for w in words:
            value = (value << self.map.data_width) | (w & ((1 << self.map.data_width) - 1))
        return value

    def write(self, name, value):
        addr, size = self.map.regs[name]
        mask = (1 << self.map.data_width) - 1
        words = [(value >> (self.map.data_width * (size - 1 - i))) & mask for i in range(size)]
        self.bone.write_words(addr, words)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baudrate", type=int, default=115200)
    p.add_argument("--csr", required=True, help="csr.csv from the build")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regs")
    r = sub.add_parser("read"); r.add_argument("names", nargs="+")
    w = sub.add_parser("write"); w.add_argument("name"); w.add_argument("value")
    args = p.parse_args()
    csrmap = CSRMap(args.csr)
    if args.cmd == "regs":
        for name, (addr, size) in sorted(csrmap.regs.items(), key=lambda kv: kv[1][0]):
            print(f"{addr:#010x} {size:2d} {name}")
        return
    csr = CSR(UARTBone(args.port, args.baudrate), csrmap)
    if args.cmd == "read":
        print(json.dumps({n: csr.read(n) for n in args.names}))
    else:
        csr.write(args.name, int(args.value, 0))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit** `bench/netv2: add CPU-less uartbone bench SoC scaffolding and host CSR client`.

### Task 8: bench targets

**Files:** `bench/netv2/hdmi_tx.py`, `bench/netv2/hdmi_loopback.py`, `litevideo/output/hdmi/s7.py` (reuse), `bench/netv2/frame_crc.py`

- [ ] **Step 1: `bench/netv2/frame_crc.py`**: `FrameCRC` in `pix`: CRC-32 (IEEE 802.3 polynomial 0x04C11DB7, init 0xFFFFFFFF, final XOR 0xFFFFFFFF) over the 24-bit `{r,g,b}` of every DE pixel, latched at VSYNC rise into `crc` with `frame` count; use `litex.soc.cores.crc` if it offers a suitable core, else a 24-bit-per-cycle table-free implementation (24 iterations of the bit-serial CRC unrolled). Python reference `frame_crc(pixels)` in the same file for the host script (colour bars are deterministic so the expected CRC is computable from `ColorBarsPattern` semantics: 8 bars of `hres/8` pixels each row).

- [ ] **Step 2: `bench/netv2/hdmi_tx.py`**

```python
"""T4: 720p60 colour bars with AVI InfoFrame on NeTV2 hdmi_out 0 (Magewell capture on rpi5-netv2)."""

from migen import *

from litex.gen import *
from litex.soc.cores.video import VideoTimingGenerator, ColorBarsPattern

from litevideo.hdmi.transmitter import HDMITransmitter
from litevideo.output.hdmi.s7 import S7HDMIOutEncoderSerializer, S7HDMIOutPHY

from bench.netv2.common import BenchSoC, bench_main, VIC_720P60
from bench.netv2.frame_crc import FrameCRC


class HDMITxSoC(BenchSoC):
    def __init__(self, **kwargs):
        BenchSoC.__init__(self, ident="LiteVideo NeTV2 HDMI TX bench", **kwargs)
        platform = self.platform
        pads = platform.request("hdmi_out", 0)

        self.vtg = ClockDomainsRenamer("pix")(VideoTimingGenerator(default_video_timings="1280x720@60Hz"))
        self.bars = ClockDomainsRenamer("pix")(ColorBarsPattern())
        self.hdmi_tx = HDMITransmitter(default_vic=VIC_720P60)
        self.comb += [self.vtg.source.connect(self.bars.vtg_sink), self.bars.source.connect(self.hdmi_tx.sink)]

        # Clock lane: fixed 0000011111 pattern at the pixel rate (litevideo convention).
        self.clk_gen = S7HDMIOutEncoderSerializer(pads.clk_p, pads.clk_n, bypass_encoder=True)
        self.comb += self.clk_gen.data.eq(0b0000011111)
        self.phy = S7HDMIOutPHY(pads, mode="raw")
        self.comb += self.hdmi_tx.source.connect(self.phy.sink)

        self.frame_crc = FrameCRC()
        self.comb += self.frame_crc.sink.eq(self.bars.source)   # see Step 1 for the exact interface

        platform.add_period_constraint(self.crg.cd_pix.clk,   1e9 / 74.25e6)
        platform.add_period_constraint(self.crg.cd_pix5x.clk, 1e9 / 371.25e6)


if __name__ == "__main__":
    bench_main(HDMITxSoC, "LiteVideo NeTV2 HDMI transmitter bench (720p colour bars).", "netv2-hdmi-tx")
```

`S7HDMIOutEncoderSerializer` honours `pad.inverted` (the `hdmi_out` 0 clock pair is `Inverted()` in the platform) and needs the `pix`/`pix5x` domains, which `CRG` provides. Check `ColorBarsPattern.source` is `video_data_layout` with `valid` held high while the VTG runs (it is; `vtg_sink.ready` is driven by the pattern).

- [ ] **Step 3: `bench/netv2/hdmi_loopback.py`**: same as `hdmi_tx.py` (it may still drive the pads) plus `HDMIPeriodDecoder` and `DataIslandDecoder` in `pix` fed from `hdmi_tx.source`, with CSRs: `rx_periods` (a 8×16-bit histogram of `period` values updated continuously), `rx_packets`, `rx_ecc_errors`, `rx_last_header` (24 bits), `rx_errors` (period decoder `error` count), `rx_frame_crc` (FrameCRC over the *decoded* `video_data_layout`), all via `CSRStatus` + `MultiReg`.

- [ ] **Step 4: Elaborate both without building**: `uv run python -m bench.netv2.hdmi_tx --no-compile-gateware` style is not available for SoCMini here, so run `uv run python -m bench.netv2.hdmi_tx` (no `--build`) and confirm it writes `build/netv2-hdmi-tx/gateware/kosagi_netv2.v` and `csr.csv`; same for the loopback. Fix elaboration errors.

- [ ] **Step 5: Commit** `bench/netv2: add HDMI transmitter and fabric loopback bench targets`.

### Task 9: build with Vivado

- [ ] **Step 1: Announce** to the peer session "netv2 firmware upgrade and hdcp work" that a Vivado build is starting (one at a time convention).
- [ ] **Step 2: Build the loopback**: `uv run scripts/limited.py -- uv run python -m bench.netv2.hdmi_loopback --build --toolchain vivado 2>&1 | tee build/loopback-build.log | tail -30` (Vivado 2025.2 must be on PATH: `source /opt/Xilinx/2025.2/Vivado/settings64.sh` in the same shell, or pass `--vivado-...` none; check `which vivado`). Expected: bitstream at `build/netv2-hdmi-loopback/gateware/kosagi_netv2.bit`; timing report `.../vivado.log` shows all constraints met. Record WNS/WHS, utilisation (LUT/FF/BRAM) and the MMCM frequencies in `doc/reports/<date>-netv2-loopback.md`.
- [ ] **Step 3: Build the tx** the same way.
- [ ] **Step 4: If timing fails on `pix5x`** (371.25 MHz OSERDES): that is the same speed-grade question netv2-fpga met; report the numbers, do not waive.
- [ ] **Step 5: Commit** the two report files (not the build directory).

### Task 10: host rig and tier T1 run

**Files:** `bench/netv2/host/rig.py`, `bench/netv2/host/run_loopback.py`

- [ ] **Step 1: `rig.py`**: functions `copy(local, remote)` (scp to `tim@rpi5-netv2.welland.mithis.com:~/litevideo/`), `load(bitstream)` (`ssh ... sudo openFPGALoader -c rp1pio --pins=27:22:4:17 ~/litevideo/<bit>`; assert the output contains `Done`), `csr(csr_csv, args)` (runs the copied `uartbone.py` remotely, returns parsed JSON), `capture_frame(path, width=1280, height=720)` (`ssh ... ffmpeg -y -f v4l2 -video_size WxH -i /dev/video0 -frames:v 3 -update 1 ~/litevideo/frame.png` then scp back; keep the third frame to skip start-up), `capture_audio(seconds)` (`arecord -D hw:XI100DUSBHDMI -f S16_LE -r 48000 -c 2 -d N ~/litevideo/audio.wav`, for phase 3), `report(path, title, rows)` writing markdown with the bitstream SHA-256, date and results. All through `subprocess.run` with `check=True`; never `shell=True` with user data.

- [ ] **Step 2: `run_loopback.py`**: copy bitstream + `uartbone.py` + `csr.csv`; announce; load; wait 2 s; read `hdmi_tx_status`, `hdmi_tx_island_count`, `hdmi_tx_frame_count`, `rx_*` twice 1 s apart; assert: frame_count advances by ~60, island_count advances, rx_packets advances with rx_ecc_errors == 0 and rx_errors == 0, `rx_last_header & 0xFF == 0x82`, rx_frame_crc equals the Python reference CRC of the colour-bar frame, period histogram contains VIDEO and DATA_ISLAND; toggle `avmute` and see rx_last_header become 0x03 within a second; set `dvi_mode` and see the DATA_ISLAND histogram bin stop advancing. Write `doc/reports/<date>-netv2-loopback.md` with every number.

- [ ] **Step 3: Run it** (announce first). Fix and rerun until green. Commit the scripts and the report.

### Task 11: tier T4 run against the Magewell

**Files:** `bench/netv2/host/run_tx.py`

- [ ] **Step 1: Script**: load `hdmi_tx` bitstream; read status; capture a frame; analyse with Pillow: sample the centre of each of the 8 bars (x = (i + 0.5) * 160, y = 360) and compare to the `ColorBarsPattern` colours (white, yellow, cyan, green, magenta, red, blue, black) with a tolerance of 40 per channel (the Magewell captures YUYV, so chroma is subsampled and converted); also `ffprobe` the device to record the detected input format (`v4l2-ctl -d /dev/video0 --get-fmt-video` and, if the driver exposes it, `--query-dv-timings`). Then set `dvi_mode=1` and capture again (Magewell must still lock: DVI-style stream), then `avmute=1` and capture (the Magewell may blank or freeze; record what it does). Report.

- [ ] **Step 2: Run** (announce first). Expected: bars captured within tolerance. If the Magewell shows its no-signal frame, work down this list and record each result in the report: (a) confirm the cable is on `hdmi_out` 0 (ask the user via the report if unsure; try `hdmi_out` 1 build only if the user says so); (b) check `hs2de_valid` and `frame_count` over the console (the transmitter is running); (c) build a variant with `dvi_mode=1` reset default; (d) invert the clock lane pattern (`0b1111100000`) to test the `inverted` handling; (e) swap the clock pattern to `0b0000011111` on a non-inverted pad if (d) helps; (f) reduce to 640x480@60 (25.175 MHz, VIC 1) which is the most forgiving mode.

- [ ] **Step 3: Commit** script and report; update `doc/transmitter.md` with the outcome.

### Task 12: documentation and review

- [ ] **Step 1: `doc/transmitter.md`**: block diagram (VTG/pattern → HDMITransmitter[framer, scheduler, AVI, GCP] → PHY), the placement algorithm with the numbers for 720p/1080p/480p (`hs2de`, `max_packets`), latencies, CSR table (from `csr.csv`), clocking (fractional MMCM values actually chosen), what T1/T4 proved with links to the reports.
- [ ] **Step 2:** Update `doc/README.md` and README features; `LOG.md`/`TODO.md` on `claude-notes`.
- [ ] **Step 3:** Push; CI green; dispatch a review sub-agent over `git diff <phase-1 tip>...hdmi-support` asking for FSM edge cases in the framer (DE rising within 10 characters of an HSYNC edge, islands on the last line before DE, `hs2de` changing between lines), latency alignment, CSR/CDC correctness, and resource use; fix findings; commit.
