# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Unit tests for MaestroCommandExecutor.
"""

from pathlib import Path
from subprocess import CompletedProcess

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.workflow.weave.maestro.command_executor import MaestroCommandExecutor


@pytest.fixture
def executor() -> MaestroCommandExecutor:
    """
    Create a `MaestroCommandExecutor` instance for tests.

    Returns:
        An instance of the `MaestroCommandExecutor`.
    """
    return MaestroCommandExecutor()


class TestExecuteCommand:
    """Unit tests for `MaestroCommandExecutor.execute_command`."""

    def test_returns_success_and_combined_output_on_zero_returncode(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should return True and combined stdout/stderr when subprocess succeeds.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """

        def fake_run(*args, **kwargs):
            return CompletedProcess(args=["maestro"], returncode=0, stdout="ok\n", stderr="warn\n")

        monkeypatch.setattr("subprocess.run", fake_run)

        success, output = executor.execute_command(["maestro", "status"])

        assert success is True
        assert output == "ok\nwarn\n"

    def test_returns_failure_and_combined_output_on_nonzero_returncode(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should return False and combined stdout/stderr when subprocess fails.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """

        def fake_run(*args, **kwargs):
            return CompletedProcess(args=["maestro"], returncode=1, stdout="partial\n", stderr="error\n")

        monkeypatch.setattr("subprocess.run", fake_run)

        success, output = executor.execute_command(["maestro", "status"])

        assert success is False
        assert output == "partial\nerror\n"

    def test_passes_confirm_input_to_subprocess(self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch):
        """
        It should pass confirm text as subprocess input.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """

        captured = {}

        def fake_run(command, capture_output, text, input):
            captured["command"] = command
            captured["capture_output"] = capture_output
            captured["text"] = text
            captured["input"] = input
            return CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

        success, output = executor.execute_command(["maestro", "cancel"], confirm="y")

        assert success is True
        assert output == ""
        assert captured["command"] == ["maestro", "cancel"]
        assert captured["capture_output"] is True
        assert captured["text"] is True
        assert captured["input"] == "y"

    def test_returns_failure_and_exception_string_when_subprocess_raises(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should catch exceptions and return False with the exception message.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """

        def fake_run(*args, **kwargs):
            raise RuntimeError("subprocess unavailable")

        monkeypatch.setattr("subprocess.run", fake_run)

        success, output = executor.execute_command(["maestro", "status"])

        assert success is False
        assert "subprocess unavailable" in output


class TestRunWorkflow:
    """Unit tests for `MaestroCommandExecutor.run_workflow`."""

    def test_returns_failure_for_empty_workflow_yaml(self, executor: MaestroCommandExecutor):
        """
        It should reject an empty workflow YAML path.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
        """
        success, output = executor.run_workflow("")

        assert success is False
        assert output == "Workflow YAML specification cannot be an empty string."

    def test_returns_failure_when_workflow_yaml_does_not_exist(self, executor: MaestroCommandExecutor, tmp_path: Path):
        """
        It should reject a workflow YAML path that does not exist.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        missing = tmp_path / "missing.yaml"

        success, output = executor.run_workflow(missing)

        assert success is False
        assert output == "The provided workflow YAML specification does not exist in the file system."

    def test_constructs_minimal_run_command(
        self,
        executor: MaestroCommandExecutor,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should construct the base maestro run command with default options.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        workflow = tmp_path / "workflow.yaml"
        workflow.write_text("description: test\n", encoding="utf-8")

        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            captured["confirm"] = confirm
            return True, "started"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.run_workflow(workflow)

        assert success is True
        assert output == "started"
        assert captured["confirm"] is None
        assert captured["command"] == [
            "maestro",
            "run",
            str(workflow),
            "--autoyes",
            "--attempts",
            "1",
            "--rlimit",
            "1",
            "--throttle",
            "0",
            "--sleeptime",
            "60",
        ]

    def test_constructs_run_command_with_all_optional_flags(
        self,
        executor: MaestroCommandExecutor,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should include optional flags when requested.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        workflow = tmp_path / "workflow.yaml"
        workflow.write_text("description: test\n", encoding="utf-8")

        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "started"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.run_workflow(
            workflow_yaml=workflow,
            attempts=3,
            rlimit=2,
            throttle=5,
            sleeptime=120,
            output_path=str(tmp_path / "out"),
            dry=True,
            foreground=True,
            hash_ws=True,
            use_tmp=True,
        )

        assert success is True
        assert output == "started"
        assert captured["command"] == [
            "maestro",
            "run",
            str(workflow),
            "--autoyes",
            "--attempts",
            "3",
            "--rlimit",
            "2",
            "--throttle",
            "5",
            "--sleeptime",
            "120",
            "--out",
            str(tmp_path / "out"),
            "--dry",
            "-fg",
            "--hashws",
            "--usetmp",
        ]

    def test_accepts_string_path_for_workflow_yaml(
        self,
        executor: MaestroCommandExecutor,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should accept a string path as workflow_yaml.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        workflow = tmp_path / "workflow.yaml"
        workflow.write_text("description: test\n", encoding="utf-8")

        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "started"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.run_workflow(str(workflow))

        assert success is True
        assert output == "started"
        assert captured["command"][2] == str(workflow)


class TestGetStatuses:
    """Unit tests for `MaestroCommandExecutor.get_statuses`."""

    def test_returns_failure_when_no_workflows_provided(self, executor: MaestroCommandExecutor):
        """
        It should reject an empty workflow list.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
        """
        success, output = executor.get_statuses([])

        assert success is False
        assert output == "No workflows provided to `get_statuses`."

    def test_constructs_status_command_with_defaults(self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch):
        """
        It should construct the maestro status command with default arguments.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            captured["confirm"] = confirm
            return True, "status"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.get_statuses(["/tmp/study1", "/tmp/study2"])

        assert success is True
        assert output == "status"
        assert captured["confirm"] is None
        assert captured["command"] == [
            "maestro",
            "status",
            "/tmp/study1",
            "/tmp/study2",
            "--disable-pager",
            "--layout",
            "flat",
        ]

    def test_constructs_status_command_with_disable_theme(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should include --disable-theme when requested.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "status"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.get_statuses(
            [Path("/") / "tmp" / "study1"],
            layout="narrow",
            disable_theme=True,
        )

        assert success is True
        assert output == "status"
        assert captured["command"] == [
            "maestro",
            "status",
            str(Path("/") / "tmp" / "study1"),
            "--disable-pager",
            "--layout",
            "narrow",
            "--disable-theme",
        ]


class TestCancelWorkflows:
    """Unit tests for `MaestroCommandExecutor.cancel_workflows`."""

    def test_returns_failure_when_no_workflows_provided(self, executor: MaestroCommandExecutor):
        """
        It should reject an empty workflow list.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
        """
        success, output = executor.cancel_workflows([])

        assert success is False
        assert output == "No workflows provided to `cancel_workflows`."

    def test_constructs_cancel_command_and_confirms_yes(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should construct the maestro cancel command and pass confirmation input.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            captured["confirm"] = confirm
            return True, "cancelled"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.cancel_workflows(["/tmp/study1", "/tmp/study2"])

        assert success is True
        assert output == "cancelled"
        assert captured["command"] == ["maestro", "cancel", "/tmp/study1", "/tmp/study2"]
        assert captured["confirm"] == "y"


class TestUpdateWorkflows:
    """Unit tests for `MaestroCommandExecutor.update_workflows`."""

    def test_returns_failure_when_no_workflows_provided(self, executor: MaestroCommandExecutor):
        """
        It should reject an empty workflow list.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
        """
        success, output = executor.update_workflows([])

        assert success is False
        assert output == "No workflows provided to `update_workflows`."

    def test_returns_failure_when_no_settings_provided(self, executor: MaestroCommandExecutor):
        """
        It should reject calls that do not include any update settings.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
        """
        success, output = executor.update_workflows(["/tmp/study1"])

        assert success is False
        assert output == "No settings to update. Need to provide one of 'rlimit', 'throttle', or 'sleeptime'."

    def test_constructs_update_command_with_rlimit_only(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should construct the maestro update command with rlimit.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "updated"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.update_workflows(["/tmp/study1"], rlimit=4)

        assert success is True
        assert output == "updated"
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "--rlimit",
            "4",
        ]

    def test_constructs_update_command_with_throttle_only(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should construct the maestro update command with throttle.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "updated"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.update_workflows(["/tmp/study1"], throttle=8)

        assert success is True
        assert output == "updated"
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "--throttle",
            "8",
        ]

    def test_constructs_update_command_with_sleeptime_only(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should construct the maestro update command with sleeptime.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "updated"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.update_workflows(["/tmp/study1"], sleeptime=90)

        assert success is True
        assert output == "updated"
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "--sleep",
            "90",
        ]

    def test_constructs_update_command_with_all_settings(
        self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch
    ):
        """
        It should construct the maestro update command with all supported settings.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "updated"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.update_workflows(
            ["/tmp/study1", "/tmp/study2"],
            rlimit=0,
            throttle=10,
            sleeptime=120,
        )

        assert success is True
        assert output == "updated"
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "/tmp/study2",
            "--rlimit",
            "0",
            "--throttle",
            "10",
            "--sleep",
            "120",
        ]

    def test_all_zero_values_for_settings(self, executor: MaestroCommandExecutor, monkeypatch: MonkeyPatch):
        """
        It should allow this and should *not* trigger the "No settings to update" warning.

        Args:
            executor (MaestroCommandExecutor):
                An instance of the `MaestroCommandExecutor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        def fake_execute(command, confirm=None):
            captured["command"] = command
            return True, "updated"

        monkeypatch.setattr(executor, "execute_command", fake_execute)

        success, output = executor.update_workflows(
            ["/tmp/study1"],
            rlimit=0,
            throttle=0,
            sleeptime=0,
        )

        assert success is True
        assert output == "updated"
        assert captured["command"] == [
            "maestro",
            "update",
            "/tmp/study1",
            "--rlimit",
            "0",
            "--throttle",
            "0",
            "--sleep",
            "0",
        ]
