# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The `study_construction` package provides components for building WEAVE-backed,
study-construction MCP server functionality.

Modules:
    server:
        Abstract base class for WEAVE-supported study construction MCP servers.
    study_constructor:
        Utilities for rendering and writing Jinja-backed study templates.
"""

from mada_tools.workflow.weave.study_construction.server import WEAVEStudyConstructionServer

__all__ = ["WEAVEStudyConstructionServer"]
