# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Server management utilities for MCP servers.

This module provides the `ServerManager` class, which discovers, starts,
stops, restarts, and monitors MCP server processes. It integrates with
`ServerStateManager` to persist and validate server runtime state across
invocations. Configuration is passed per-operation rather than at
construction time, allowing a single manager instance to handle both
config-based operations (start, restart) and state-only operations
(stop, status).
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import psutil
from rich.console import Console
from rich.table import Table

from mada_tools.extensions.registry import ExtensionRegistry
from mada_tools.server_management import ServerInfo, ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager
from mada_tools.shared import PortInUseError

LOG = logging.getLogger(__name__)


class ServerManager:
    """
    Coordinate operations for MCP server processes.

    The `ServerManager` provides operations to start, stop, restart, and query
    the status of MCP server processes. It uses `ServerStateManager` to track
    and validate running server instances across sessions.

    Operations that start servers (start_servers, restart_servers) require a
    configuration file to be passed in. Operations that only need to interact
    with running servers (stop_servers, get_server_statuses) work purely from
    the state file.

    Attributes:
        state_manager (ServerStateManager):
            Manager responsible for persisting and validating server runtime state.
        _extension_registry (ExtensionRegistry):
            Registry used to resolve available MCP server registrations.

    Methods:
        start_servers:
            Start all or a subset of configured servers.
        start_server:
            Start a single server process and register it with the state manager.
        stop_servers:
            Stop all or a subset of currently running servers.
        stop_server:
            Stop a single server, attempting graceful shutdown before forcing.
        restart_servers:
            Restart all or a subset of configured servers.
        restart_server:
            Restart a single server, stopping it if running then starting a fresh instance.
        get_server_statuses:
            Retrieve `ServerInfo` objects describing current status of servers.
        print_server_statuses:
            Print a simple table of server statuses to stdout.
    """

    def __init__(self, state_file: Optional[Path] = None):
        """
        Constructor for the ServerManager.

        Args:
            state_file (Optional[Path]): Optional path to state file for ServerStateManager.
        """
        self.state_manager = ServerStateManager(state_file=state_file)
        self._extension_registry = ExtensionRegistry()
        LOG.debug("ServerManager initialized")

    def _load_servers(self, config_file: Path) -> Dict[str, ServerInfo]:
        """
        Load server configurations from the config file and sync with current state.

        Args:
            config_file: Path to the JSON configuration file

        Returns:
            A dictionary mapping server names to `ServerInfo` instances.

        Raises:
            FileNotFoundError:
                Raised when the provided configuration path does not exist.
        """
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        config = json.loads(config_file.read_text())

        # Discover all available server entry points
        available_servers = self._extension_registry.get_mcp_server_index()

        servers = {}
        server_configs = config.get("servers", {})

        # Get current running state from state manager
        running_servers = self.state_manager.get_running_servers(validate=True)

        for name, server_config in server_configs.items():
            # Verify the server is available
            if name not in available_servers:
                LOG.warning(f"Server '{name}' not found in discovered servers, skipping")
                continue
            registration = available_servers[name]

            # Get optional fields with defaults
            log_file = server_config.get("log_file")
            if log_file:
                log_file = Path(log_file).expanduser()
            else:
                log_file = Path.home() / ".mada" / "server_logs" / f"{name}.log"

            env_vars = server_config.get("env_vars", {})
            host = server_config.get("host", "localhost")
            port = server_config.get("port")

            # Check if server is currently running
            if name in running_servers:
                # Use the state manager's info which has current PID, status, etc.
                server_info = running_servers[name]
                # Update with any config changes
                server_info.package = registration.package
                server_info.module_path = registration.module_path
                server_info.log_file = log_file
                server_info.env_vars = env_vars
                server_info.host = host
                if port:
                    server_info.port = port
            else:
                # Create new ServerInfo instance
                server_info = ServerInfo(
                    name=name,
                    package=registration.package,
                    module_path=registration.module_path,
                    log_file=log_file,
                    env_vars=env_vars,
                    host=host,
                    port=port,
                    status=ServerStatus.STOPPED,
                )

            servers[name] = server_info

        return servers

    def start_servers(self, config_file: Path, server_names: Optional[List[str]] = None):
        """
        Start specified MCP servers or all servers if none specified.

        Args:
            config_file: Path to the JSON configuration file defining servers
            server_names: Optional list of server names to start. If None, starts all.

        Raises:
            ValueError:
                Raised when a requested server name is not present in the
                resolved configuration.
        """
        # Load servers from config
        servers = self._load_servers(config_file)

        if server_names:
            # Validate server names
            for name in server_names:
                if name not in servers:
                    raise ValueError(f"Unknown server: {name}")
            servers_to_start = {name: servers[name] for name in server_names}
        else:
            servers_to_start = servers

        for name, server_info in servers_to_start.items():
            try:
                self.start_server(config_file, name, server_info)
            except Exception as e:
                LOG.error(f"Failed to start server '{name}'.")
                raise e

    def start_server(self, config_file: Path, name: str, server_info: ServerInfo):
        """
        Start an individual MCP server.

        Args:
            config_file: Path to the JSON configuration file
            name: The server name
            server_info: A ServerInfo instance containing information about the server to start.
        """
        # Check if server is already running
        existing = self.state_manager.get_server(name)
        if existing and existing.pid:
            if self.state_manager._is_process_running(existing.pid):
                LOG.info(f"Server '{name}' is already running (PID: {existing.pid})")
                return

        LOG.info(f"Starting server '{name}'...")

        # Prepare log file
        server_info.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(server_info.log_file, "a")

        # Build command to run the server
        # Use the package's main entry point via python -m
        cmd = [
            sys.executable,
            "-m",
            server_info.module_path,
            "--config",
            str(config_file),
        ]

        # Prepare environment variables
        env = dict(os.environ)
        if server_info.env_vars:
            for key, value in server_info.env_vars.items():
                env[key] = str(value)

        # Verify that the port we're trying to use isn't already in use
        if server_info.port and self.state_manager._is_port_in_use(server_info.host, server_info.port):
            raise PortInUseError(
                f"Cannot start server '{name}', port {server_info.host}:{server_info.port} is already in use"
            )

        # Start the server process
        try:
            process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,  # Detach from parent process
            )

            # Update server info with process details
            server_info.pid = process.pid
            server_info.status = ServerStatus.STARTING
            server_info.started_at = datetime.now().isoformat()

            # Register with state manager
            config = json.loads(config_file.read_text())
            server_config = config.get("servers", {}).get(name, {})
            self.state_manager.register_server(server_info, server_config)

            # Give it a moment to start, then check health
            time.sleep(3)

            # Post-start check to see if the process is running
            if process.poll() is not None:
                self.state_manager.update_server_status(name, ServerStatus.FAILED)
                LOG.error(
                    f"Server '{name}' exited early with return code {process.returncode}. "
                    f"Check logs: {server_info.log_file}"
                )
                return

            LOG.info(f"Server '{name}' started with PID {process.pid}, logs: {server_info.log_file}")

            if server_info.port:
                if self.state_manager._is_port_in_use(server_info.host, server_info.port):
                    self.state_manager.update_server_status(name, ServerStatus.RUNNING)
                    LOG.info(f"Server '{name}' is healthy and running")
                else:
                    self.state_manager.update_server_status(name, ServerStatus.UNHEALTHY)
                    LOG.warning(f"Server '{name}' started but health check failed")

        except Exception as e:
            LOG.error(f"Failed to start server '{name}': {e}")
            server_info.status = ServerStatus.FAILED
            raise
        finally:
            if server_info.log_file and log_handle != subprocess.DEVNULL:
                log_handle.close()

    def stop_servers(
        self,
        server_names: Optional[List[str]] = None,
        config_file: Optional[Path] = None,
    ):
        """
        Stop specified running MCP servers or all servers if none specified.

        Args:
            server_names: Optional list of server names to stop. If None, stops all.
            config_file: Optional path to config file. If provided, shows all servers from config
                (even if stopped). If not provided, shows all servers from state.
        """
        # Get currently running servers from state
        running_servers = self.state_manager.get_running_servers(validate=True)

        # Determine allowed servers (filter by config if provided)
        if config_file:
            configured_servers = self._load_servers(config_file)
            allowed_servers = {
                name: running_servers[name] for name in configured_servers.keys() if name in running_servers
            }
        else:
            allowed_servers = running_servers

        # Further filter by requested server names
        if server_names:
            servers_to_stop = {name: allowed_servers[name] for name in server_names if name in allowed_servers}

            # Warn about servers that can't be stopped
            for name in server_names:
                if name not in allowed_servers:
                    if config_file:
                        if name not in configured_servers:
                            LOG.warning(f"Server '{name}' not found in config")
                        elif name not in running_servers:
                            LOG.warning(f"Server '{name}' is not running")
                    else:
                        LOG.warning(f"Server '{name}' is not running")
        else:
            servers_to_stop = allowed_servers

        # Stop each server
        for name, server_info in servers_to_stop.items():
            try:
                self.stop_server(name, server_info)
            except Exception as e:
                LOG.error(f"Failed to stop server '{name}': {e}")

    def stop_server(self, name: str, server_info: ServerInfo, timeout: int = 10) -> bool:
        """
        Stop an individual MCP server.

        Args:
            name: The server name to stop.
            server_info: ServerInfo with process details
            timeout: Seconds to wait for graceful shutdown before force kill

        Returns:
            bool: True if server was stopped, False if not running
        """
        LOG.info(f"Stopping server '{name}'...")

        if not server_info.pid:
            LOG.warning(f"Server '{name}' has no PID recorded")
            # Clean up state anyway
            self.state_manager.remove_server(name)
            return False

        pid = server_info.pid

        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            LOG.info(f"Server '{name}' (PID {pid}) is already stopped")
            self.state_manager.remove_server(name)
            return False
        except psutil.AccessDenied:
            LOG.error(f"Access denied when accessing server '{name}' (PID {pid})")
            return False

        # Check if this is actually our server process (safety check)
        try:
            # You could verify process name/cmdline matches expected server
            cmdline = process.cmdline()
            if not any(name in arg or server_info.package in arg for arg in cmdline):
                LOG.warning(f"PID {pid} doesn't appear to be server '{name}', skipping")
                self.state_manager.remove_server(name)
                return False
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass  # Process might have died, continue with cleanup

        # Attempt graceful shutdown
        try:
            LOG.debug(f"Sending terminate signal to server '{name}' (PID {pid})")
            process.terminate()  # Cross-platform SIGTERM equivalent

            # Wait for process to exit gracefully
            try:
                process.wait(timeout=timeout)
                LOG.info(f"Server '{name}' stopped gracefully")
                self.state_manager.remove_server(name)
                return True
            except psutil.TimeoutExpired:
                # Process didn't stop, force kill
                LOG.warning(f"Server '{name}' did not stop gracefully after {timeout}s, forcing shutdown")

                # Kill all child processes too
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)

                    # Kill children first
                    for child in children:
                        try:
                            LOG.debug(f"Killing child process {child.pid}")
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    # Then kill parent
                    parent.kill()

                    # Wait a moment for cleanup
                    parent.wait(timeout=2)

                    LOG.info(f"Server '{name}' force stopped")
                    self.state_manager.remove_server(name)
                    return True

                except psutil.NoSuchProcess:
                    # Process died during our kill attempt
                    LOG.info(f"Server '{name}' process terminated")
                    self.state_manager.remove_server(name)
                    return True

        except psutil.NoSuchProcess:
            # Process already gone
            LOG.info(f"Server '{name}' process already terminated")
            self.state_manager.remove_server(name)
            return True
        except psutil.AccessDenied:
            LOG.error(f"Permission denied when trying to stop server '{name}' (PID {pid})")
            return False
        except Exception as e:
            LOG.error(f"Error stopping server '{name}': {e}")
            return False

    def restart_servers(self, config_file: Path, server_names: Optional[List[str]] = None):
        """
        Restart specified MCP servers or all servers if none specified.

        Args:
            config_file: Path to the JSON configuration file defining servers
            server_names: Optional list of server names to restart. If None, restarts all configured servers.
        """
        # Load servers from config
        servers = self._load_servers(config_file)

        if server_names:
            # Validate server names exist in config
            for name in server_names:
                if name not in servers:
                    raise ValueError(f"Unknown server: {name}")
            servers_to_restart = server_names
        else:
            # Restart all configured servers
            servers_to_restart = list(servers.keys())

        for name in servers_to_restart:
            try:
                self.restart_server(config_file, name, servers[name])
            except Exception as e:
                LOG.error(f"Failed to restart server '{name}': {e}")

    def restart_server(self, config_file: Path, name: str, server_info: ServerInfo):
        """
        Restart a server (stop then start).

        Args:
            config_file: Path to the JSON configuration file
            name: Server name to restart
            server_info: ServerInfo instance from config
        """
        LOG.info(f"Restarting server '{name}'...")

        # Get current server info from state (if running)
        running_server = self.state_manager.get_server(name)

        if running_server and running_server.pid:
            # Stop if running
            stopped = self.stop_server(name, running_server)
            if stopped:
                LOG.info(f"Server '{name}' stopped, starting fresh...")
            else:
                LOG.warning(f"Failed to stop server '{name}', attempting to start anyway...")
        else:
            LOG.info(f"Server '{name}' is not running, starting fresh...")

        # Start fresh with config
        self.start_server(config_file, name, server_info)
        LOG.info(f"Server '{name}' restarted successfully")

    def get_server_statuses(
        self,
        server_names: Optional[List[str]] = None,
        config_file: Optional[Path] = None,
    ) -> Dict[str, ServerInfo]:
        """
        Get status information for specified servers or all servers.

        Args:
            server_names: Optional list of server names. If None, returns all running servers.
            config_file: Optional path to config file. If provided, shows all servers from config
                (even if stopped). If not provided, shows all servers from state.

        Returns:
            Dictionary mapping server names to their ServerInfo with current status.
        """
        servers: Dict[str, ServerInfo]
        if config_file is not None:
            # Get servers from config file
            servers = self._load_servers(config_file)
        else:
            # Get running servers from state manager
            servers = self.state_manager.get_servers(validate=True)

        # Determine which servers to check
        if server_names:
            for name in server_names[:]:
                if name not in servers:
                    LOG.warning(
                        f"Server '{name}' not found {'in config' if config_file is not None else 'by state manager'}."
                        "Removing this server from the filter."
                    )
                    server_names.remove(name)
            servers_to_check = server_names
        else:
            servers_to_check = list(servers.keys())

        statuses = {}
        for name in servers_to_check:
            if name in servers:
                statuses[name] = servers[name]
            else:
                LOG.warning(f"Server '{name}' not found in state.")

        return statuses

    def print_server_statuses(
        self,
        server_names: Optional[List[str]] = None,
        config_file: Optional[Path] = None,
    ):
        """
        Output the statuses of servers to the terminal.

        Args:
            server_names: Optional list of server names. If None, shows all running servers.
            config_file: Optional path to config file. If provided, shows all servers from config
                (even if stopped). If not provided, shows all servers from state.
        """
        statuses = self.get_server_statuses(server_names=server_names, config_file=config_file)
        console = Console()

        if not statuses:
            console.print("\nNo servers found.")
            return

        table = Table(title="MCP Server Status", show_header=True, header_style="bold magenta")

        # Add columns
        table.add_column("Server Name", style="cyan", no_wrap=True)
        table.add_column("Status", style="bold")
        table.add_column("PID", justify="right")
        table.add_column("Host:Port")

        # Add rows with status-based styling
        for name, server_info in statuses.items():
            pid_str = str(server_info.pid) if server_info.pid else "N/A"
            host_port = f"{server_info.host}:{server_info.port}" if server_info.port else "N/A"

            # Color-code status based on state
            status_display = server_info.status.value.upper()
            if server_info.status == ServerStatus.RUNNING:
                status_style = "[green]" + status_display + "[/green]"
            elif server_info.status == ServerStatus.STOPPED:
                status_style = "[dim]" + status_display + "[/dim]"
            elif server_info.status == ServerStatus.STARTING:
                status_style = "[yellow]" + status_display + "[/yellow]"
            elif server_info.status == ServerStatus.UNHEALTHY:
                status_style = "[red]" + status_display + "[/red]"
            elif server_info.status == ServerStatus.FAILED:
                status_style = "[bold red]" + status_display + "[/bold red]"
            else:
                status_style = status_display

            table.add_row(name, status_style, pid_str, host_port)

        console.print()
        console.print(table)
        console.print()
