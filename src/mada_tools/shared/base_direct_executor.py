# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Shared base class for direct capability execution adapters."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from mada_tools.shared.task_runtime import BackgroundTaskRuntime
from mada_tools.shared.task_state_manager import TaskStateManager
from mada_tools.shared.tool_execution import execute_tool_contract

DIRECT_TASK_PREFIX = "direct-task"


class BaseDirectExecutor(ABC):
    """Execute direct capability actions through the shared task runtime."""

    capability_name: str = ""

    def __init__(self, task_runtime: BackgroundTaskRuntime | None = None):
        """Initialize the direct executor.

        Args:
            task_runtime: Optional shared background-task runtime. When omitted,
                a direct-CLI runtime is created.
        """
        self.task_runtime = task_runtime or self._create_task_runtime()

    @classmethod
    def run_background_task(
        cls,
        *,
        task_id: str,
        action: str,
        payload: dict[str, Any],
        tasks_file: str | None = None,
    ) -> None:
        """Execute one detached background task for this direct executor.

        Args:
            task_id: Externally visible task id for this background run.
            action: Direct action name to execute.
            payload: JSON-decoded payload for the selected action.
            tasks_file: Optional explicit task-state file path.
        """
        task_state_manager = TaskStateManager(Path(tasks_file) if tasks_file else None)
        task_runtime = cls._create_task_runtime(task_state_callback=task_state_manager.upsert_task)
        adapter = cls(task_runtime=task_runtime)
        asyncio.run(
            adapter.execute_action(
                action,
                payload,
                background=True,
                task_id=task_id,
                wait_for_background_completion=True,
            )
        )

    @classmethod
    def start_background_task(
        cls,
        *,
        callable_path: str,
        action: str,
        payload: dict[str, Any],
        tasks_file: str | None = None,
    ) -> dict[str, Any]:
        """Create task state and launch detached background work for this executor.

        Args:
            callable_path: Manifest-defined direct command import target.
            action: Direct action name to execute.
            payload: JSON-safe payload forwarded to the detached worker.
            tasks_file: Optional explicit task-state file path.

        Returns:
            dict[str, Any]: Initial task descriptor for the queued background task.
            If worker startup fails, returns the persisted failure payload instead.
        """
        task_state_manager = TaskStateManager(Path(tasks_file) if tasks_file else None)
        task_info = cls._create_task_runtime().create_task_info(cls.get_class_task_name(action))
        task_state_manager.upsert_task(task_info)

        command = [
            sys.executable,
            "-m",
            "mada_tools.main",
            "_run-direct-task",
            "--task-id",
            task_info["task_id"],
            "--callable-path",
            callable_path,
            "--action",
            action,
            "--payload",
            json.dumps(payload),
        ]

        if tasks_file:
            command.extend(["--tasks-file", tasks_file])

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": cls._background_worker_env(),
        }

        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True

        try:
            subprocess.Popen(command, **popen_kwargs)
        except Exception as exc:
            failed_task_info = dict(task_info)
            failed_task_info["status"] = "failed"
            failed_task_info["completed_at"] = (
                datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
            failed_task_info["error"] = str(exc)
            failed_task_info.pop("message", None)
            task_state_manager.upsert_task(failed_task_info)
            return failed_task_info

        return task_info

    @staticmethod
    def _create_task_runtime(
        task_state_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> BackgroundTaskRuntime:
        """Create a runtime configured for direct CLI execution.

        Args:
            task_state_callback: Optional callback invoked whenever tracked task
                state changes.

        Returns:
            BackgroundTaskRuntime: Runtime configured with direct-task id
            conventions.
        """
        return BackgroundTaskRuntime(
            task_prefix=DIRECT_TASK_PREFIX,
            task_state_callback=task_state_callback,
            task_id_factory=BaseDirectExecutor._direct_task_id_factory,
        )

    @staticmethod
    def _direct_task_id_factory(task_prefix: str, _task_sequence: int) -> str:
        """Build globally unique task ids for detached CLI workers.

        Args:
            task_prefix: Prefix configured on the shared runtime.
            _task_sequence: Unused sequence number supplied by the runtime.

        Returns:
            str: UUID-backed task id suitable for cross-process coordination.
        """
        return f"{task_prefix}-{uuid.uuid4().hex}"

    @staticmethod
    def _background_worker_env() -> dict[str, str]:
        """Build an environment that preserves the current Python import path.

        Returns:
            dict[str, str]: Environment variables for the worker process,
            including a `PYTHONPATH` value derived from the current
            interpreter state.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(str(path) for path in sys.path if path)
        return env

    async def execute_action(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        background: bool = False,
        task_id: str | None = None,
        wait_for_background_completion: bool = False,
    ) -> Any:
        """Execute one direct action in the foreground or background.

        Args:
            action: Action name to resolve and execute.
            payload: JSON-safe payload forwarded to the action handler.
            background: Whether to execute through the background-task runtime.
            task_id: Optional externally supplied task id.
            wait_for_background_completion: Whether to wait for the tracked
                background task to complete and return its final task payload.

        Returns:
            Any: Foreground payload, background task descriptor, or final
            background task payload when waiting for completion.
        """
        return await self.execute_handler(
            self.get_action_handler(action),
            payload,
            action_name=action,
            background=background,
            task_id=task_id,
            wait_for_background_completion=wait_for_background_completion,
        )

    async def execute_handler(
        self,
        handler: Callable[..., tuple[bool, Any]],
        payload: dict[str, Any],
        *,
        action_name: str,
        background: bool = False,
        task_id: str | None = None,
        wait_for_background_completion: bool = False,
    ) -> Any:
        """Execute one exact handler in the foreground or background.

        Args:
            handler: Bound handler implementing one direct action.
            payload: JSON-safe payload forwarded to the handler.
            action_name: Stable action name used for task naming.
            background: Whether to execute through the background-task runtime.
            task_id: Optional externally supplied task id.
            wait_for_background_completion: Whether to wait for the tracked
                background task to complete and return its final task payload.

        Returns:
            Any: Foreground payload, background task descriptor, or final
            background task payload when waiting for completion.
        """
        task_result = await self.task_runtime.run(
            execute_tool_contract,
            handler,
            background=background,
            task_id=task_id,
            task_name=self.get_task_name(action_name),
            **payload,
        )

        if not background or not wait_for_background_completion:
            return task_result

        return await self.wait_for_background_task(task_result["task_id"])

    def get_task_name(self, action: str) -> str:
        """Return the tracked task name used for one action.

        Args:
            action: Action name being executed.

        Returns:
            str: Task name in `<capability>.<action>` form.
        """
        return self.get_class_task_name(action)

    @classmethod
    def get_class_task_name(cls, action: str) -> str:
        """Return the tracked task name used for one action.

        Args:
            action: Action name being executed.

        Returns:
            str: Task name in `<capability>.<action>` form.
        """
        return f"{cls.capability_name}.{action}"

    async def wait_for_background_task(self, task_id: str, poll_interval: float = 0.01) -> dict[str, Any]:
        """Wait for one background task to complete and return its final state.

        Args:
            task_id: Tracked task identifier.
            poll_interval: Poll interval in seconds between state checks.

        Returns:
            dict[str, Any]: Final tracked task payload.
        """
        while True:
            current_task = self.task_runtime.get_task(task_id)
            if current_task["status"] != "running":
                return current_task
            await asyncio.sleep(poll_interval)

    @abstractmethod
    def get_action_handler(self, action: str) -> Callable[..., tuple[bool, Any]]:
        """Return the bound handler that implements one action.

        Args:
            action: Action name to resolve.

        Returns:
            Callable[..., tuple[bool, Any]]: Bound handler implementing the
            requested action.

        Raises:
            ValueError: If the action is unsupported.
        """
        raise NotImplementedError
