# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Persistent state management for direct background tasks."""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Dict, Generator, Optional

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class TaskStateManager:
    """Persist background task results across CLI invocations."""

    def __init__(self, state_file: Optional[Path] = None):
        """Initialize the task-state manager.

        Args:
            state_file (Optional[Path]):
                Optional state file. When omitted,
                `~/.mada/direct_task_results.json` is used.
        """
        self.state_file = state_file or Path.home() / ".mada" / "direct_task_results.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock_state(self) -> Generator[None]:
        """Acquire and release the task-state lock around a critical section.

        Yields:
            None: Control while the task-state lock is held.
        """
        lock_file = self.state_file.with_suffix(".lock")
        with open(lock_file, "a+b") as lock_handle:
            self._acquire_file_lock(lock_handle)
            try:
                yield
            finally:
                self._release_file_lock(lock_handle)

    @staticmethod
    def _acquire_file_lock(lock_handle: BinaryIO) -> None:
        """Acquire an exclusive lock using the platform's file locking API.

        Args:
            lock_handle: Open lock file handle used for synchronization.

        Raises:
            RuntimeError: If no supported file locking implementation is
                available on the current platform.
        """
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            return

        if msvcrt is not None:
            lock_handle.seek(0, 2)
            if lock_handle.tell() == 0:
                lock_handle.write(b"\0")
                lock_handle.flush()

            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
            return

        raise RuntimeError("No supported file locking implementation is available")

    @staticmethod
    def _release_file_lock(lock_handle: BinaryIO) -> None:
        """Release a previously acquired file lock.

        Args:
            lock_handle: Open lock file handle used for synchronization.

        Raises:
            RuntimeError: If no supported file locking implementation is
                available on the current platform.
        """
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            return

        if msvcrt is not None:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        raise RuntimeError("No supported file locking implementation is available")

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Return one tracked task record or a consistent not-found payload.

        Args:
            task_id: Identifier of the tracked task.

        Returns:
            Dict[str, Any]: Copy of the stored task payload, or a consistent
            `not_found` payload when the task id is unknown.
        """
        with self._lock_state():
            tasks = self._load_state()
            task_info = tasks.get(task_id)
            if task_info is None:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "message": "Background task not found.",
                }
            return dict(task_info)

    def upsert_task(self, task_info: Dict[str, Any]) -> None:
        """Insert or update one tracked task payload.

        Args:
            task_info: Task payload keyed by `task_id`.
        """
        task_id = task_info["task_id"]

        with self._lock_state():
            tasks = self._load_state()
            tasks[task_id] = dict(task_info)
            self._save_state(tasks)

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        """Load the persisted task state from disk.

        Returns:
            Dict[str, Dict[str, Any]]: Mapping of task ids to stored task
            payloads.
        """
        if not self.state_file.exists():
            return {}

        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        return {
            task_id: task_info for task_id, task_info in data.get("tasks", {}).items() if isinstance(task_info, dict)
        }

    def _save_state(self, tasks: Dict[str, Dict[str, Any]]) -> None:
        """Save task state atomically.

        Args:
            tasks: Mapping of task ids to task payloads.
        """
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tasks": tasks}, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.state_file)
