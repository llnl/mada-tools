# Professor MCP Server

The Professor MCP Server provides an interface for launching Professor visualization tools and performing data analysis tasks, including AI-powered image analysis. It exposes MCP tools for starting the Professor GUI with a given configuration and for leveraging a large language model (LLM) to analyze and describe images based on user prompts.

## Requirements

This server requires:

- The Professor visualization suite be installed and accessible on the host system
- For LLM-based image analysis:
    - Access to the OpenAI-compatible API endpoint
    - Valid API key for authentication
- Environment variables set for (these can be given in the configuration file or set at the CLI prior to launching the server):
    - `API_KEY`: Your API key for the LLM
    - `API_BASE_URL`: (Optional) URL for the LLM API endpoint (default: `https://livai-api.llnl.gov`)
    - `MODEL`: (Optional) LLM model name (default: `gpt-4o`)
    - `PROF_VIS_PATH`: (Optional) Path to the Professor visualization executable (default `/usr/workspace/prof/bin/prof-vis`)

## Server Configuration

To use the Professor server, copy and paste the below configuration into your configuration file. You'll need to fill in the missing settings.

=== "streamable-http transport"

    ```json
    "professor": {
        "host": ,
        "port": ,
        "transport": "streamable-http",
        "env_vars": {
            "API_KEY": "${API_KEY}",
            "MODEL": "${MODEL:-gpt-4o}",
            "PROF_VIS_PATH": "${PROF_VIS_PATH:-/usr/workspace/prof/bin/prof-vis}",
            "API_BASE_URL": "${API_BASE_URL:-https://livai-api.llnl.gov}"
        }
    }
    ```

=== "stdio transport"

    ```json
    "professor": {
        "transport": "stdio",
        "env_vars": {
            "API_KEY": "${API_KEY}",
            "MODEL": "${MODEL:-gpt-4o}",
            "PROF_VIS_PATH": "${PROF_VIS_PATH:-/usr/workspace/prof/bin/prof-vis}",
            "API_BASE_URL": "${API_BASE_URL:-https://livai-api.llnl.gov}"
        }
    }
    ```

## Available MCP Tools

| Tool Name                 | Description                                                                       |
| ------------------------- | --------------------------------------------------------------------------------- |
| `launch_professor_gui`    | Launch the Professor GUI with a specified YAML configuration file.                |
| `analyze_image_with_llm`  | Use an LLM to analyze and describe an image according to a user-supplied prompt.  |

## Key Features

- **Visualization Launch:** Start the Professor GUI with a specified YAML configuration for interactive analysis and visualization.
- **AI-Powered Image Analysis:** Use a large language model to analyze images and generate descriptions or answers to user questions.
- **Configurable Integration:** Easily configure the server for your environment using environment variables.
- **Seamless Automation:** Integrate Professor visualization and AI analysis into automated workflows.
