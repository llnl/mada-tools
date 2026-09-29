# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the direct `job_monitor` adapter."""

import asyncio
import json

import pytest

from mada_tools.monitor.job_monitor.direct import JobMonitorDirectAdapter
from mada_tools.monitor.job_monitor.job_monitor_helper import JobMonitorHelper
from mada_tools.shared.task_state_manager import TaskStateManager


@pytest.mark.asyncio
async def test_job_monitor_direct_read_logs_matches_helper_payload(tmp_path):
    """Verify direct foreground log reads reuse the helper output exactly."""
    run_dir = _create_run_dir(tmp_path)
    adapter = JobMonitorDirectAdapter()
    helper = JobMonitorHelper()

    direct_payload = json.loads(await adapter.read_logs(str(run_dir), "stdout.log", "stderr.log"))
    helper_payload = json.loads(helper.read_logs(str(run_dir), "stdout.log", "stderr.log")[1])

    assert direct_payload == helper_payload


@pytest.mark.asyncio
async def test_job_monitor_direct_summarize_status_matches_helper_payload(tmp_path):
    """Verify direct foreground status summaries reuse the helper output exactly."""
    run_dir = _create_run_dir(tmp_path)
    adapter = JobMonitorDirectAdapter()
    helper = JobMonitorHelper()

    direct_payload = json.loads(await adapter.summarize_status(str(run_dir), "stdout.log", "stderr.log", exit_code=17))
    helper_payload = json.loads(helper.summarize_status(str(run_dir), "stdout.log", "stderr.log", exit_code=17)[1])

    assert direct_payload == helper_payload


def test_job_monitor_direct_background_execution_persists_task_results(tmp_path):
    """Verify direct background execution persists a completed task record."""
    run_dir = _create_run_dir(tmp_path)
    state_file = tmp_path / "direct_tasks.json"
    task_id = "direct-task-explicit"
    task_state_manager = TaskStateManager(state_file=state_file)
    task_runtime = JobMonitorDirectAdapter._create_task_runtime(task_state_callback=task_state_manager.upsert_task)
    adapter = JobMonitorDirectAdapter(task_runtime=task_runtime)

    result = asyncio.run(
        adapter.execute_action(
            "summarize_status",
            {
                "run_location": str(run_dir),
                "stdout_file": "stdout.log",
                "stderr_file": "stderr.log",
                "exit_code": 23,
            },
            background=True,
            task_id=task_id,
            wait_for_background_completion=True,
        )
    )

    assert result["task_id"] == task_id
    assert result["status"] == "completed"

    persisted = task_state_manager.get_task(task_id)
    assert persisted["status"] == "completed"
    assert json.loads(persisted["result"])["exit_code"] == 23


def _create_run_dir(tmp_path):
    """Create one synthetic run directory with representative stdout and stderr logs."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stdout.log").write_text("solver started\nstep complete\n", encoding="utf-8")
    (run_dir / "stderr.log").write_text("MPI_ABORT: rank 0\n", encoding="utf-8")
    return run_dir
