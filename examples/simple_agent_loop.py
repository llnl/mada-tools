#!/usr/bin/env python3
"""
Simple Agent Loop for MADA MCP Servers

This simple agent connects to multiple MADA MCP servers and uses their tools through OpenAI's function calling.
It can work with any combination of MADA MCP servers to execute engineering workflows using natural language.

Usage:
    python examples/simple_agent_loop.py [--config config.json]

Environment Variables:
    API_KEY: Your OpenAI API key (same as used by MADA Professor server)
    API_BASE_URL: OpenAI base URL (optional, defaults to https://livai-api.llnl.gov)

Configuration:
    Uses config.json for MCP server definitions and model configuration.
"""

import asyncio
import copy
import json
import logging
import os
import pathlib
import re
import signal
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any, Dict, List

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import AsyncOpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from pydantic import BaseModel


# Configure logging: logs go to both console and file
class DualLogger(logging.Logger):
    def query(self, msg, *args, **kwargs):
        super().info("Query: " + msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        print(msg, file=sys.stdout)
        super().info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        print(msg, file=sys.stdout)
        super().warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        print(msg, file=sys.stdout)
        super().error(msg, *args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        print(msg, file=sys.stdout)
        super().exception(msg, *args, exc_info=exc_info, **kwargs)

    def debug(self, msg, *args, **kwargs):
        print(msg, file=sys.stdout)
        super().debug(msg, *args, **kwargs)


logging.setLoggerClass(DualLogger)
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
log_filename = f"simple_agent_loop_history_{timestamp}.log"
file_handler = logging.FileHandler(log_filename)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
LOGGER.addHandler(file_handler)
LOGGER.propagate = False  # Prevent double logging


class Tool(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str  # Track which server this tool comes from

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert tool to OpenAI format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[{self.server_name}] {self.description}",
                "parameters": self.input_schema,
            },
        }


class MultiServerAgent:
    """
    LLM Agent that connects to multiple MADA MCP servers and uses their tools.

    This agent can connect to multiple MADA MCP servers simultaneously and use all
    available tools through an OpenAI-compatible interface with tool calling.
    """

    def __init__(self, config_path: str = "config.json"):
        """
        Initialize the multi-server MCP agent.

        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        # Use all servers defined in mcp_servers
        self.selected_servers = list(self.config["mcp_servers"].keys())

        # Setup OpenAI client
        model_config = self.config["model"]
        api_key = self._expand_env_var(model_config["api_key"])
        base_url = self._expand_env_var(model_config["base_url"])
        context_file = self._expand_env_var(model_config["context_file"])

        LOGGER.info(f"API Base URL: {base_url}")
        LOGGER.info(f"API Key: {'*' * (len(api_key) - 4) + api_key[-4:] if api_key else 'Not set'}")
        LOGGER.info(f"Load model init context from: {context_file}")

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        # Initialize state
        self.chat_history: List[Dict[str, Any]] = []
        self.tools: List[Tool] = []
        self.model = model_config["model"]
        self._base_context_messages: list[dict] = []
        self.sessions: Dict[str, ClientSession] = {}
        self.transports: Dict[str, Any] = {}

        self.pending_tasks: Dict[str, asyncio.Task] = {}
        self.task_counter = 0
        self.task_results: Dict[str, str] = {}

        # Load static context once at startup
        if context_file:
            self._load_static_context(context_file)

        LOGGER.info("Multi-Server Agent initialized")
        LOGGER.info(f"Model: {self.model}")
        LOGGER.info(f"Target servers: {', '.join(self.selected_servers)}")

    def _load_static_context(self, path: str) -> None:
        path_obj = pathlib.Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Context file not found: {path_obj}")

        with path_obj.open("r", encoding="utf-8") as f:
            ctx = json.load(f)

        system_prompt = ctx.get("system_prompt")
        if system_prompt:
            self._base_context_messages.append({"role": "system", "content": system_prompt})

        for msg in ctx.get("extra_messages", []):
            # basic validation
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                self._base_context_messages.append({"role": msg["role"], "content": msg["content"]})

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file '{config_path}' not found. Please create a config.json file.")

    def _expand_env_var(self, value: str) -> str:
        """Expand environment variables in config values."""

        def replace_env_var(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.getenv(var_name.strip(), default_value.strip())
            else:
                env_value = os.getenv(var_expr.strip())
                if env_value is None:
                    raise ValueError(f"Environment variable {var_expr} is not set")
                return env_value

        pattern = r"\$\{([^}]+)\}"
        return re.sub(pattern, replace_env_var, value)

    async def initialize(self, stack: AsyncExitStack):
        """Initialize the agent by connecting to all MCP servers and setting up tools."""
        LOGGER.info("\nConnecting to MADA MCP servers...")

        connected_servers = []
        for server_name in self.selected_servers:
            if server_name not in self.config["mcp_servers"]:
                LOGGER.warning(f"Warning: Server '{server_name}' not found in config")
                continue

            server_config = self.config["mcp_servers"][server_name]
            connected = await self._connect_to_server(server_name, server_config, stack)
            if connected:
                connected_servers.append(server_name)

        if not connected_servers:
            raise RuntimeError("Failed to connect to any MCP servers")

        await self._setup_all_tools()

        LOGGER.info("\nAgent ready!")
        LOGGER.info(f"Connected servers: {', '.join(connected_servers)}")
        LOGGER.info(f"Total tools available: {len(self.tools)}")

        # Show tools by server
        tools_by_server = {}
        for tool in self.tools:
            if tool.server_name not in tools_by_server:
                tools_by_server[tool.server_name] = []
            tools_by_server[tool.server_name].append(tool.name)

        for server, tool_names in tools_by_server.items():
            LOGGER.info(f"  {server}: {', '.join(tool_names)}")

    async def _connect_to_server(self, server_name: str, server_config: Dict[str, Any], stack: AsyncExitStack) -> bool:
        """Connect to a single MCP server."""
        url = server_config["url"]
        try:
            # Enter the MCP transport context via the AsyncExitStack
            transport_cm = streamablehttp_client(url)
            read_stream, write_stream, _ = await stack.enter_async_context(transport_cm)

            # Create and enter the session via the stack as well
            session = ClientSession(read_stream, write_stream)
            await stack.enter_async_context(session)

            await session.initialize()

            tools_result = await session.list_tools()

            self.sessions[server_name] = session
            # You usually do not need to keep the transport separately any more,
            # but if you want it for logging, store the CM object:
            self.transports[server_name] = transport_cm

            LOGGER.info(f"  SUCCESS: {server_name}: {len(tools_result.tools)} tools ({server_config['description']})")
            return True

        except Exception as e:
            LOGGER.error(f"  ERROR: {server_name}: Failed to connect - {e}")
            return False

    async def _setup_all_tools(self):
        """Setup tools from all connected MCP servers."""
        self.tools = []

        for server_name, session in self.sessions.items():
            try:
                # Get tools from MCP server
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
            except Exception as e:
                LOGGER.error(f"Error getting tools from {server_name}: {e}")

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool using the appropriate MCP server."""
        try:
            # Find which server has this tool
            tool_server = None
            for tool in self.tools:
                if tool.name == tool_name:
                    tool_server = tool.server_name
                    break

            if tool_server is None:
                return f"Error: Tool '{tool_name}' not found"

            session = self.sessions.get(tool_server)
            if session is None:
                return f"Error: No connection to server '{tool_server}'"

            LOGGER.info(f"Executing {tool_name} on {tool_server} with args: {tool_input}")
            result = await session.call_tool(tool_name, tool_input)

            if result.isError:
                return f"MCP tool error: {result.content}"

            # Handle different result content types
            if result.content:
                if hasattr(result.content[0], "text"):
                    return result.content[0].text
                else:
                    return str(result.content[0])
            else:
                return "Tool executed successfully (no output)"

        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    @staticmethod
    def _extract_tool_task(tool_output: str) -> Dict[str, Any] | None:
        """Parse a JSON tool-task payload when present."""
        try:
            payload = json.loads(tool_output)
        except (TypeError, json.JSONDecodeError):
            return None

        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id.startswith("tool-task-"):
            return payload
        return None

    @staticmethod
    def _stringify_content(content: Any) -> str:
        """Normalize message content so conversation history never stores null."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return str(content)

    def add_message(
        self,
        role: str,
        content: str = None,
        tool_calls: List[Dict] = None,
        tool_call_id: str = None,
    ):
        """Add a message to the conversation history."""
        message = {"role": role}
        normalized_content = self._stringify_content(content)

        if role == "system":
            message["content"] = normalized_content
        elif role == "user":
            message["content"] = normalized_content
        elif role == "assistant":
            message["content"] = normalized_content
            if tool_calls:
                message["tool_calls"] = tool_calls
        elif role == "tool":
            message["content"] = normalized_content
            if tool_call_id:
                message["tool_call_id"] = tool_call_id

        self.chat_history.append(message)

    async def process_query(self, query: str, chat_snapshot: List[Dict[str, Any]], task_id: str = "", max_tool_calls: int = 10) -> str:
        """
        Process a query using LLM and available MADA MCP tools.

        Args:
            query: The user query.
            task_id: Background task id for logging.
            max_tool_calls: Maximum number of LLM/tool-call rounds before aborting.

        Returns:
            The response from LLM.
        """
        messages: List[Dict[str, Any]] = list(self._base_context_messages) + list(chat_snapshot)
        messages.append({"role": "user", "content": query})

        openai_tools = [tool.to_openai_format() for tool in self.tools]

        for step in range(max_tool_calls):
            try:
                LOGGER.info(f"[{task_id}] Making API call to {self.client.base_url} with model {self.model}\n\n")
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                )
            except Exception as e:
                LOGGER.error(f"[{task_id}] Error Details: {type(e).__name__}: {e}")
                return f"Error calling LLM: {e}"

            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.content or "",
                        "tool_calls": [tc.model_dump() for tc in tool_calls],
                    }
                )

                started_tasks: List[Dict[str, str]] = []
                for tool_call in tool_calls:
                    tool_args = json.loads(tool_call.function.arguments)
                    LOGGER.info(f"[{task_id}] Executing tool: {tool_call.function.name}")
                    tool_result = await self._execute_tool(
                        tool_call.function.name,
                        tool_args,
                    )
                    tool_task = self._extract_tool_task(tool_result)
                    if tool_task and tool_task.get("status") in {"queued", "running"}:
                        started_tasks.append(
                            {
                                "tool_name": tool_call.function.name,
                                "task_id": tool_task["task_id"],
                                "status": str(tool_task["status"]),
                            }
                        )

                    messages.append(
                        {
                            "role": "tool",
                            "content": tool_result,
                            "tool_call_id": tool_call.id,
                        }
                    )

                if started_tasks:
                    lines = ["Started background tool tasks:"]
                    for started_task in started_tasks:
                        lines.append(
                            f"- {started_task['tool_name']}: {started_task['task_id']} ({started_task['status']})"
                        )
                    lines.append("This query will not wait for completion.")
                    return "\n".join(lines)

                continue

            final_content = self._stringify_content(assistant_message.content)
            messages.append({"role": "assistant", "content": final_content})
            return final_content

        max_tool_calls_message = (
            f"Agent stopped after reaching max_tool_calls={max_tool_calls} without producing a final response."
        )
        LOGGER.warning(f"[{task_id}] {max_tool_calls_message}")
        return max_tool_calls_message

    async def chat_loop(self):
        """Run an interactive chat loop with the MADA MCP servers."""
        LOGGER.info("\n")
        LOGGER.info("MADA Multi-Server Agent - Interactive Chat")
        LOGGER.info("=" * 60)
        LOGGER.info(f"Connected servers: {', '.join(self.sessions.keys())}")
        LOGGER.info("Type your queries or 'quit' to exit.")
        LOGGER.info("Press Ctrl-C while a query is running to cancel it.")
        LOGGER.info("-" * 60)

        # Prompt session gives us readline‑like editing (arrow keys etc.)
        session = PromptSession()

        # Key bindings: first Ctrl‑C cancels current query, second exits
        kb = KeyBindings()
        state = {"running_task": None, "cancel_count": 0}

        def sigint_handler(signum, frame):
            # If a task is running, cancel it
            if state["running_task"] and not state["running_task"].done():
                state["running_task"].cancel()

                def _log_cancel():
                    LOGGER.info("\nQuery canceled.")

                asyncio.get_event_loop().call_soon_threadsafe(lambda: run_in_terminal(_log_cancel))
            else:
                # At prompt, increment cancel count
                state["cancel_count"] += 1

                def _log_interrupt():
                    if state["cancel_count"] == 1:
                        LOGGER.info("\nPress Ctrl-C again to exit, or press Enter to continue.")
                    else:
                        LOGGER.info("\nExiting.")

                asyncio.get_event_loop().call_soon_threadsafe(lambda: run_in_terminal(_log_interrupt))
                if state["cancel_count"] >= 2:
                    LOGGER.info(f"Cancel count: {state['cancel_count']}")
                    raise KeyboardInterrupt()

        # Set custom SIGINT handler for the chat loop
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

                    if query.strip().lower() == "tasks":
                        LOGGER.info(f"Pending tasks: {list(self.pending_tasks.keys())}")
                        LOGGER.info(f"Completed tasks: {list(self.task_results.keys())}")
                        continue

                    LOGGER.query(query)
                    task_id = self.submit_query(query)
                    LOGGER.info(f"\n[{task_id}] Started in background")

                except KeyboardInterrupt:
                    LOGGER.info("\nGoodbye!")
                    break
                except EOFError:
                    LOGGER.info("\nGoodbye!")
                    break
                except Exception as e:
                    LOGGER.error(f"\nError: {str(e)}")
        finally:
            signal.signal(signal.SIGINT, old_handler)

    def submit_query(self, query: str) -> str:
        self.task_counter += 1
        task_id = f"task-{self.task_counter}"

        snapshot = copy.deepcopy(self.chat_history)

        task = asyncio.create_task(self.process_query(query, snapshot, task_id=task_id))
        self.pending_tasks[task_id] = task

        def done_callback(t: asyncio.Task):
            try:
                result = t.result()
                self.task_results[task_id] = result
                self.chat_history.append({"role": "user", "content": query})
                self.chat_history.append({"role": "assistant", "content": result})
                LOGGER.info(f"\n[{task_id}] Completed:\n{result}")
            except Exception as e:
                self.task_results[task_id] = f"Error: {e}"
                LOGGER.error(f"\n[{task_id}] Failed: {e}")
            finally:
                self.pending_tasks.pop(task_id, None)

        task.add_done_callback(done_callback)
        return task_id

async def main():
    """Main function to run the multi-server agent with MADA MCP servers."""
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Multi-Server Agent for MADA MCP Servers")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Configuration file path (default: config.json)",
    )
    args = parser.parse_args()

    # Create and initialize agent
    agent = MultiServerAgent(config_path=args.config)

    try:
        async with AsyncExitStack() as stack:
            # Initialize the agent (connects to MCP servers)
            await agent.initialize(stack)

            # Run interactive chat
            await agent.chat_loop()

    except Exception as e:
        LOGGER.error(f"Error: {e}")
        LOGGER.error("\nTroubleshooting:")
        LOGGER.error("1. Make sure the MCP servers are running")
        LOGGER.error("2. Check your API_KEY environment variable")
        LOGGER.error("3. Verify the MCP server URLs in config.json are correct")
        LOGGER.error("4. Edit config.json mcp_servers section to specify which servers to connect to")


if __name__ == "__main__":
    asyncio.run(main())
