# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Transport-agnostic runtime for foreground and background task execution."""

import asyncio
import logging
import threading
from datetime import UTC, datetime
from itertools import count
from typing import Any, Callable, Dict

LOG = logging.getLogger(__name__)


class BackgroundTaskRuntime:
    """Execute callables in the foreground or track them as background tasks."""

    def __init__(
        self,
        task_prefix: str = "task",
        task_state_callback: Callable[[Dict[str, Any]], None] | None = None,
        task_id_factory: Callable[[str, int], str] | None = None,
    ):
        """Initialize the shared background task runtime.

        Args:
            task_prefix (str):
                Prefix used when constructing externally visible task
                identifiers.
            task_state_callback (Callable[[Dict[str, Any]], None] | None):
                Optional callback invoked whenever task state
                is created or updated.
            task_id_factory (Callable[[str, int], str] | None):
                Optional factory used to build task ids from the configured
                prefix and next sequence number.
        """
        self._task_prefix = task_prefix
        self._task_state_callback = task_state_callback
        self._task_id_factory = task_id_factory or _default_task_id_factory
        self._task_lock = threading.Lock()
        self._task_counter = count(1)
        self._tasks: Dict[str, Dict[str, Any]] = {}

    async def run(
        self,
        func: Callable[..., Any],
        *args: Any,
        background: bool = True,
        task_name: str | None = None,
        task_id: str | None = None,
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
            task_id (str | None):
                Optional externally supplied task identifier. When omitted, the
                runtime constructs one using the configured prefix.
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
        task_info = self._create_task_info(task_name, task_id=task_id)
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

    def create_task_info(self, task_name: str, task_id: str | None = None) -> Dict[str, Any]:
        """Create and store the initial descriptor for a background task.

        Args:
            task_name (str):
                Human-readable name associated with the task.
            task_id (str | None):
                Optional externally supplied task identifier.

        Returns:
            Dict[str, Any]:
                A copy of the initial tracked task descriptor.
        """
        return self._create_task_info(task_name, task_id=task_id)

    def _create_task_info(self, task_name: str, task_id: str | None = None) -> Dict[str, Any]:
        """Create and store the initial descriptor for a background task.

        Args:
            task_name (str):
                Human-readable name associated with the task.
            task_id (str | None):
                Optional externally supplied task identifier.

        Returns:
            Dict[str, Any]:
                A copy of the initial tracked task descriptor.
        """
        with self._task_lock:
            task_sequence = next(self._task_counter)
            task_id = task_id or self._task_id_factory(self._task_prefix, task_sequence)
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
            task_info_copy = dict(task_info)

        self._publish_task_state(task_info_copy)
        return task_info_copy

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
                    task_info_copy = dict(task_info)
                    LOG.error("Background task %s (%s) was cancelled", task_name, task_id)
                else:
                    error = done_task.exception()
                    if error is not None:
                        task_info["status"] = "failed"
                        task_info["error"] = str(error)
                        task_info_copy = dict(task_info)
                        LOG.error("Background task %s (%s) failed: %s", task_name, task_id, error)
                    else:
                        task_info["status"] = "completed"
                        task_info["result"] = done_task.result()
                        task_info_copy = dict(task_info)
                        LOG.info("Background task %s (%s) completed", task_name, task_id)

            self._publish_task_state(task_info_copy)

        return _save

    def _publish_task_state(self, task_info: Dict[str, Any]) -> None:
        """Send a task-state snapshot to the optional external callback.

        Args:
            task_info (Dict[str, Any]):
                Snapshot of tracked task state.
        """
        if self._task_state_callback is None:
            return

        self._task_state_callback(dict(task_info))


def _utcnow_isoformat() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds.

    Returns:
        str: Current UTC timestamp formatted as an ISO-8601 string.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_task_id_factory(task_prefix: str, task_sequence: int) -> str:
    """Return the default task id format used by the shared runtime.

    Args:
        task_prefix: Prefix configured on the runtime.
        task_sequence: Sequence number allocated for the new task.

    Returns:
        str: Default task id in `<prefix>-<sequence>` form.
    """
    return f"{task_prefix}-{task_sequence}"
