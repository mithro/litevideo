#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""Simulation helpers shared by the tests.

``stream_inserter`` drives a LiteX ``stream.Endpoint`` sink from a list of
dicts (one dict per beat, keys are field names), optionally with random
``valid`` gaps. ``stream_collector`` records beats from a source into a list of
dicts, optionally with random ``ready`` back-pressure. Both follow the LiteEth
``test/test_stream.py`` pattern.
"""

import random

from migen import *


def stream_inserter(endpoint, beats, seed=0, valid_rand=0, first_last=False, drain=64):
    """Generator: push ``beats`` (list of dicts) into ``endpoint`` (a sink),
    then idle for ``drain`` cycles so pipelined cores can flush (the
    simulation ends when the last non-passive generator returns)."""
    prng = random.Random(seed)
    for n, beat in enumerate(beats):
        while prng.randrange(100) < valid_rand:
            yield endpoint.valid.eq(0)
            yield
        yield endpoint.valid.eq(1)
        for name, value in beat.items():
            yield getattr(endpoint, name).eq(value)
        if first_last:
            yield endpoint.first.eq(n == 0)
            yield endpoint.last.eq(n == len(beats) - 1)
        yield
        while not (yield endpoint.ready):
            yield
    yield endpoint.valid.eq(0)
    if first_last:
        yield endpoint.first.eq(0)
        yield endpoint.last.eq(0)
    for _ in range(drain):
        yield


@passive
def stream_collector(endpoint, fields, dest, seed=0, ready_rand=0):
    """Passive generator: collect beats of ``endpoint`` (a source) into ``dest``.

    ``yield`` is not allowed inside a comprehension, hence the explicit loop."""
    prng = random.Random(seed)
    while True:
        ready = prng.randrange(100) >= ready_rand
        yield endpoint.ready.eq(ready)
        yield
        if ready and (yield endpoint.valid):
            beat = {}
            for name in fields:
                beat[name] = (yield getattr(endpoint, name))
            dest.append(beat)


def run_for(cycles):
    """Generator: idle for ``cycles`` clock cycles."""
    for _ in range(cycles):
        yield
