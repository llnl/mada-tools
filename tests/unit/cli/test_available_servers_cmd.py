# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the `available_servers.py` module."""

from argparse import Namespace
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.available_servers import AvailableServersCmd
from mada_tools.extensions.manifest import MCPServerRegistration


@pytest.fixture
def available_servers_cmd() -> AvailableServersCmd:
    """Return an `AvailableServersCmd` instance for CLI tests."""
    return AvailableServersCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, available_servers_cmd: AvailableServersCmd):
    """Verify that the `available-servers` subcommand is registered correctly."""
    parser = create_parser(available_servers_cmd)

    args = parser.parse_args(["available-servers"])

    assert args.main_command == "available-servers"
    assert hasattr(args, "func")
    assert callable(args.func)


def test_process_command_prints_no_servers_message(monkeypatch: MonkeyPatch, capsys):
    """Verify that the command prints a fallback message when no servers are discovered."""

    class FakeExtensionRegistry:
        def get_available_mcp_servers(self):
            return []

    import mada_tools.cli.commands.available_servers as available_mod

    monkeypatch.setattr(available_mod, "ExtensionRegistry", FakeExtensionRegistry)

    AvailableServersCmd().process_command(Namespace())

    captured = capsys.readouterr()
    assert "No available servers found." in captured.out


def test_process_command_renders_sorted_server_table(monkeypatch: MonkeyPatch, capsys):
    """Verify that the command renders the discovered server registrations in a table."""

    class FakeExtensionRegistry:
        def get_available_mcp_servers(self):
            return [
                MCPServerRegistration("alpha", "alpha_pkg.alpha.server", "alpha_pkg"),
                MCPServerRegistration("beta", "alpha_pkg.beta.server", "alpha_pkg"),
                MCPServerRegistration("zeta", "beta_pkg.zeta.server", "beta_pkg"),
            ]

    import mada_tools.cli.commands.available_servers as available_mod

    monkeypatch.setattr(available_mod, "ExtensionRegistry", FakeExtensionRegistry)

    AvailableServersCmd().process_command(Namespace())

    captured = capsys.readouterr()
    output = captured.out
    assert "Available MCP Servers" in output
    assert "Provider Package" in output
    assert "Module Path" in output
    assert output.index("alpha_pkg          alpha") < output.index("beta_pkg           zeta")
    assert output.index("alpha_pkg          alpha") < output.index("alpha_pkg          beta")
