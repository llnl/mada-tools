# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Functionality for interaction with the CLI.

The `cli` package contains all of the functionality required
for user interaction with the command line interface (CLI).
It sets up an argument parser for the main `mada-tools` command
and subparsers for the various subcommands found in the `commands`
subpackage.

Subpackages:
    commands:
        Sets up subcommands for the `mada-tools` command.

Modules:
    ascii_art:
        A file to store ASCII art that can be used in the CLI output.
"""

from mada_tools.cli.ascii_art import BANNER
from mada_tools.cli.commands import ALL_COMMANDS
from mada_tools.logging_config import LEVEL_MAP, set_log_level, setup_logging

__all__ = [
    "set_log_level",
    "setup_logging",
    "ALL_COMMANDS",
    "BANNER",
    "LEVEL_MAP",
]
