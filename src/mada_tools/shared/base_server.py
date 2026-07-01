# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Base MCP server class for common functionality."""

import argparse
import concurrent.futures
import json
import logging
import os
import threading
import traceback
from abc import ABC
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from fastmcp import FastMCP

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
        self._tool_executor = concurrent.futures.ThreadPoolExecutor(
            thread_name_prefix=f"{server_name.lower().replace(' ', '-')}-tool"
        )
        self._tool_task_lock = threading.Lock()
        self._tool_task_counter = 0

    def get_env_var(self, var_name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """
        Get environment variable with optional default and required validation.

        Args:
            var_name: Name of the environment variable
            default: Default value if not set
            required: Whether the variable is required

        Returns:
            The environment variable value

        Raises:
            ValueError: If required variable is not set
        """
        value = os.getenv(var_name, default)
        if required and value is None:
            raise ValueError(f"Required environment variable {var_name} is not set")
        return value

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
        import re

        def replace_env_var(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.getenv(var_name, default_value)
            else:
                return os.getenv(var_expr, match.group(0))  # Return original if not found

        # Pattern matches ${VAR_NAME} or ${VAR_NAME:-default}
        pattern = r"\$\{([^}]+)\}"
        return re.sub(pattern, replace_env_var, value)

    def run_with_args(self, server_key: str):
        """
        Run the server with command line argument parsing.

        Args:
            server_key: Key for this server in config files
        """
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

    def run_tool(self, func: Callable, *args, **kwargs) -> Any:
        """
        Start a tool in the background and return a tracking payload.

        Args:
            func: The function/method to execute.

        Returns:
            A JSON task descriptor for the started background tool.
        """
        task_id = self._next_tool_task_id()
        tool_name = getattr(func, "__name__", repr(func))
        submitted_at = self._utc_now()
        future = self._tool_executor.submit(self._execute_tool, func, *args, **kwargs)
        future.add_done_callback(
            lambda done_future, tracked_task_id=task_id, tracked_tool_name=tool_name: self._log_background_completion(
                tracked_task_id,
                tracked_tool_name,
                done_future,
            )
        )
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

    @staticmethod
    def _utc_now() -> str:
        """Return a stable UTC timestamp string for tool task metadata."""
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _next_tool_task_id(self) -> str:
        """Generate the next server-local tool task ID."""
        with self._tool_task_lock:
            self._tool_task_counter += 1
            return f"tool-task-{self._tool_task_counter}"

    def _log_background_completion(self, task_id: str, tool_name: str, future: concurrent.futures.Future) -> None:
        """Log failures from detached background tool execution."""
        try:
            future.result()
        except Exception as e:
            LOG.error("Background tool %s (%s) failed: %s", tool_name, task_id, e)

    def _execute_tool(self, func: Callable, *args, **kwargs) -> Any:
        """Execute one tool function and normalize `(success, payload)` results."""
        try:
            success, payload = func(*args, **kwargs)
            if success:
                return payload
            else:
                raise ToolExecutionError(str(payload))
        except Exception as e:
            last = traceback.extract_tb(e.__traceback__)[-1]
            raise ToolExecutionError(f"Tool execution failed at {last.filename}:{last.lineno} in {last.name}: {e}")
