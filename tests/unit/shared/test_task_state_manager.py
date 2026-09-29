# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for persistent direct background task state."""

from mada_tools.shared.task_state_manager import TaskStateManager


def test_task_state_manager_persists_and_reads_back_task_payloads(tmp_path):
    """Verify one task payload can be written and read back from disk."""
    state_file = tmp_path / "direct_tasks.json"
    manager = TaskStateManager(state_file=state_file)
    task_info = {
        "task_id": "direct-task-1",
        "task_name": "job_monitor.read_logs",
        "status": "completed",
        "submitted_at": "2026-09-16T12:00:00Z",
        "completed_at": "2026-09-16T12:00:01Z",
        "result": '{"stdout": "ok", "stderr": ""}',
        "error": None,
    }

    manager.upsert_task(task_info)

    assert manager.get_task("direct-task-1") == task_info


def test_task_state_manager_returns_not_found_payload_for_unknown_tasks(tmp_path):
    """Verify unknown task ids return the shared not-found response shape."""
    manager = TaskStateManager(state_file=tmp_path / "direct_tasks.json")

    assert manager.get_task("direct-task-404") == {
        "task_id": "direct-task-404",
        "status": "not_found",
        "message": "Background task not found.",
    }
