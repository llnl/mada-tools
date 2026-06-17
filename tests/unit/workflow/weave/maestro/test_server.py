# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Unit tests for MaestroCommandExecutionServer.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.workflow.weave import MaestroCommandExecutionServer


class FakeMCP:
    """Minimal fake MCP object that records registered tool functions."""

    def __init__(self):
        """Initialize the fake MCP registry."""
        self.registered_tools = []

    def tool(self):
        """Return a decorator that records the decorated function."""

        def decorator(func):
            self.registered_tools.append(func)
            return func

        return decorator


class DummyCommandExecutionServer(MaestroCommandExecutionServer):
    """Test subclass of `MaestroCommandExecutionServer`."""

    def __init__(self):
        """Initialize the dummy server."""
        super().__init__()
        self.mcp = FakeMCP()


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """
    Create a temporary templates directory with sample YAML templates.

    Args:
        tmp_path (Path):
            Pytest tmp_path fixture.

    Returns:
        A path containing template studies for testing.
    """
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()

    (tmpl_dir / "example.yaml").write_text(
        """{#-
mcp_doc: |
  Example tool doc.
-#}
description:
    name: example
    description: example study for testing

env:
    variables:
        VALUE: {{ required_value }}
        OPTIONAL: {{ optional_value | default("abc") }}
""",
        encoding="utf-8",
    )

    (tmpl_dir / "alpha_study.yaml").write_text(
        """description:
    name: alpha
    description: alpha test study

env:
    variables:
        VALUE: {{ alpha_value }}
""",
        encoding="utf-8",
    )

    (tmpl_dir / "beta.yaml").write_text(
        """description:
    name: beta
    description: beta test study

env:
    variables:
        VALUE: {{ beta_value | default(5) }}
""",
        encoding="utf-8",
    )

    return tmpl_dir


@pytest.fixture
def server() -> DummyCommandExecutionServer:
    """
    Create a `DummyCommandExecutionServer` instance for tests.

    Returns:
        A dummy implementation of the `MaestroCommandExecutionServer` class.
    """
    return DummyCommandExecutionServer()


class TestMaestroCommandExecutionServerInit:
    """Unit tests for `MaestroCommandExecutionServer.__init__`."""

    def test_initializes_command_executor(self):
        """
        It should initialize `command_executor`.
        """
        srv = DummyCommandExecutionServer()

        assert srv.command_executor is not None


class TestRegisterTools:
    """Unit tests for `MaestroCommandExecutionServer._register_tools`."""

    def test_registers_expected_workflow_tools(self, server: DummyCommandExecutionServer):
        """
        It should register the workflow management MCP tools.

        Args:
            server (DummyCommandExecutionServer):
                A dummy implementation of the `MaestroCommandExecutionServer` class.
        """
        server._register_tools()

        tool_names = {tool.__name__ for tool in server.mcp.registered_tools}
        assert "run_workflow" in tool_names
        assert "get_statuses" in tool_names
        assert "cancel_workflows" in tool_names
        assert "update_workflows" in tool_names

    def test_run_workflow_delegates_to_run_tool(self, server: DummyCommandExecutionServer, monkeypatch: MonkeyPatch):
        """
        `run_workflow` should delegate to `run_tool`..

        Args:
            server (DummyCommandExecutionServer):
                A dummy implementation of the `MaestroCommandExecutionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        server._register_tools()
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "run_workflow")

        run_tool_mock = MagicMock(return_value="workflow started")
        monkeypatch.setattr(server, "run_tool", run_tool_mock)

        result = tool("workflow.yaml", attempts=2, dry=True)

        assert result == "workflow started"
        run_tool_mock.assert_called_once()

    def test_get_statuses_delegates_to_run_tool(self, server: DummyCommandExecutionServer, monkeypatch: MonkeyPatch):
        """
        `get_statuses` should delegate to `run_tool`.

        Args:
            server (DummyCommandExecutionServer):
                A dummy implementation of the `MaestroCommandExecutionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        server._register_tools()
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "get_statuses")

        run_tool_mock = MagicMock(return_value="status output")
        monkeypatch.setattr(server, "run_tool", run_tool_mock)

        result = tool(["/tmp/study1"], layout="narrow", disable_theme=True)

        assert result == "status output"
        run_tool_mock.assert_called_once()

    def test_cancel_workflows_delegates_to_run_tool(
        self,
        server: DummyCommandExecutionServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        `cancel_workflows` should delegate to `run_tool`.

        Args:
            server (DummyCommandExecutionServer):
                A dummy implementation of the `MaestroCommandExecutionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        server._register_tools()
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "cancel_workflows")

        run_tool_mock = MagicMock(return_value="cancelled")
        monkeypatch.setattr(server, "run_tool", run_tool_mock)

        result = tool(["/tmp/study1"])

        assert result == "cancelled"
        run_tool_mock.assert_called_once()

    def test_update_workflows_delegates_to_run_tool(
        self,
        server: DummyCommandExecutionServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        `update_workflows` should delegate to `run_tool`.

        Args:
            server (DummyCommandExecutionServer):
                A dummy implementation of the `MaestroCommandExecutionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        server._register_tools()
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "update_workflows")

        run_tool_mock = MagicMock(return_value="updated")
        monkeypatch.setattr(server, "run_tool", run_tool_mock)

        result = tool(["/tmp/study1"], throttle=5)

        assert result == "updated"
        run_tool_mock.assert_called_once()
