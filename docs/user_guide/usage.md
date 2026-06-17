# Using MADA Tools

!!! warning "Important"

    Before using any of the MADA applications, make sure the MCP servers you wish to use are running. For detailed instructions, see [Starting Servers](./server_management.md#starting-servers).

MADA provides two apps for interacting with MCP servers:

- [Simple single-agent example application](#single-agent-example-app)
- [The MADA Library](#the-mada-library) for a multi-agent group chat configuration

If neither of these options are what you're looking for, you'll have to develop your own app for utilizing the MCP servers. The single-agent example should give you a good starting ground for this.

Below are more details on the MADA-provided applications.

## Single-Agent Example App

The Simple-Agent Application is located in the examples/ folder at the top of the repository. Inside this folder, you’ll find:

- `config.json`: Configuration for your model and MCP servers
- `simple_agent_loop.py`: The Python script containing the application logic

### Configuration

The `config.json` file specifies both model information and the MCP servers to connect to. It follows this format:

```json
{
    "model": {
        "model": "which model to use",
        "api_key": "${API_KEY}",
        "base_url": "${API_BASE_URL:-https://api.openai.com/v1/responses}"
    },
    "mcp_servers": {
        "name of the MCP server": {
            "transport": "either streamable-http or stdio",
            "url": "endpoint of the server",
            "description": "A brief description of this MCP server"
        }
    }
}
```

### How the Simple-Agent Application Works

The Simple-Agent Application (`simple_agent_loop.py`) connects to one or more MCP servers and allows you to interact with their tools using natural language queries. It leverages OpenAI’s function-calling interface to interpret your requests and execute workflows across multiple servers.

**Key Features**

- **Multi-Server Support:** Connects to any number of MCP servers as defined in your configuration.
- **Automatic Tool Discovery:** Discovers tools on each MCP server and makes them available for use.
- **Interactive Chat Loop:** Provides a command-line interface for entering queries and receiving results.
- **OpenAI Integration:** Uses an OpenAI-compatible model to interpret queries and determine which tools to call.

### Running the Application

1. Set Up Your Environment:

    Set the `API_KEY` environment variable to your OpenAI API key.
    Optionally, set `API_BASE_URL` if you need to override the default endpoint.

2. Prepare Your Configuration:

    Edit a `config.json` file to specify your model and the MCP servers you wish to connect to.

3. Start the Agent:

    Run the application from the command line:

    ```bash
    python examples/simple_agent_loop.py --config config.json
    ```

    The agent will connect to your specified MCP servers, discover their tools, and display a summary of available functionality.

4. Interact with the Agent:

    Type natural language queries at the prompt. The agent will process your request, call the appropriate tools on the MCP servers, and display the results.

5. Exit the Application:

    Type `quit`, `exit`, or `q` to leave the chat loop.

### Troubleshooting

If you encounter issues, check the following:

- Are the MCP servers running and reachable at the URLs specified in your configuration?
- Is your API key and base URL set correctly?
- Is your config.json properly formatted and does it include all required server definitions?

## The MADA Library

The MADA library is a more advanced project designed for complex, multi-agent workflows. Unlike the simple agent loop, the MADA library coordinates multiple user-provided agents along with an automatically created planning agent, all within a single group chat interface.

When you submit a request, your input is first routed to the planning agent. The planning agent then determines which agent or tool is best suited to handle your request and coordinates the workflow accordingly.

The MADA library is maintained in a separate repository. For setup instructions, usage details, and further documentation, please visit [here](https://github.com/llnl/mada).
