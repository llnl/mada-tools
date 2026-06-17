# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Main CLI entry point for the MADA tools command-line interface.

This module provides the main entry point to the `mada-tools` CLI tool.
It defines the primary argument parser and integration of all available
subcommands.
"""

import logging
import sys
import traceback
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter

from mada_tools import VERSION
from mada_tools.cli import ALL_COMMANDS, LEVEL_MAP, setup_logging
from mada_tools.cli.ascii_art import BANNER


def parse_args() -> Namespace:
    """
    Set up the command-line argument parser for the Merlin package.

    Returns:
        An `ArgumentParser` object with every parser defined in Merlin's codebase.
    """
    parser = ArgumentParser(
        prog="mada-tools",
        description=BANNER,
        formatter_class=RawDescriptionHelpFormatter,
        epilog="See mada-tools <command> --help for more info",
    )
    parser.add_argument("-v", "--version", action="version", version=VERSION)
    parser.add_argument(
        "-l",
        "--log-level",
        type=str,
        default="INFO",
        choices=LEVEL_MAP.keys(),
        help="Set the logging level. Default: %(default)s",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional path to a log file",
    )
    subparsers = parser.add_subparsers(dest="subparsers", required=True)

    for command in ALL_COMMANDS:
        command.add_parser(subparsers)

    return parser.parse_args()


def main():
    """
    Entry point for the MADA tools command-line interface (CLI) operations.

    This function sets up the argument parser, handles command-line arguments,
    initializes logging, and executes the appropriate function based on the
    provided command. It ensures that the user receives error handling for any
    exceptions that may occur during command execution.
    """
    # Parse arguments from the user
    args = parse_args()

    # Configure logging once
    setup_logging(
        level=args.log_level,
        log_to_stdout=True,
        log_file=args.log_file,
    )

    LOG = logging.getLogger(__name__)

    # Run the command requested by the user
    try:
        args.func(args)
    except Exception as excpt:
        LOG.debug(traceback.format_exc())
        LOG.error(str(excpt))
        sys.exit(1)

    sys.exit()


if __name__ == "__main__":
    main()
