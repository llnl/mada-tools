# Adding New MCP Servers to the MADA Tools Repository

To add a new MCP server directly to the MADA Tools Repository, you’ll need to create a server class that inherits from the [`BaseMCPServer`](../shared/base_server.md#shared.base_server.BaseMCPServer) class, and then register the server so it can be launched and discovered by the rest of the MADA MCP system. This page details the process step by step.

## Understanding the Base MCP Server Class

Every MCP server in the MADA Tools repository must inherit from the `BaseMCPServer` class, which is located in the `mada_tools/shared/base_server.py` file.

The `BaseMCPServer` class provides common functionality for all MCP servers, including:

- Parsing arguments from a config file (host, port, config file, transport)
- Loading and expanding configuration files and environment variables
- Initializing the FastMCP server backend
- Handling different transport methods (stdio, HTTP)
- Providing a standard entrypoint for launching the server

For new servers, we also strongly recommend putting the underlying tool logic in one or more helper classes and then exposing that logic through MCP tools that call `BaseMCPServer.run_tool()`. This keeps the business logic separate from MCP-specific registration details, makes unit testing easier, and allows the same implementation to support both MCP and Programmatic Tool Calling (PTC). For more information on PTC, see the [Anthropic Programmatic Tool Calling documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling).

By inheriting from this class, you ensure your server is compatible with the MADA MCP launch and orchestration infrastructure.

## Creating a `server.py` File

To implement a new MCP server, first create a new directory in the appropriate location in the repository for the server (see [MADA Tools Codebase Architecture](../architecture.md) for more information on repository structure), and add a `server.py` file inside it. This file will define your server class and specify which tools (APIs) your server provides.

**Example Structure:**

```
mada_tools/
├── scheduler/
│   ├── flux/
│   │   └── server.py
...
```

Below is a basic template for what's required when creating your own server:

```python
from mada_tools import BaseMCPServer


class MyServerHelper:
    def my_cool_tool(self, value: str) -> tuple[bool, str]:
        if not value:
            return False, "value must not be empty"
        return True, f"processed {value}"

class MyNewMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__(
            server_name="my_new_server",
            description="MCP Server for My New Functionality"
        )
        self.helper = MyServerHelper()

    def _register_tools(self):
        @self.mcp.tool()
        def my_cool_tool(value: str) -> str:
            return self.run_tool(self.helper.my_cool_tool, value)

if __name__ == "__main__":
    my_server = MyNewMCPServer()
    my_server.run_with_args(server_key="my_new_server")
```

**Key points:**

- Inherit from `BaseMCPServer`.
- Implement the `_register_tools` method to register all tools (APIs) your server provides.
- Prefer helper classes for business logic, and have your MCP tools call that logic with `self.run_tool(...)`.
- Return structured success and payload information from helper methods so the same logic can be used by MCP and PTC callers.
- In the `__main__` block, call `run_with_args(server_key=...)` with your server’s key name (used in config files).

## Recommended Pattern for MCP and PTC Compatibility

When defining tools, avoid putting all of the implementation directly inside the function decorated with `@self.mcp.tool()`. Instead:

1. Put the actual tool logic in a helper class or other plain Python callable.
2. Have the MCP tool function call that implementation through `self.run_tool(...)`.
3. Reuse the helper directly when you need the same capability outside an MCP server context.

This pattern is recommended because it:

- Keeps MCP registration code thin and easy to read
- Centralizes validation and error handling
- Makes unit testing simpler because helpers can be tested directly
- Makes it easier to support Programmatic Tool Calling (PTC) in addition to MCP

In practice, MCP and PTC often need access to the same tool behavior, but they do not share the same transport and registration layer. Keeping tool logic in helpers avoids coupling your implementation to MCP-specific decorators and server lifecycle details.

!!! note

    Keep in mind that type hints and thorough docstrings help the LLM perform much better. Make sure your tools are well documented for the best performance.

## Registering a New MCP Server

After creating your server class, you need to register it so it can be launched by the development scripts and included in configuration files.

1. Add a convenient CLI entrypoint to the `pyproject.toml` file in the `[project.scripts]` section. This should follow the following format:

    ```toml
    [project.scripts]
    mada-mcp-<server key> = "mada_tools.path.to.server:main"
    ```

2. Register the server in the built-in extension manifest at `src/mada_tools/extensions/builtins.py` by adding an `MCPServerRegistration` entry to `get_extension_manifest()`. This keeps built-in server discovery in one place.

    Example:

    ```python
    MCPServerRegistration(
        name="my_new_server",
        module_path="mada_tools.path.to.server",
        package="mada_tools",
    )
    ```

3. Add the server to the `configs/development.json` file. Below is a template entry; you may not need the `env_vars` entry:

    ```json
    {
        "servers": {
            "my_new_server": {
                "description": "MCP Server for My New Functionality",
                "host": "localhost",
                "port": 9005,
                "env_vars": {
                    "MY_SERVER_SETTING": "some_value"
                }
            }
        }
    }
    ```

4. Add a command to spin up your server in the `scripts/start_all_servers.sh` file:

    ```bash
    echo "Starting My New Server server..."
    mada-mcp-<server key> --config $CONFIG_FILE > $LOG_DIR/my_new_server.log 2>&1 &
    MY_NEW_SERVER_PID=$!
    ```

    You'll also want to add your stored server PID to the `echo` command that writes the PIDs to the `$LOG_DIR/server_pids.txt` file and to the `kill` command at the end of the script.

## Documenting Your Server

Add an entry for your server to the table in the [Available Servers](../../user_guide/supported_servers/index.md#available-servers) section in the documentation. Then, take that same entry and add it to the appropriate table in your server's category `index.md` page.

For example, the `Flux` MCP Server has an entry in the [Available Servers](../../user_guide/supported_servers/index.md#available-servers) table *and* the more-specific [Available Scheduler Servers](../../user_guide/supported_servers/scheduler/index.md#available-scheduler-servers) table.

Once that's done, create a page in the appropriate category to describe your server. The page should follow the following format:

```md
# <Server Key> MCP Server

<General overview of what the server accomplishes>

## Requirements

<any requirements that the server has>

## Server Configuration

<template configuration for this server>

## Available MCP Tools

<a table of MCP tools that this server has available>

## Key Features

<a bulleted list of key features for this server>
```
