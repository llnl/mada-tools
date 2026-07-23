# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Base MCP server class for common functionality."""

import argparse
import asyncio
import json
import logging
import os
import threading
import traceback
from abc import ABC
from datetime import datetime
from itertools import count
from typing import Any, Callable, Dict, Optional

from .env import expand_env_vars
from .exceptions import ToolExecutionError

LOG = logging.getLogger(__name__)


class BaseMCPServer(ABC):
    """Base class for all MADA MCP servers."""

    def __init__(self, server_name: str, description: Optional[str] = None):
        """
        Initialize the base MCP server.

        Args:
            server_name: Name of the MCP server
            description: Optional description of the server
        """
        self.server_name = server_name
        self.description = description or f"MCP Server for {server_name}"
        # self.mcp will be initialized in run_with_args after parsing config
        self.mcp = None
        # OAuth configuration (set during run_with_args)
        self.oauth_enabled = False
        self._tool_task_lock = threading.Lock()
        self._tool_task_counter = count(1)
        self._tool_tasks: Dict[str, Dict[str, Any]] = {}

    def parse_args(self) -> argparse.Namespace:
        """Parse command line arguments."""
        parser = argparse.ArgumentParser(description=self.description)
        parser.add_argument("--host", default=None, help="Host to bind to")
        parser.add_argument("--port", type=int, help="Port to bind to")
        parser.add_argument("--config", help="Configuration file path")
        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="streamable-http",
            help="Transport method (stdio, streamable-http)",
        )
        return parser.parse_args()

    def load_config(self, config_path: str, server_key: str) -> Dict[str, Any]:
        """
        Load configuration from file with environment variable expansion.

        Args:
            config_path: Path to configuration file
            server_key: Key for this server in the config

        Returns:
            Configuration dictionary for this server
        """
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            return config.get("servers", {}).get(server_key, {})
        except Exception as e:
            print(f"Warning: Could not load config {config_path}: {e}")
            return {}

    def expand_env_vars(self, value: str) -> str:
        """
        Expand environment variable references in configuration values.

        Supports formats:
        - ${VAR_NAME} - expands to os.getenv("VAR_NAME")
        - ${VAR_NAME:-default} - expands with default value if not set

        Args:
            value: String that may contain environment variable references

        Returns:
            String with environment variables expanded
        """
        return expand_env_vars(value, missing="preserve", strip_names=False)

    def run_with_args(self, server_key: str):
        """
        Run the server with command line argument parsing.

        Args:
            server_key: Key for this server in config files
        """
        from fastmcp import FastMCP

        args = self.parse_args()

        # Load config if provided
        config = {}
        if args.config:
            config = self.load_config(args.config, server_key)
            # Set environment variables from config with expansion
            env_vars = config.get("env_vars", {})
            for key, value in env_vars.items():
                if isinstance(value, str):
                    expanded_value = self.expand_env_vars(value)
                    os.environ.setdefault(key, expanded_value)
                else:
                    os.environ.setdefault(key, str(value))

        # Determine transport method and get host/port
        transport = args.transport or config.get("transport", "streamable-http")

        # Check if OAuth/JWT authentication is enabled in config
        auth_config = config.get("authentication", {})
        self.oauth_enabled = auth_config.get("oauth_enabled", False)

        # Initialize FastMCP with configuration based on transport
        if transport == "stdio":
            # For stdio, host/port are not used
            self.mcp = FastMCP(name=self.server_name)
        else:
            # Configure OAuth/JWT if enabled
            if self.oauth_enabled:
                from fastmcp.server.auth.providers.jwt import JWTVerifier

                jwks_uri = auth_config.get("jwks_uri")
                if not jwks_uri:
                    raise ValueError("OAuth enabled but 'jwks_uri' not specified in authentication config")
                LOG.info("OAuth/JWT authentication enabled")
                LOG.info(f"  JWKS URI: {jwks_uri}")
                verifier = JWTVerifier(
                    jwks_uri=jwks_uri,
                )
                self.mcp = FastMCP(name=self.server_name, auth=verifier)
            else:
                # No authentication
                self.mcp = FastMCP(name=self.server_name)

        # Register tools now that mcp is initialized
        self._register_base_tools()
        self._register_tools()

        # Start the server
        if transport == "stdio":
            print(f"Starting {self.server_name} with stdio transport")
            self.mcp.run(transport="stdio")
        elif transport == "streamable-http":
            # For HTTP transports, use host/port from config
            host = args.host or config.get("host", "localhost")
            port = args.port or config.get("port", 8000)
            print(f"Starting {self.server_name} with streamable-http on {host}:{port}")
            LOG.info(f"Debug endpoint available at: http://{host}:{port}/debug/headers")
            self.mcp.run(
                transport="streamable-http",
                host=host,
                port=port,
                stateless_http=True,
            )
        else:
            raise ValueError(f"Unsupported transport: {transport}")

    def _register_base_tools(self):
        """Register tools shared by all MADA MCP servers."""

        @self.mcp.tool()
        async def get_background_task_result(task_id: str) -> str:
            """
            Get the status and result for a background tool task.

            Args:
                task_id: Task id returned by a background tool call.

            Returns:
                JSON describing the task status, result, or error.
            """
            with self._tool_task_lock:
                task_info = self._tool_tasks.get(task_id)
                if task_info is None:
                    return json.dumps(
                        {
                            "task_id": task_id,
                            "status": "not_found",
                            "message": "Background task not found.",
                        },
                        indent=2,
                    )
                return json.dumps(task_info, default=str, indent=2)

    async def run_tool(self, func: Callable, *args, background: bool = True, **kwargs) -> Any:
        """
        Execute a tool and return either a background task descriptor or its payload.

        Args:
            func: The function/method to execute.
            background: Whether to run the tool in the background. Defaults to True.

        Returns:
            A JSON task descriptor when running in the background, otherwise the normalized tool payload.
        """
        if not background:
            return await asyncio.to_thread(self._execute_tool, func, *args, **kwargs)

        with self._tool_task_lock:
            task_id = f"tool-task-{next(self._tool_task_counter)}"
            tool_name = getattr(func, "__name__", repr(func))
            submitted_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            self._tool_tasks[task_id] = {
                "task_id": task_id,
                "tool_name": tool_name,
                "status": "running",
                "submitted_at": submitted_at,
                "completed_at": None,
                "result": None,
                "error": None,
            }
        task = asyncio.create_task(asyncio.to_thread(self._execute_tool, func, *args, **kwargs))

        def _save_background_result(done_task):
            completed_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            if done_task.cancelled():
                with self._tool_task_lock:
                    self._tool_tasks[task_id]["status"] = "cancelled"
                    self._tool_tasks[task_id]["completed_at"] = completed_at
                    self._tool_tasks[task_id]["error"] = "Background tool was cancelled."
                LOG.error(f"Background tool {tool_name} ({task_id}) was cancelled")
            else:
                error = done_task.exception()
                if error is not None:
                    with self._tool_task_lock:
                        self._tool_tasks[task_id]["status"] = "failed"
                        self._tool_tasks[task_id]["completed_at"] = completed_at
                        self._tool_tasks[task_id]["error"] = str(error)
                    LOG.error(f"Background tool {tool_name} ({task_id}) failed: {error}")
                else:
                    with self._tool_task_lock:
                        self._tool_tasks[task_id]["status"] = "completed"
                        self._tool_tasks[task_id]["completed_at"] = completed_at
                        self._tool_tasks[task_id]["result"] = done_task.result()
                    LOG.info(f"Background tool {tool_name} ({task_id}) completed")

        task.add_done_callback(_save_background_result)
        return json.dumps(
            {
                "task_id": task_id,
                "tool_name": tool_name,
                "status": "running",
                "submitted_at": submitted_at,
                "message": "Tool started in background.",
            },
            indent=2,
        )

    def _execute_tool(self, func: Callable, *args, **kwargs) -> Any:
        """
        Helper function to run a tool and handle errors.

        Args:
        func: The function/method to execute.
        background: Whether to run the tool in the background. Defaults to True.

        Returns:
        The successful payload returned by the tool.

        Raises:
        ToolExecutionError: If the tool execution fails.
        """
        try:
            success, payload = func(*args, **kwargs)
            if success:
                return payload
            else:
                raise ToolExecutionError(str(payload))
        except Exception as e:
            last = traceback.extract_tb(e.__traceback__)[-1]
            raise ToolExecutionError(f"Tool execution failed at {last.filename}:{last.lineno} in {last.name}: {e}")
