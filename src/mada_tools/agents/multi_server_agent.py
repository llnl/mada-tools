# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Reusable multi-server agent support for MADA MCP servers.

The implementation in this module is the supported library version of the
multi-server AI agent previously housed only in the example application. It is
designed to be reused in three places:

- interactive local experiments through `examples/simple_agent_loop.py`
- automated end-to-end tests through `mada_tools.testing.AgentTestRunner`
- downstream applications or extension packages that want a simple
  OpenAI-compatible orchestrator for one or more running MCP servers
"""

import asyncio
import json
import logging
import os
import pathlib
import re
import signal
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Tool:
    """Describe one MCP tool exposed to the LLM client.

    Instances are created from MCP tool metadata returned by each connected
    server. The agent uses this normalized representation to advertise tools to
    the OpenAI chat-completions API while still remembering which MCP server is
    responsible for executing the tool.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str

    def to_openai_format(self) -> dict[str, Any]:
        """Convert the tool metadata into the OpenAI tool schema.

        Returns:
            dict[str, Any]: Payload matching the OpenAI tool-calling format.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[{self.server_name}] {self.description}",
                "parameters": self.input_schema,
            },
        }


class MultiServerAgent:
    """LLM agent that connects to multiple MADA MCP servers and uses their tools.

    The agent reads a JSON configuration file describing the model endpoint and
    a set of MCP servers, opens client sessions to each server, discovers the
    available tool set, and then lets an OpenAI-compatible model decide which
    tools to call while answering user prompts.

    The implementation is intentionally stateful: it stores conversation
    history, discovered tools, active MCP sessions, and background task routing
    data for the lifetime of the agent instance.
    """

    def __init__(self, config_path: str = "config.json"):
        """Initialize the multi-server MCP agent.

        Args:
            config_path: Path to the JSON configuration file describing the
                model settings and MCP server endpoints.
        """
        self.config = self._load_config(config_path)
        self.selected_servers = list(self.config["mcp_servers"].keys())

        model_config = self.config["model"]
        api_key = self._expand_env_var(model_config["api_key"])
        base_url = self._expand_env_var(model_config["base_url"])
        context_file = Path(self._expand_env_var(model_config["context_file"]))
        if not context_file.is_absolute():
            context_file = Path(config_path).resolve().parent / context_file

        LOGGER.info("API Base URL: %s", base_url)
        LOGGER.info("API Key: %s", "*" * (len(api_key) - 4) + api_key[-4:] if api_key else "Not set")
        LOGGER.info("Load model init context from: %s", context_file)

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.messages: list[dict[str, Any]] = []
        self.tools: list[Tool] = []
        self.model = model_config["model"]
        self._base_context_messages: list[dict[str, Any]] = []
        self.sessions: dict[str, ClientSession] = {}
        self.transports: dict[str, Any] = {}
        self._background_task_servers: dict[str, str] = {}

        if context_file:
            self._load_static_context(context_file)

        LOGGER.info("Multi-Server Agent initialized")
        LOGGER.info("Model: %s", self.model)
        LOGGER.info("Target servers: %s", ", ".join(self.selected_servers))

    def _load_static_context(self, path: str | Path) -> None:
        """Load optional system and seed messages from a JSON context file.

        Args:
            path: Path to a JSON file containing a `system_prompt` field and an
                optional `extra_messages` list.

        Raises:
            FileNotFoundError: If the configured context file does not exist.
        """
        path_obj = pathlib.Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Context file not found: {path_obj}")

        with path_obj.open("r", encoding="utf-8") as file:
            context_data = json.load(file)

        system_prompt = context_data.get("system_prompt")
        if system_prompt:
            self._base_context_messages.append({"role": "system", "content": system_prompt})

        for message in context_data.get("extra_messages", []):
            if isinstance(message, dict) and "role" in message and "content" in message:
                self._base_context_messages.append({"role": message["role"], "content": message["content"]})

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load the main agent configuration JSON file.

        Args:
            config_path: Location of the configuration file.

        Returns:
            dict[str, Any]: Parsed JSON configuration.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
        """
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Configuration file '{config_path}' not found. Please create a config.json file."
            ) from exc

    def _expand_env_var(self, value: str) -> str:
        """Expand environment-variable placeholders in configuration values.

        Supported forms are `${NAME}` and `${NAME:-default}`.

        Args:
            value: Raw string from the JSON configuration.

        Returns:
            str: The expanded string.

        Raises:
            ValueError: If a required environment variable is missing.
        """

        def replace_env_var(match: re.Match[str]) -> str:
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.getenv(var_name.strip(), default_value.strip())

            env_value = os.getenv(var_expr.strip())
            if env_value is None:
                raise ValueError(f"Environment variable {var_expr} is not set")
            return env_value

        return re.sub(r"\$\{([^}]+)\}", replace_env_var, value)

    async def initialize(self, stack: AsyncExitStack):
        """Connect to configured MCP servers and populate the tool catalog.

        Args:
            stack: Exit stack that owns the lifetime of all MCP transports and
                sessions opened by this agent.

        Raises:
            RuntimeError: If none of the configured servers can be reached.
        """
        LOGGER.info("\nConnecting to MADA MCP servers...")

        connected_servers = []
        for server_name in self.selected_servers:
            if server_name not in self.config["mcp_servers"]:
                LOGGER.warning("Warning: Server '%s' not found in config", server_name)
                continue

            server_config = self.config["mcp_servers"][server_name]
            connected = await self._connect_to_server(server_name, server_config, stack)
            if connected:
                connected_servers.append(server_name)

        if not connected_servers:
            raise RuntimeError("Failed to connect to any MCP servers")

        await self._setup_all_tools()

        LOGGER.info("\nAgent ready!")
        LOGGER.info("Connected servers: %s", ", ".join(connected_servers))
        LOGGER.info("Total tools available: %s", len(self.tools))

        tools_by_server: dict[str, list[str]] = {}
        for tool in self.tools:
            tools_by_server.setdefault(tool.server_name, []).append(tool.name)

        for server_name, tool_names in tools_by_server.items():
            LOGGER.info("  %s: %s", server_name, ", ".join(tool_names))

    async def _connect_to_server(self, server_name: str, server_config: dict[str, Any], stack: AsyncExitStack) -> bool:
        """Connect to one MCP server and cache its active session.

        Args:
            server_name: Logical server name from the config file.
            server_config: Configuration block containing at least the server
                URL and descriptive metadata.
            stack: Exit stack used to manage the underlying transport and
                session contexts.

        Returns:
            bool: `True` when the server connection and initial tool discovery
            succeed, otherwise `False`.
        """
        url = server_config["url"]
        try:
            http_client = httpx2.AsyncClient(
                headers=server_config.get("headers"),
                timeout=httpx2.Timeout(
                    server_config.get("timeout", 30),
                    read=server_config.get("sse_read_timeout", 150),
                ),
                follow_redirects=True,
            )
            await stack.enter_async_context(http_client)

            transport_cm = streamable_http_client(url, http_client=http_client)
            read_stream, write_stream, *_ = await stack.enter_async_context(transport_cm)

            session = ClientSession(read_stream, write_stream)
            await stack.enter_async_context(session)
            await session.initialize()

            tools_result = await session.list_tools()

            self.sessions[server_name] = session
            self.transports[server_name] = transport_cm

            LOGGER.info(
                "  SUCCESS: %s: %s tools (%s)",
                server_name,
                len(tools_result.tools),
                server_config["description"],
            )
            return True

        except Exception as exc:
            LOGGER.error("  ERROR: %s: Failed to connect - %s", server_name, exc)
            return False

    async def _setup_all_tools(self):
        """Refresh the flattened tool list from all connected MCP servers.

        This normalizes tool metadata from every active MCP session into the
        internal `Tool` dataclass used when sending tool definitions to the LLM.
        """
        self.tools = []

        for server_name, session in self.sessions.items():
            try:
                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    self.tools.append(
                        Tool(
                            name=tool.name,
                            description=tool.description,
                            input_schema=tool.inputSchema,
                            server_name=server_name,
                        )
                    )
            except Exception as exc:
                LOGGER.error("Error getting tools from %s: %s", server_name, exc)

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool call on the MCP server that owns the tool.

        Args:
            tool_name: Name of the tool selected by the model.
            tool_input: JSON-decoded tool arguments produced by the model.

        Returns:
            str: Normalized tool output text or a readable error string.
        """
        try:
            tool_server = None
            if tool_name == "get_background_task_result":
                task_id = tool_input.get("task_id")
                if isinstance(task_id, str):
                    tool_server = self._background_task_servers.get(task_id)

            if tool_server is None:
                for tool in self.tools:
                    if tool.name == tool_name:
                        tool_server = tool.server_name
                        break

            if tool_server is None:
                return f"Error: Tool '{tool_name}' not found"

            session = self.sessions.get(tool_server)
            if session is None:
                return f"Error: No connection to server '{tool_server}'"

            LOGGER.info("Executing %s on %s with args: %s", tool_name, tool_server, tool_input)
            result = await session.call_tool(tool_name, tool_input)

            if result.isError:
                return f"MCP tool error: {result.content}"

            if result.content:
                if hasattr(result.content[0], "text"):
                    tool_result = result.content[0].text
                else:
                    tool_result = str(result.content[0])
            else:
                tool_result = "Tool executed successfully (no output)"

            try:
                task_payload = json.loads(tool_result)
            except json.JSONDecodeError:
                task_payload = None

            if isinstance(task_payload, dict):
                task_id = task_payload.get("task_id")
                if isinstance(task_id, str):
                    self._background_task_servers[task_id] = tool_server

            return tool_result

        except Exception as exc:
            return f"Error executing {tool_name}: {exc}"

    @staticmethod
    def _stringify_content(content: Any) -> str:
        """Normalize message content so conversation history never stores null.

        Args:
            content: Value returned by the model or tool execution pipeline.

        Returns:
            str: Safe string representation for storage in message history.
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return str(content)

    def add_message(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ):
        """Append one message to the in-memory conversation history.

        Args:
            role: Chat role such as `system`, `user`, `assistant`, or `tool`.
            content: Optional textual content for the message.
            tool_calls: Optional assistant tool-call payloads to persist exactly
                as returned by the OpenAI client.
            tool_call_id: Optional identifier tying a tool response back to the
                originating assistant tool call.
        """
        message: dict[str, Any] = {"role": role}
        normalized_content = self._stringify_content(content)

        if role in {"system", "user", "assistant", "tool"}:
            message["content"] = normalized_content

        if role == "assistant" and tool_calls:
            message["tool_calls"] = tool_calls

        if role == "tool" and tool_call_id:
            message["tool_call_id"] = tool_call_id

        self.messages.append(message)

    async def process_query(self, query: str, max_tool_calls: int = 10, add_tool_context: bool = False) -> str:
        """Process one user query using the model and discovered MCP tools.

        The method appends the query to the conversation history, repeatedly
        asks the model for the next response, executes any requested tool calls,
        and stops when the model produces a final non-tool response or the
        maximum tool-call budget is reached.

        Args:
            query: User prompt to submit to the model.
            max_tool_calls: Maximum number of model/tool-call rounds before the
                method aborts and returns a failure message.
            add_tool_context: Whether to append a textual summary of executed
                tool calls to the final response. Tests use this to make tool
                execution assertions easier.

        Returns:
            str: Final model response or an error/status message.
        """
        self.add_message("user", query)
        tool_context = ""
        openai_tools = [tool.to_openai_format() for tool in self.tools]

        for _ in range(max_tool_calls):
            messages_for_call: list[dict[str, Any]] = list(self._base_context_messages) + list(self.messages)

            try:
                LOGGER.info("Making API call to %s with model %s", self.client.base_url, self.model)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages_for_call,
                    tools=openai_tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                LOGGER.error("Error Details: %s: %s", type(exc).__name__, exc)
                return f"Error calling LLM: {exc}"

            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []

            if tool_calls:
                self.add_message(
                    "assistant",
                    content=assistant_message.content,
                    tool_calls=[tool_call.model_dump() for tool_call in tool_calls],
                )

                for tool_call in tool_calls:
                    LOGGER.info("\nExecuting tool: %s", tool_call.function.name)
                    tool_arguments = json.loads(tool_call.function.arguments)
                    result = await self._execute_tool(
                        tool_name=tool_call.function.name,
                        tool_input=tool_arguments,
                    )
                    if add_tool_context:
                        tool_context += f"\nExecuted tool: {tool_call.function.name} with arguments: {tool_arguments}"
                    self.add_message("tool", content=result, tool_call_id=tool_call.id)

                continue

            final_content = self._stringify_content(assistant_message.content)
            if add_tool_context:
                final_content += tool_context
            self.add_message("assistant", content=final_content)
            return final_content

        max_tool_calls_message = (
            f"Agent stopped after reaching max_tool_calls={max_tool_calls} without producing a final response."
        )
        LOGGER.warning(max_tool_calls_message)
        return max_tool_calls_message

    async def chat_loop(self):
        """Run an interactive terminal chat loop backed by the reusable agent.

        This method imports `prompt_toolkit` lazily so downstream code that only
        uses the agent for automated tests or scripted calls does not need the
        interactive example dependency stack at import time.
        """
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application import run_in_terminal
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.patch_stdout import patch_stdout

        LOGGER.info("\n")
        LOGGER.info("MADA Multi-Server Agent - Interactive Chat")
        LOGGER.info("=" * 60)
        LOGGER.info("Connected servers: %s", ", ".join(self.sessions.keys()))
        LOGGER.info("Type your queries or 'quit' to exit.")
        LOGGER.info("Press Ctrl-C while a query is running to cancel it.")
        LOGGER.info("-" * 60)

        session = PromptSession()
        kb = KeyBindings()
        state: dict[str, Any] = {"running_task": None, "cancel_count": 0}

        def sigint_handler(signum, frame):
            del signum, frame
            if state["running_task"] and not state["running_task"].done():
                state["running_task"].cancel()

                def _log_cancel():
                    LOGGER.info("\nQuery canceled.")

                asyncio.get_event_loop().call_soon_threadsafe(lambda: run_in_terminal(_log_cancel))
                return

            state["cancel_count"] += 1

            def _log_interrupt():
                if state["cancel_count"] == 1:
                    LOGGER.info("\nPress Ctrl-C again to exit, or press Enter to continue.")
                else:
                    LOGGER.info("\nExiting.")

            asyncio.get_event_loop().call_soon_threadsafe(lambda: run_in_terminal(_log_interrupt))
            if state["cancel_count"] >= 2:
                raise KeyboardInterrupt()

        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, sigint_handler)

        try:
            while True:
                try:
                    with patch_stdout():
                        query = await session.prompt_async("Query: ", key_bindings=kb)
                    state["cancel_count"] = 0

                    if query.strip().lower() in ["quit", "exit", "q"]:
                        LOGGER.info("Goodbye!")
                        break

                    if not query.strip():
                        continue

                    LOGGER.info("Query: %s", query)
                    LOGGER.info("\nProcessing...")

                    task = asyncio.create_task(self.process_query(query))
                    state["running_task"] = task

                    try:
                        response = await task
                        LOGGER.info("\nResponse:\n%s", response)
                    except asyncio.CancelledError:
                        LOGGER.info("\nQuery was canceled by user.")
                    finally:
                        state["running_task"] = None

                except KeyboardInterrupt:
                    LOGGER.info("\nGoodbye!")
                    break
                except EOFError:
                    LOGGER.info("\nGoodbye!")
                    break
                except Exception as exc:
                    LOGGER.error("\nError: %s", exc)
        finally:
            signal.signal(signal.SIGINT, old_handler)
