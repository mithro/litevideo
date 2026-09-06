#
# This file is part of LiteVideo.
#
# Copyright (c) 2026 Tim 'mithro' Ansell <me@mith.ro>
# SPDX-License-Identifier: BSD-2-Clause

"""HDMI link-layer cores, independent of any PHY or clock domain.

Modules here run in the default clock domain; integrators rename it to the
pixel clock with ``ClockDomainsRenamer("pix")``. See doc/hdmi-protocol.md.
"""
