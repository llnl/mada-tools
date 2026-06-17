# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Integration tests for workflow management MCP tool flows.

These tests exercise `BaseMaestroServer` workflow tools together with the real
`MaestroCommandExecutor` command-building logic, while mocking the subprocess
boundary.
"""

from pathlib import Path
from subprocess import CompletedProcess

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.shared import ToolExecutionError


@pytest.fixture
def registered_tools_map(dummy_command_execution_server) -> dict:
    """
    Register all tools on the dummy server and return the tool registry.

    Args:
        dummy_command_execution_server (DummyMaestroCommandExecutionServer):
            Concrete test server instance.

    Returns:
        dict:
            Mapping of tool names to registered callables.
    """
    dummy_command_execution_server._register_tools()
    return dummy_command_execution_server.mcp.tools


class TestWorkflowManagementFlows:
    """
    Integration tests for workflow management tools registered by `BaseMaestroServer`.
    """

    def test_run_workflow_tool_executes_full_command_flow(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ):
        """
        It should execute the full `run_workflow` tool flow and invoke the expected
        Maestro CLI command through the subprocess boundary.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("description: test\n", encoding="utf-8")

        captured = {}

        def fake_run(command, capture_output, text, input):
            captured["command"] = command
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["input"] = input
            return CompletedProcess(args=command, returncode=0, stdout="started\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        tool = registered_tools_map["run_workflow"]
        result = tool(
            workflow_yaml=str(workflow_yaml),
            attempts=2,
            rlimit=3,
            throttle=4,
            sleeptime=90,
            output_path=str(tmp_path / "out"),
            dry=True,
            foreground=True,
            hash_ws=True,
            use_tmp=True,
        )

        assert result == "started\n"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["input"] is None
        assert captured["command"] == [
            "maestro",
            "run",
            str(workflow_yaml),
            "--autoyes",
            "--attempts",
            "2",
            "--rlimit",
            "3",
            "--throttle",
            "4",
            "--sleeptime",
            "90",
            "--out",
            str(tmp_path / "out"),
            "--dry",
            "-fg",
            "--hashws",
            "--usetmp",
        ]

    def test_run_workflow_tool_rejects_missing_yaml_file(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should surface missing workflow YAML validation as a `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        missing_yaml = tmp_path / "missing.yaml"
        tool = registered_tools_map["run_workflow"]

        with pytest.raises(
            ToolExecutionError,
            match="The provided workflow YAML specification does not exist in the file system.",
        ):
            tool(workflow_yaml=str(missing_yaml))

    def test_run_workflow_tool_rejects_pargs_without_pgen(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should reject pargs when pgen is not provided.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("description: test\n", encoding="utf-8")

        tool = registered_tools_map["run_workflow"]

        with pytest.raises(ToolExecutionError, match="`pargs` requires `pgen`"):
            tool(
                workflow_yaml=str(workflow_yaml),
                pargs=["a", "b"],
            )

    def test_get_statuses_tool_executes_full_command_flow(
        self,
        registered_tools_map: dict,
        monkeypatch: MonkeyPatch,
    ):
        """
        It should execute the full `get_statuses` tool flow and invoke the expected
        Maestro status command.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_run(command, capture_output, text, input):
            captured["command"] = command
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["input"] = input
            return CompletedProcess(args=command, returncode=0, stdout="status-ok\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        tool = registered_tools_map["get_statuses"]
        result = tool(
            workflow_dirs=["/tmp/study1", "/tmp/study2"],
            layout="narrow",
            disable_theme=True,
        )

        assert result == "status-ok\n"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["input"] is None
        assert captured["command"] == [
            "maestro",
            "status",
            "/tmp/study1",
            "/tmp/study2",
            "--disable-pager",
            "--layout",
            "narrow",
            "--disable-theme",
        ]

    def test_get_statuses_tool_propagates_empty_workflow_validation_error(
        self,
        registered_tools_map: dict,
    ):
        """
        It should surface empty workflow list validation from `get_statuses` as a `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
        """
        tool = registered_tools_map["get_statuses"]

        with pytest.raises(ToolExecutionError, match="No workflows provided to `get_statuses`"):
            tool(workflow_dirs=[])

    def test_cancel_workflows_tool_executes_full_command_flow(
        self,
        registered_tools_map: dict,
        monkeypatch: MonkeyPatch,
    ):
        """
        It should execute the full cancel_workflows tool flow and pass the
        expected confirmation input to the subprocess boundary.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_run(command, capture_output, text, input):
            captured["command"] = command
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["input"] = input
            return CompletedProcess(args=command, returncode=0, stdout="cancelled\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        tool = registered_tools_map["cancel_workflows"]
        result = tool(workflow_dirs=["/tmp/study1", "/tmp/study2"])

        assert result == "cancelled\n"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["input"] == "y"
        assert captured["command"] == [
            "maestro",
            "cancel",
            "/tmp/study1",
            "/tmp/study2",
        ]

    def test_cancel_workflows_tool_propagates_empty_workflow_validation_error(
        self,
        registered_tools_map: dict,
    ):
        """
        It should surface empty workflow list validation from cancel_workflows
        as a ToolExecutionError.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
        """
        tool = registered_tools_map["cancel_workflows"]

        with pytest.raises(ToolExecutionError, match="No workflows provided to `cancel_workflows`"):
            tool(workflow_dirs=[])

    def test_update_workflows_tool_executes_full_command_flow(
        self,
        registered_tools_map: dict,
        monkeypatch,
    ):
        """
        It should execute the full `update_workflows` tool flow and invoke the
        expected Maestro update command.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            monkeypatch:
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_run(command, capture_output, text, input):
            captured["command"] = command
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["input"] = input
            return CompletedProcess(args=command, returncode=0, stdout="updated\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        tool = registered_tools_map["update_workflows"]
        result = tool(
            workflow_dirs=["/tmp/study1", "/tmp/study2"],
            rlimit=5,
            throttle=6,
            sleeptime=120,
        )

        assert result == "updated\n"
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["input"] is None
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "/tmp/study2",
            "--rlimit",
            "5",
            "--throttle",
            "6",
            "--sleep",
            "120",
        ]

    def test_update_workflows_tool_propagates_no_settings_error(
        self,
        registered_tools_map: dict,
    ):
        """
        It should surface the no-settings validation failure as a `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
        """
        tool = registered_tools_map["update_workflows"]

        with pytest.raises(ToolExecutionError, match="No settings to update"):
            tool(workflow_dirs=["/tmp/study1"])

    def test_update_workflows_tool_propagates_empty_workflow_validation_error(
        self,
        registered_tools_map: dict,
    ):
        """
        It should surface empty workflow list validation from update_workflows
        as a ToolExecutionError.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
        """
        tool = registered_tools_map["update_workflows"]

        with pytest.raises(ToolExecutionError, match="No workflows provided to `update_workflows`"):
            tool(workflow_dirs=[], throttle=1)

    def test_workflow_tool_propagates_subprocess_failure_as_tool_execution_error(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
        monkeypatch,
    ):
        """
        It should convert a failed Maestro subprocess invocation into a `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
            monkeypatch:
                Pytest monkeypatch fixture.
        """
        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("description: test\n", encoding="utf-8")

        def fake_run(command, capture_output, text, input):
            return CompletedProcess(args=command, returncode=1, stdout="", stderr="maestro failed\n")

        monkeypatch.setattr("subprocess.run", fake_run)

        tool = registered_tools_map["run_workflow"]

        with pytest.raises(ToolExecutionError, match="maestro failed"):
            tool(workflow_yaml=str(workflow_yaml))
