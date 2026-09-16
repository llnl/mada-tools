# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the shared background task runtime."""

import asyncio

import pytest

from mada_tools.shared.task_runtime import BackgroundTaskRuntime


@pytest.mark.asyncio
async def test_background_task_runtime_runs_foreground_callables_directly():
    """Verify foreground execution returns the callable result directly."""
    runtime = BackgroundTaskRuntime(task_prefix="job")

    result = await runtime.run(lambda value: value.upper(), "alpha", background=False)

    assert result == "ALPHA"


@pytest.mark.asyncio
async def test_background_task_runtime_tracks_background_completion():
    """Verify background execution stores task state and result."""
    runtime = BackgroundTaskRuntime(task_prefix="job")

    task_info = await runtime.run(lambda: "payload", background=True, task_name="demo")

    assert task_info["task_id"].startswith("job-")
    assert task_info["status"] == "running"
    assert task_info["task_name"] == "demo"

    for _ in range(20):
        result = runtime.get_task(task_info["task_id"])
        if result["status"] != "running":
            break
        await asyncio.sleep(0.01)

    assert result["status"] == "completed"
    assert result["result"] == "payload"
    assert result["completed_at"] is not None


@pytest.mark.asyncio
async def test_background_task_runtime_tracks_background_failures():
    """Verify background execution stores errors from failed callables."""
    runtime = BackgroundTaskRuntime(task_prefix="job")

    def fail():
        raise RuntimeError("boom")

    task_info = await runtime.run(fail, background=True)

    for _ in range(20):
        result = runtime.get_task(task_info["task_id"])
        if result["status"] != "running":
            break
        await asyncio.sleep(0.01)

    assert result["status"] == "failed"
    assert result["error"] == "boom"
    assert result["completed_at"] is not None


def test_background_task_runtime_reports_missing_task_ids():
    """Verify unknown task ids return a consistent not-found payload."""
    runtime = BackgroundTaskRuntime(task_prefix="job")

    assert runtime.get_task("job-404") == {
        "task_id": "job-404",
        "status": "not_found",
        "message": "Background task not found.",
    }
