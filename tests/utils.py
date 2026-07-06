# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Utilites used by several tests
"""

import json
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mada_tools.server_management.server_info import ServerStatus


def load_server_config(config_path: Path) -> dict:
    """
    Load and parse a server configuration JSON file.

    Args:
        config_path (Path): Path to the JSON config file.

    Returns:
        dict: Parsed server configuration.
    """
    if not config_path.exists():
        raise pytest.UsageError(f"Config not found: {config_path}")

    with open(config_path, "r") as f:
        return json.load(f)


def validate_server_state(expected_servers: dict, active_servers: dict) -> None:
    """
    Validate that active servers match the expected server configuration.

    Checks server name, host, port, running status, and configured environment variables.

    Args:
        expected_servers (dict): Expected server definitions from config.
        active_servers (dict): Active server objects keyed by server name.
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


async def collect_server_tools(active_servers: dict, expected_tools: dict[str, set[str]]) -> dict[str, dict]:
    """
    Collect tool names exposed by each active server and verify required tools are present.

    Args:
        active_servers (dict): Active server objects keyed by server name.
        expected_tools (dict[str, set[str]]): Required tool names per server.

    Returns:
        dict[str, dict]: Per-server connection details and discovered tools.
    """
    results = {}

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


def get_server_env_vars(config_path: Path, server_key: str):
    """
    Return the environment variables mapping for a specific server.

    Args:
        config_path: Path to the server configuration file.
        server_key: Key identifying the server entry in the configuration.

    Returns:
        A dictionary of environment variables for the given server.
        Returns an empty dictionary if the server has no "env_vars" entry.

    Raises:
        KeyError: If `server_key` is not present in the configuration.
    """
    data = load_server_config(config_path)
    servers = data.get("servers", {})

    if server_key not in servers:
        raise KeyError(f"Server key '{server_key}' not found in config.")

    return servers[server_key].get("env_vars", {})
