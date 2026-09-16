# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Transport-agnostic runtime for foreground and background task execution."""

import asyncio
import logging
import threading
from datetime import datetime
from itertools import count
from typing import Any, Callable, Dict

LOG = logging.getLogger(__name__)


class BackgroundTaskRuntime:
    """Execute callables in the foreground or track them as background tasks."""

    def __init__(self, task_prefix: str = "task"):
        """Initialize the shared background task runtime.

        Args:
            task_prefix (str):
                Prefix used when constructing externally visible task
                identifiers.
        """
        self._task_prefix = task_prefix
        self._task_lock = threading.Lock()
        self._task_counter = count(1)
        self._tasks: Dict[str, Dict[str, Any]] = {}

    async def run(
        self,
        func: Callable[..., Any],
        *args: Any,
        background: bool = True,
        task_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run one callable in the foreground or as a tracked background task.

        Args:
            func (Callable[..., Any]):
                Callable to execute.
            *args (Any):
                Positional arguments passed to `func`.
            background (bool):
                Whether to execute the callable in the background and return a
                task descriptor instead of the callable result.
            task_name (str | None):
                Optional display name for the tracked task. When omitted, the
                runtime derives a name from `func`.
            **kwargs (Any):
                Keyword arguments passed to `func`.

        Returns:
            Any:
                The direct callable result for foreground execution, or a task
                descriptor dictionary for background execution.
        """
        if not background:
            return await asyncio.to_thread(func, *args, **kwargs)

        task_name = task_name or getattr(func, "__name__", repr(func))
        task_info = self._create_task_info(task_name)
        task_id = task_info["task_id"]
        task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        task.add_done_callback(self._save_background_result(task_id=task_id, task_name=task_name))
        return dict(task_info)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Return the tracked state for one task id.

        Args:
            task_id (str):
                Identifier of the tracked task.

        Returns:
            Dict[str, Any]:
                A copy of the tracked task state, or a consistent `not_found`
                payload when the task id is unknown.
        """
        with self._task_lock:
            task_info = self._tasks.get(task_id)
            if task_info is None:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "message": "Background task not found.",
                }
            return dict(task_info)

    def _create_task_info(self, task_name: str) -> Dict[str, Any]:
        """Create and store the initial descriptor for a background task.

        Args:
            task_name (str):
                Human-readable name associated with the task.

        Returns:
            Dict[str, Any]:
                A copy of the initial tracked task descriptor.
        """
        with self._task_lock:
            task_id = f"{self._task_prefix}-{next(self._task_counter)}"
            submitted_at = _utcnow_isoformat()
            task_info = {
                "task_id": task_id,
                "task_name": task_name,
                "status": "running",
                "submitted_at": submitted_at,
                "completed_at": None,
                "result": None,
                "error": None,
                "message": "Task started in background.",
            }
            self._tasks[task_id] = task_info
            return dict(task_info)

    def _save_background_result(self, task_id: str, task_name: str) -> Callable[[asyncio.Task[Any]], None]:
        """Build the completion callback used to persist background task results.

        Args:
            task_id (str):
                Identifier of the tracked task.
            task_name (str):
                Human-readable name associated with the task.

        Returns:
            Callable[[asyncio.Task[Any]], None]:
                Callback that persists the final task state when the asyncio
                task completes.
        """

        def _save(done_task: asyncio.Task[Any]) -> None:
            completed_at = _utcnow_isoformat()
            with self._task_lock:
                task_info = self._tasks.get(task_id)
                if task_info is None:
                    return

                task_info["completed_at"] = completed_at
                task_info.pop("message", None)

                if done_task.cancelled():
                    task_info["status"] = "cancelled"
                    task_info["error"] = "Background task was cancelled."
                    LOG.error("Background task %s (%s) was cancelled", task_name, task_id)
                    return

                error = done_task.exception()
                if error is not None:
                    task_info["status"] = "failed"
                    task_info["error"] = str(error)
                    LOG.error("Background task %s (%s) failed: %s", task_name, task_id, error)
                    return

                task_info["status"] = "completed"
                task_info["result"] = done_task.result()
                LOG.info("Background task %s (%s) completed", task_name, task_id)

        return _save


def _utcnow_isoformat() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds.

    Returns:
        str:
            Current UTC timestamp formatted as an ISO-8601 string.
    """
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
