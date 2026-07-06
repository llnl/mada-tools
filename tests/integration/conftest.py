# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for files in this `integration/` test directory.
"""

import json
import random
import uuid
from pathlib import Path
from typing import Callable

import pytest

from mada_tools.server_management.server_manager import ServerManager
from tests.conftest import REPO_DIR
from tests.utils import (
    collect_server_tools,
    load_server_config,
    validate_server_state,
)


@pytest.fixture(scope="session")
def server_management_integration_testing_dir(create_testing_dir: Callable, temp_output_dir: str) -> Path:
    """
    Fixture to create a temporary output directory for integration tests related to testing the
    `server_management` directory.

    Args:
        create_testing_dir: A fixture which returns a function that creates the testing directory.
        temp_output_dir: The path to the temporary ouptut directory we'll be using for this test run.

    Returns:
        The path to the temporary testing directory for integration tests of files in the
        `server_management` directory.
    """
    return create_testing_dir(temp_output_dir, "server_management_integration_testing")


@pytest.fixture
def validated_server_group():
    """
    Create an async helper for integration tests that starts a server group,
    validates server state, and verifies required MCP tools are available.

    Returns:
        Callable: Async function that accepts a server group name and expected
        tools mapping, then returns collected server tool information.
    """

    async def _run(server_name: str, expected_tools: dict[str, set[str]]):
        normalized = server_name.replace("-", "_")
        config_path = REPO_DIR / "configs" / f"{normalized}_servers.json"
        randomized_path = REPO_DIR / "configs" / f"{normalized}_servers_randomized_{uuid.uuid4().hex}.json"

        data = json.loads(config_path.read_text())

        for server in data.get("servers", {}).values():
            if "port" in server:
                server["port"] = random.randint(1024, 65535)

        randomized_path.write_text(json.dumps(data, indent=2))
        config_path = randomized_path

        config = load_server_config(config_path)
        server_manager = ServerManager(state_file=Path.home() / ".mada" / f"server_statuses_{uuid.uuid4().hex}.json")
        server_manager.start_servers(config_path)

        try:
            active_servers = server_manager.state_manager.get_servers(validate=True)

            validate_server_state(config["servers"], active_servers)
            return await collect_server_tools(active_servers, expected_tools)

        finally:
            server_manager.stop_servers()

    return _run
