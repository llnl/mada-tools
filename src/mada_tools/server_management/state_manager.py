# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Persistent state management for MCP server processes.

This module provides a file backed mechanism for tracking the lifecycle and
health of MCP servers. It stores server metadata (PID, host, port, status,
timestamps, and other fields encapsulated by `ServerInfo`) in a JSON file
on disk, and uses a simple file lock to ensure atomic read and write
operations across multiple processes.
"""

import json
import logging
import socket
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, Optional

import psutil

from mada_tools.server_management import ServerInfo, ServerStatus

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

LOG = logging.getLogger(__name__)


class ServerStateManager:
    """
    Manage persistent state and health information for MCP servers.

    This class maintains a JSON backed registry of server processes,
    including their metadata and current status. It provides methods
    to register new servers, update their status, query running servers,
    and transparently remove entries for processes that are no longer
    alive or reachable.

    State is stored in a single JSON file on disk, and all read or write
    operations are protected by a simple file based lock to avoid
    concurrent modification issues when multiple processes interact
    with the registry.

    Attributes:
        state_file (Path):
            Path to the JSON file where server state is stored. If not
            explicitly provided at construction time, this defaults to
            `~/.mada/server_statuses.json`. The parent directory is
            created automatically if it does not already exist.

    Methods:
        register_server:
            Register a newly started server and persist its initial state.
        update_server_status:
            Update the status and last checked timestamp for an existing
            server entry.
        remove_server:
            Remove a server by name from the state file. Returns True if an
            entry was removed, or False if no matching server exists.
        get_server:
            Retrieve a single `ServerInfo` by server name, or `None` if the
            server is not registered.
        get_running_servers:
            Return a mapping of server names to `ServerInfo` objects. When
            `validate` is True, each entry is checked for process liveness
            (via PID) and, if a port is known, TCP health. Stale or dead
            entries are removed from the persisted state.
        cleanup_stale:
            Convenience method to remove dead or unreachable servers from
            the registry by invoking `get_running_servers(validate=True)`.
    """

    def __init__(self, state_file: Optional[Path] = None):
        """
        Constructor for `ServerStateManager`.

        Args:
            state_file (Optional[Path]): Optional state file. If not provided,
                "~/.mada/server_statuses.json" is used.
        """
        self.state_file = state_file or Path.home() / ".mada" / "server_statuses.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock_state(self) -> Iterator[None]:
        """
        Acquire and release the state file lock around a critical section.

        Args:
            None.

        Returns:
            Iterator[None]: Context manager that yields while the lock is held.

        Raises:
            OSError: If the lock file cannot be opened.
            RuntimeError: If no supported file locking implementation is available.
        """
        lock_file = self.state_file.with_suffix(".lock")
        with open(lock_file, "a+b") as f:
            self._acquire_file_lock(f)
            try:
                yield
            finally:
                self._release_file_lock(f)

    @staticmethod
    def _acquire_file_lock(lock_handle: BinaryIO) -> None:
        """
        Acquire an exclusive lock using the platform's file locking API.

        Args:
            lock_handle (BinaryIO): Open lock file handle.

        Raises:
            OSError: If the underlying platform lock operation fails.
            RuntimeError: If no supported file locking implementation is available.
        """
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            return

        if msvcrt is not None:
            # Windows locks a byte range, so ensure the file has at least one byte.
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
        """
        Release a previously acquired file lock.

        Args:
            lock_handle (BinaryIO): Open lock file handle.

        Raises:
            OSError: If the underlying platform unlock operation fails.
            RuntimeError: If no supported file locking implementation is available.
        """
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            return

        if msvcrt is not None:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        raise RuntimeError("No supported file locking implementation is available")

    def _load_state(self) -> Dict[str, ServerInfo]:
        """
        Load in the state of the servers from the state file.

        Returns:
            Dict[str, ServerInfo]: Dictionary mapping server names to ServerInfo objects
        """
        if not self.state_file.exists():
            return {}

        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        servers = {}
        for name, server_dict in data.get("servers", {}).items():
            try:
                servers[name] = ServerInfo.from_dict(server_dict)
            except Exception as e:
                # Log warning but continue - don't let one bad entry break everything
                LOG.warning(f"Failed to load server '{name}': {e}")

        return servers

    def _save_state(self, servers: Dict[str, ServerInfo]) -> None:
        """
        Save server state atomically.

        Args:
            servers (Dict[str, ServerInfo]): Dictionary mapping server names to
                ServerInfo objects.

        Returns:
            None.

        Raises:
            OSError: If writing the temporary state file or replacing the final
                state file fails.
            TypeError: If a server entry cannot be serialized to JSON.
        """
        state = {"servers": {name: server.to_dict() for name, server in servers.items()}}

        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def _is_process_running(self, pid: int) -> bool:
        """
        Check if PID is still running.

        Args:
            pid: Process ID to check

        Returns:
            bool: True if process is running
        """
        try:
            return psutil.Process(pid).is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            return False

    def _is_port_in_use(self, host: str, port: int, timeout: int = 1) -> bool:
        """
        Check whether a TCP service is already listening on the given host and port.

        Args:
            host (str): Hostname or IP address.
            port (int): Port number.
            timeout (int): Connection timeout in seconds.

        Returns:
            bool: True if a connection to host:port succeeds, meaning the port is in use.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                return sock.connect_ex((host, port)) == 0
        except OSError as exc:
            # Covers typical network and socket errors
            LOG.error(f"Port check failed for {host}:{port}, error: {exc}")
            return False

    def register_server(self, server_info: ServerInfo, config: dict):
        """
        Register a newly started server.

        Args:
            server_info: ServerInfo object with server details
            config: Configuration dict used to start the server
        """
        with self._lock_state():
            servers = self._load_state()

            server_info.started_at = datetime.now().isoformat()
            server_info.status = ServerStatus.STARTING

            servers[server_info.name] = server_info
            self._save_state(servers)

    def update_server_status(self, name: str, status: ServerStatus):
        """
        Update server status after health check.

        Args:
            name: Server name
            status: New ServerStatus
        """
        with self._lock_state():
            servers = self._load_state()
            if name in servers:
                servers[name].status = status
                servers[name].last_checked = datetime.now().isoformat()
                self._save_state(servers)

    def remove_server(self, name: str) -> bool:
        """
        Remove a server from state.

        Args:
            name: Server name

        Returns:
            bool: True if server was removed, False if not found
        """
        with self._lock_state():
            servers = self._load_state()
            if name in servers:
                del servers[name]
                self._save_state(servers)
                return True
            return False

    def get_server(self, name: str) -> Optional[ServerInfo]:
        """
        Get a specific server by name.

        Args:
            name: Server name

        Returns:
            ServerInfo if found, None otherwise
        """
        servers = self._load_state()
        return servers.get(name)

    def get_servers(self, validate: bool = True) -> Dict[str, ServerInfo]:
        """
        Get all servers, optionally validating they're still running.

        Args:
            validate: If True, check process liveness and update statuses accordingly

        Returns:
            Dict[str, ServerInfo]: Dictionary of server names to ServerInfo objects
        """
        with self._lock_state():
            servers = self._load_state()

            if not validate:
                return servers

            # Validate and update statuses
            changed = False

            for _, server_info in servers.items():
                if server_info.pid and self._is_process_running(server_info.pid):
                    # Process is running, check health if we have port info
                    if server_info.port:
                        if self._is_port_in_use(server_info.host, server_info.port):
                            if server_info.status != ServerStatus.RUNNING:
                                server_info.status = ServerStatus.RUNNING
                                changed = True
                        else:
                            if server_info.status != ServerStatus.UNHEALTHY:
                                server_info.status = ServerStatus.UNHEALTHY
                                changed = True
                    else:
                        # No port to check, just trust PID
                        if server_info.status != ServerStatus.RUNNING:
                            server_info.status = ServerStatus.RUNNING
                            changed = True
                else:
                    # Process not running
                    if server_info.status != ServerStatus.STOPPED:
                        server_info.status = ServerStatus.STOPPED
                        server_info.pid = None
                        changed = True

            if changed:
                self._save_state(servers)

            return servers

    def get_running_servers(self, validate: bool = True) -> Dict[str, ServerInfo]:
        """
        Get all running servers, optionally validating they're still running.

        Args:
            validate: If True, check that processes are actually running and clean up stale entries

        Returns:
            Dict[str, ServerInfo]: Dictionary of server names to ServerInfo objects (only running servers)
        """
        all_servers = self.get_servers(validate=validate)

        # Filter to only running/unhealthy servers (servers with active PIDs)
        running = {
            name: server_info
            for name, server_info in all_servers.items()
            if server_info.pid
            and server_info.status in [ServerStatus.RUNNING, ServerStatus.UNHEALTHY, ServerStatus.STARTING]
        }

        return running

    def cleanup_stale(self):
        """Remove dead servers from state"""
        self.get_running_servers(validate=True)
