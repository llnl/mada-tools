# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Reusable helpers for server-oriented tests.

These functions bundle the common assertions and MCP inspection logic used by
integration and end-to-end tests. They are intentionally path-based and free of
pytest fixture assumptions so downstream extension packages can call them from
their own tests or helper layers.
"""

import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mada_tools.server_management.server_info import ServerStatus


def load_server_config(config_path: Path) -> dict[str, Any]:
    """Load and parse a server configuration JSON file.

    Args:
        config_path: Path to a JSON file containing a top-level `servers`
            mapping.

    Returns:
        dict[str, Any]: Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_server_state(expected_servers: dict[str, Any], active_servers: dict[str, Any]) -> None:
    """Validate that active servers match the expected server configuration.

    The checks cover presence, host, port, running status, and configured
    environment variables. The function raises assertion failures directly so it
    reads naturally inside tests.

    Args:
        expected_servers: Expected server definitions from the config file.
        active_servers: Actual server objects returned by the server-state
            manager, keyed by server name.
    """
    for name, expected in expected_servers.items():
        assert name in active_servers, f"Missing server: {name}"

        active = active_servers[name]
        assert active.name == name
        assert active.host == expected["host"]
        assert active.port == expected["port"]
        assert active.status == ServerStatus.RUNNING

        for key, value in expected.get("env_vars", {}).items():
            assert active.env_vars.get(key) == value, (
                f"{name} env var mismatch for {key}: expected {value}, got {active.env_vars.get(key)}"
            )


async def collect_server_tools(
    active_servers: dict[str, Any],
    expected_tools: dict[str, set[str]],
) -> dict[str, dict[str, Any]]:
    """Collect tools exposed by each active server and optionally assert on them.

    Args:
        active_servers: Active server objects keyed by server name.
        expected_tools: Optional expected tool-name sets keyed by server name.
            When a server name is present, the discovered tool set must match
            exactly.

    Returns:
        dict[str, dict[str, Any]]: Per-server connection information and the set
        of discovered tool names.
    """
    results: dict[str, dict[str, Any]] = {}

    for name, active in active_servers.items():
        url = f"http://{active.host}:{active.port}/mcp"

        async with AsyncExitStack() as stack:
            transport_cm = streamable_http_client(url)
            read_stream, write_stream, _ = await stack.enter_async_context(transport_cm)

            session = ClientSession(read_stream, write_stream)
            await stack.enter_async_context(session)

            await session.initialize()
            tools_result = await session.list_tools()
            actual_tool_names = {tool.name for tool in tools_result.tools}

        if name in expected_tools:
            assert expected_tools[name] == actual_tool_names, (
                f"{name} tool mismatch. Expected {expected_tools[name]}, got {actual_tool_names}"
            )

        results[name] = {
            "host": active.host,
            "port": active.port,
            "tools": actual_tool_names,
        }

    return results


def get_server_env_vars(config_path: Path, server_key: str) -> dict[str, Any]:
    """Return the environment-variable mapping for one configured server.

    Args:
        config_path: Path to the server configuration JSON file.
        server_key: Key identifying the server entry inside the `servers`
            mapping.

    Returns:
        dict[str, Any]: Environment-variable mapping for the requested server,
        or an empty dictionary when the server has no `env_vars` block.

    Raises:
        KeyError: If `server_key` does not exist in the configuration.
    """
    data = load_server_config(config_path)
    servers = data.get("servers", {})

    if server_key not in servers:
        raise KeyError(f"Server key '{server_key}' not found in config.")

    return servers[server_key].get("env_vars", {})
