# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""End-to-end tests for direct CLI job-monitor commands."""

import json
import sys
import threading

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.extensions.manifest import DirectCommandRegistration
from mada_tools.main import main


def test_main_mounts_extension_direct_commands_via_registry(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,
    capsys,
):
    """Verify the CLI mounts direct commands from the extension registry instead of hardcoded imports."""

    class PluginAlphaCmd(BaseCmd):
        def add_parser(self, subparsers):
            parser = subparsers.add_parser("plugin-alpha")
            parser.set_defaults(func=self.process_command)

        def process_command(self, args):
            print("plugin direct command")

    def register():
        return [PluginAlphaCmd()]

    monkeypatch.setattr(
        "mada_tools.extensions.registry.ExtensionRegistry.get_available_direct_commands",
        lambda self: [DirectCommandRegistration("plugin_alpha", "plugin_pkg.direct:register", "plugin_pkg")],
    )
    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"register": staticmethod(register)})(),
    )
    monkeypatch.setattr(sys, "argv", ["mada-tools", "plugin-alpha"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert "plugin direct command" in capsys.readouterr().out


def test_main_job_monitor_read_logs_runs_without_mcp(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,
    tmp_path,
    capsys,
):
    """Verify the direct `job-monitor read-logs` command runs through the CLI."""
    run_dir = _create_run_dir(tmp_path)
    _register_job_monitor_direct_command(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mada-tools", "job-monitor", "read-logs", str(run_dir), "stdout.log", "stderr.log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    payload = json.loads(capsys.readouterr().out)
    assert payload["stdout"].splitlines() == ["stdout line 1", "stdout line 2"]
    assert payload["stderr"].splitlines() == ["stderr line 1"]


def test_main_job_monitor_background_execution_and_task_result_retrieval(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,
    tmp_path,
    capsys,
):
    """Verify direct background execution and later task retrieval work through the CLI."""
    run_dir = _create_run_dir(tmp_path)
    tasks_file = tmp_path / "direct_tasks.json"
    _register_job_monitor_direct_command(monkeypatch)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "job-monitor",
            "summarize-status",
            str(run_dir),
            "stdout.log",
            "stderr.log",
            "--exit-code",
            "19",
            "--background",
            "--tasks-file",
            str(tasks_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    task_info = json.loads(capsys.readouterr().out)
    assert task_info["status"] == "running"

    task_result = None
    for _ in range(200):
        monkeypatch.setattr(
            sys,
            "argv",
            ["mada-tools", "task-result", task_info["task_id"], "--tasks-file", str(tasks_file)],
        )

        with pytest.raises(SystemExit) as poll_exc_info:
            main()

        assert poll_exc_info.value.code in (None, 0)
        task_result = json.loads(capsys.readouterr().out)
        if task_result["status"] != "running":
            break
        threading.Event().wait(0.05)

    assert task_result is not None
    assert task_result["status"] == "completed"
    summary = json.loads(task_result["result"])
    assert summary["exit_code"] == 19
    assert summary["stderr_tail"].splitlines() == ["stderr line 1"]


def _register_job_monitor_direct_command(monkeypatch: MonkeyPatch) -> None:
    """Patch direct-command discovery to return the built-in job-monitor registration only."""
    monkeypatch.setattr(
        "mada_tools.extensions.registry.ExtensionRegistry.get_available_direct_commands",
        lambda self: [
            DirectCommandRegistration(
                "job_monitor",
                "mada_tools.monitor.job_monitor.direct:JobMonitorDirectCmd",
                "mada_tools",
            )
        ],
    )


def _create_run_dir(tmp_path):
    """Create one synthetic run directory for CLI tests."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stdout.log").write_text("stdout line 1\nstdout line 2\n", encoding="utf-8")
    (run_dir / "stderr.log").write_text("stderr line 1\n", encoding="utf-8")
    return run_dir
