# Configuration

!!! note

    The configuration file used for starting MCP servers is different from the configuration file used by the [simple agent application](./usage.md#single-agent-example-app).

Server configurations are stored in the `configs/` directory. The main development configuration housing all available MCP servers is `configs/development.json`.

Configuration files specify server hostnames, ports, transport methods, and environment variables.

Example server startup config (`configs/development.json`):

```json
--8<-- "configs/development.json"
```

## Environment Variable Expansion

Configuration files support environment variable expansion for secure handling of sensitive values:

- `${VAR_NAME}` — Expands to the value of the environment variable
- `${VAR_NAME:-default}` — Uses the default value if the variable is not set

Set environment variables before starting servers that require them.

!!! example

    ```json
    {
    "servers": {
        "professor": {
        "env_vars": {
            "API_KEY": "${API_KEY}",
            "API_BASE_URL": "${API_BASE_URL:-https://api.openai.com/v1/responses}"
        }
        }
    }
    }
    ```

    Set required environment variables before starting this server:

    ```bash
    export API_KEY="sk-xxxx"
    ```

## Transport Methods

MCP servers support different transport methods:

| Transport         | Description                                                                                                           | Host/Port Required?   |
| ----------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------- |
| streamable-http   | Network-based HTTP transport (default). Good for distributed systems and production. Supports streaming responses.    | Yes                   |
| stdio             | Standard IO (stdin/stdout) transport. Good for local development and direct process communication.                    | No                    |

The `streamable-http` transport method requires both the `host` and `port` configuration settings. These settings will define where the server should be spun up.

!!! example

    ```json
    {
        "servers": {
            "flux": {
                "transport": "streamable-http",
                "host": "localhost",
                "port": 8001,
                "env_vars": {
                    "FLUX_HANDLE": "default"
                }
            }
        }
    }
    ```
