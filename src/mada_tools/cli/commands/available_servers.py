# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for viewing available MCP servers.

This module defines the `AvailableServersCmd` class, which implements a
command-line interface (CLI) command for viewing the available MCP servers.
The output will include both built-in servers and plugin servers.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace

from rich import box
from rich.console import Console
from rich.table import Table

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.extensions import ExtensionRegistry


class AvailableServersCmd(BaseCmd):
    """
    CLI command for viewing available MCP servers.

    This class adds the "available-servers" command to the main argument
    parser, allowing users to view available built-in and plugin MCP servers
    for MADA.

    Methods:
        add_parser:
            Adds the "available-servers" subcommand and its arguments to the
            CLI parser.
        process_command:
            Executes the logic for retrieving available servers using the
            parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        available_servers: ArgumentParser = subparsers.add_parser(
            "available-servers",
            help="View available servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        available_servers.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """
        Execute the logic for this CLI command.

        Args:
            args (Namespace): Parsed CLI arguments from the user.
        """
        available = ExtensionRegistry().get_available_mcp_servers()

        if not available:
            print("\nNo available servers found.")
            return

        console = Console()

        rows = []
        for registration in available:
            rows.append((registration.package, registration.name, registration.module_path))

        table = Table(
            title="Available MCP Servers",
            show_header=True,
            header_style="bold magenta",
            box=box.SIMPLE_HEAVY,
        )
        table.add_column("Provider Package", no_wrap=True)
        table.add_column("Server", style="cyan", no_wrap=True)
        table.add_column("Module Path")

        style_cycle = ["", "dim"]
        current_pkg = None
        pkg_index = -1

        for pkg, name, module_path in rows:
            if pkg != current_pkg:
                current_pkg = pkg
                pkg_index += 1

            row_style = style_cycle[pkg_index % len(style_cycle)]
            table.add_row(pkg, name, module_path, style=row_style)

        console.print(table)
