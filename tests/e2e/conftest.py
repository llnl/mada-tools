# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for end-to-end tests.
"""

import json
import random
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest
import pytest_asyncio
from _pytest.monkeypatch import MonkeyPatch
from mada_mcp_servers.server_management.server_manager import ServerManager

from examples.simple_agent_loop import MultiServerAgent
from mada_tools.server_management import ServerInfo, ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager
from tests.conftest import REPO_DIR
from tests.utils import (
    load_server_config,
    validate_server_state,
)


@pytest.fixture
def patch_cli_dependencies(monkeypatch: MonkeyPatch):
    """
    Patch nonessential external boundaries so CLI end-to-end tests remain
    deterministic while still exercising the real command and manager stack.

    Args:
        monkeypatch (MonkeyPatch): Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "mada_tools.main.setup_logging",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.time.sleep",
        lambda _: None,
    )


@pytest.fixture
def capture_rich_prints(monkeypatch: MonkeyPatch) -> List[Tuple[Any, ...]]:
    """
    Capture Rich Console.print calls so tests can inspect printed objects.

    Args:
        monkeypatch (MonkeyPatch): Pytest monkeypatch fixture.

    Returns:
        list: Captured positional argument tuples from Console.print calls.
    """
    captured = []

    def fake_print(self, *args, **kwargs):
        captured.append(args)

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.Console.print",
        fake_print,
    )
    return captured


@pytest.fixture
def extract_tables():
    """
    A fixture for extracting printed Rich table objects from captured Console.print calls.

    Args:
        captured_prints: Captured Console.print argument tuples.

    Returns:
        A callable function for extracting Rich table outputs from Console.print calls.
    """

    def _extract_tables(captured_prints: List[Tuple[Any, ...]]) -> List[Any]:
        """
        Extract printed Rich Table objects from captured Console.print calls.

        Args:
            captured_prints: Captured Console.print argument tuples.

        Returns:
            list: Printed objects whose class name is Table.
        """
        tables = []
        for args in captured_prints:
            for obj in args:
                if obj.__class__.__name__ == "Table":
                    tables.append(obj)
        return tables

    return _extract_tables


@pytest.fixture
def register_server() -> Callable:
    """
    A fixture for registering servers in a real state file.

    Args:
        state_file: Path to the state file.
        name: Server name.
        pid: Optional process ID.
        status: Server status to persist.
        package: Package name.
        module_path: Python module path.
        host: Host value.
        port: Optional port value.

    Returns:
        A callable function for registering servers.
    """

    def _register_server(
        state_file: Path,
        name: str,
        pid: int | None,
        status: ServerStatus,
        package: str = "fake_pkg",
        module_path: str = "fake_pkg.alpha.server",
        host: str = "127.0.0.1",
        port: int | None = None,
    ):
        """
        Register a server entry in the real state file for status tests.

        Args:
            state_file: Path to the state file.
            name: Server name.
            pid: Optional process ID.
            status: Server status to persist.
            package: Package name.
            module_path: Python module path.
            host: Host value.
            port: Optional port value.
        """
        state_manager = ServerStateManager(state_file=state_file)
        state_manager.register_server(
            ServerInfo(
                name=name,
                package=package,
                module_path=module_path,
                pid=pid,
                host=host,
                port=port,
                status=status,
            ),
            {},
        )
        state_manager.update_server_status(name, status)

    return _register_server


class AgentTestRunner:
    """
    Async test harness for starting MCP servers, initializing an agent,
    and running prompt-based integration queries against it.
    """

    def __init__(
        self,
        servers_config_path: Path,
        agent_config_path: Path,
        agent_cls,
    ):
        """
        Initialize the test runner with server and agent configuration paths.

        Args:
            servers_config_path (Path): Path to the MCP servers config file.
            agent_config_path (Path): Path to the agent config file.
            agent_cls: Agent class used to create the test agent instance.
        """
        self.servers_config_path = Path(servers_config_path)
        self.agent_config_path = Path(agent_config_path)
        self.agent_cls = agent_cls

        self.server_manager = ServerManager(
            state_file=Path.home() / ".mada" / f"server_statuses_{uuid.uuid4().hex}.json"
        )
        self.stack: AsyncExitStack | None = None
        self.agent: Any | None = None
        self.servers_config: dict[str, Any] | None = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self):
        if not self.servers_config_path.exists():
            raise pytest.UsageError(f"Servers config not found: {self.servers_config_path}")

        if not self.agent_config_path.exists():
            raise pytest.UsageError(f"Agent config not found: {self.agent_config_path}")

        servers_data = json.loads(self.servers_config_path.read_text())
        agent_data = json.loads(self.agent_config_path.read_text())

        port_map = {}

        for name, server in servers_data.get("servers", {}).items():
            if "port" in server:
                port_map[name] = random.randint(1024, 65535)
                server["port"] = port_map[name]

        for name, mcp_server in agent_data.get("mcp_servers", {}).items():
            if name in port_map and "url" in mcp_server:
                mcp_server["url"] = f"http://localhost:{port_map[name]}/mcp"

        servers_randomized_path = self.servers_config_path.with_name(
            self.servers_config_path.stem + f"_randomized_{uuid.uuid4().hex}.json"
        )
        agent_randomized_path = self.agent_config_path.with_name(
            self.agent_config_path.stem + f"_randomized_{uuid.uuid4().hex}.json"
        )

        servers_randomized_path.write_text(json.dumps(servers_data, indent=2))
        agent_randomized_path.write_text(json.dumps(agent_data, indent=2))

        self.servers_config_path = servers_randomized_path
        self.agent_config_path = agent_randomized_path

        self.servers_config = load_server_config(self.servers_config_path)
        self.server_manager.start_servers(self.servers_config_path)

        try:
            active_servers = self.server_manager.state_manager.get_servers(validate=True)
            validate_server_state(self.servers_config["servers"], active_servers)

            self.agent = self.agent_cls(
                config_path=str(self.agent_config_path),
            )
            self.stack = AsyncExitStack()
            await self.stack.__aenter__()
            await self.agent.initialize(self.stack)

        except Exception:
            await self.close()
            raise

    async def process_query(self, prompt: str) -> str:
        assert self.agent is not None, "Call start() first"
        return await self.agent.process_query(prompt, add_tool_context=True)

    async def close(self):
        try:
            if self.stack is not None:
                await self.stack.aclose()
                self.stack = None
        finally:
            self.server_manager.stop_servers()


@pytest_asyncio.fixture
def agent_test_runner():
    async def _create(
        servers_config_file: str,
        agent_config_file: str,
    ):
        """
        Create an async factory for constructing AgentTestRunner instances
        from repository-relative config file names.
        """
        servers_config_path = REPO_DIR / "configs" / servers_config_file
        agent_config_path = REPO_DIR / "examples" / agent_config_file

        return AgentTestRunner(
            servers_config_path=servers_config_path,
            agent_config_path=agent_config_path,
            agent_cls=MultiServerAgent,
        )

    return _create
