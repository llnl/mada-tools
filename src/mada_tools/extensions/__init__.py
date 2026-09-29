# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Extension discovery and manifest definitions for MADA.

The extensions package provides data structures and discovery utilities for
registering MADA functionality through extension manifests.

Modules:
    manifest:
        Dataclasses describing extension manifests and extension registrations.
    registry:
        Discovery and validation utilities for manifest-based and legacy
        extension registrations.
    builtins:
        Built-in extension manifest factory for surfaces shipped with MADA.
"""

from mada_tools.extensions.manifest import (
    DirectCommandRegistration,
    ExtensionManifest,
    MCPServerRegistration,
    SkillRegistration,
)
from mada_tools.extensions.registry import ExtensionRegistry

__all__ = [
    "DirectCommandRegistration",
    "ExtensionManifest",
    "ExtensionRegistry",
    "MCPServerRegistration",
    "SkillRegistration",
]
