# Testing

## Tier 0: simulation (no hardware)

    uv sync --extra dev
    uv run pytest -v

Every gateware core in `litevideo/hdmi/` is simulated with Migen against the
pure-Python model `litevideo/hdmi/model.py`; the model itself is checked
against vectors derived from the HDMI specification text and an independent
implementation (see `test/test_hdmi_bch.py`). Colour-space cores are checked
against float models on a test image.

Helpers: `test/common.py` (`stream_inserter`, `stream_collector`). The
`test/` package shadows the standard library's `test` package; that is fine
under pytest (default prepend import mode, as LiteEth does it) but
`python -m unittest test.test_x` may pick up the wrong package, so use
`uv run pytest`.

## Hardware tiers

| Tier | Rig | What it proves |
|---|---|---|
| T1 | fabric loopback on a NeTV2 (`rpi5-netv2`) | protocol layer at the pixel rate on silicon, no cables |
| T2 | HDMI cable `hdmi_out` 0 → `hdmi_in` 0 on the same board | SERDES, clock recovery, real TMDS |
| T3 | real HDMI source into `hdmi_in` 1 (the Pi 5's own HDMI-A-2 on rpi5-netv2; `bench/netv2/hdmi_rx.py`, `bench/netv2/host/run_rx.py`) | receiver front end, timing, ECC and packet conventions against a commercial source |
| T4 | real HDMI sink with audio capture on `hdmi_out` 0 | transmitter accepted by a commercial sink |

Board targets and host scripts live under `bench/` (from phase 2). Every
hardware run writes a dated report under `doc/reports/`.
