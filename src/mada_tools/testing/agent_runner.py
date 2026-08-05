# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Reusable end-to-end agent test harnesses.

This module packages the repository's MCP-server-plus-agent integration pattern
into a reusable class that downstream extension packages can import directly.
The runner owns the full lifecycle of randomized config generation, server
startup, agent initialization, prompt execution, and cleanup.
"""

import json
import random
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mada_tools.agents import MultiServerAgent
from mada_tools.server_management.server_manager import ServerManager
from mada_tools.testing.server_checks import load_server_config, validate_server_state


class AgentTestRunner:
    """Async test harness for starting MCP servers and querying them through an agent.

    The runner accepts explicit paths to a server configuration and an agent
    configuration. During startup it randomizes server ports, rewrites matching
    MCP URLs in the agent config, launches the configured servers, validates the
    observed server state, and then initializes the requested agent class.

    The default agent class is `MultiServerAgent`, but tests may substitute any
    compatible implementation that accepts `config_path=...`, exposes an async
    `initialize(stack)` method, and supports `process_query(...)`.
    """

    def __init__(
        self,
        servers_config_path: Path,
        agent_config_path: Path,
        agent_cls=MultiServerAgent,
    ):
        """Initialize the test runner.

        Args:
            servers_config_path: Path to the MCP server configuration JSON.
            agent_config_path: Path to the agent configuration JSON.
            agent_cls: Agent implementation to instantiate after servers are
                running. Defaults to `MultiServerAgent`.
        """
        self.base_servers_config_path = Path(servers_config_path)
        self.base_agent_config_path = Path(agent_config_path)
        self.servers_config_path = self.base_servers_config_path
        self.agent_config_path = self.base_agent_config_path
        self.agent_cls = agent_cls

        self.server_manager = ServerManager(
            state_file=Path.home() / ".mada" / f"server_statuses_{uuid.uuid4().hex}.json"
        )
        self.stack: AsyncExitStack | None = None
        self.agent: Any | None = None
        self.servers_config: dict[str, Any] | None = None
        self._generated_config_paths: list[Path] = []

    async def __aenter__(self):
        """Start managed resources when entering an async context."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Always tear down managed resources when leaving an async context."""
        await self.close()

    async def start(self):
        """Prepare randomized configs, start servers, and initialize the agent.

        Raises:
            FileNotFoundError: If either input configuration path does not
                exist.
            Exception: Propagates any server-startup or agent-initialization
                error after best-effort cleanup.
        """
        if not self.base_servers_config_path.exists():
            raise FileNotFoundError(f"Servers config not found: {self.base_servers_config_path}")

        if not self.base_agent_config_path.exists():
            raise FileNotFoundError(f"Agent config not found: {self.base_agent_config_path}")

        servers_data = json.loads(self.base_servers_config_path.read_text(encoding="utf-8"))
        agent_data = json.loads(self.base_agent_config_path.read_text(encoding="utf-8"))

        port_map = {}

        for name, server in servers_data.get("servers", {}).items():
            if "port" in server:
                port_map[name] = random.randint(1024, 65535)
                server["port"] = port_map[name]

        for name, mcp_server in agent_data.get("mcp_servers", {}).items():
            if name in port_map and "url" in mcp_server:
                mcp_server["url"] = f"http://localhost:{port_map[name]}/mcp"

        self.servers_config_path = self.base_servers_config_path.with_name(
            self.base_servers_config_path.stem + f"_randomized_{uuid.uuid4().hex}.json"
        )
        self.agent_config_path = self.base_agent_config_path.with_name(
            self.base_agent_config_path.stem + f"_randomized_{uuid.uuid4().hex}.json"
        )
        self._generated_config_paths = [self.servers_config_path, self.agent_config_path]

        self.servers_config_path.write_text(json.dumps(servers_data, indent=2), encoding="utf-8")
        self.agent_config_path.write_text(json.dumps(agent_data, indent=2), encoding="utf-8")

        self.servers_config = load_server_config(self.servers_config_path)
        self.server_manager.start_servers(self.servers_config_path)

        try:
            active_servers = self.server_manager.state_manager.get_servers(validate=True)
            validate_server_state(self.servers_config["servers"], active_servers)

            self.agent = self.agent_cls(config_path=str(self.agent_config_path))
            self.stack = AsyncExitStack()
            await self.stack.__aenter__()
            await self.agent.initialize(self.stack)

        except Exception:
            await self.close()
            raise

    async def process_query(self, prompt: str) -> str:
        """Process one prompt against the initialized agent.

        Args:
            prompt: Natural-language prompt to send through the managed agent.

        Returns:
            str: Agent response including tool-context annotations.
        """
        assert self.agent is not None, "Call start() first"
        return await self.agent.process_query(prompt, add_tool_context=True)

    async def close(self):
        """Tear down the agent, servers, and temporary config files.

        Cleanup is best-effort so tests do not leak background servers or
        randomized config files even when startup or prompt execution fails.
        """
        try:
            if self.stack is not None:
                await self.stack.aclose()
                self.stack = None
        finally:
            self.server_manager.stop_servers()
            for path in self._generated_config_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._generated_config_paths = []
            self.servers_config_path = self.base_servers_config_path
            self.agent_config_path = self.base_agent_config_path
