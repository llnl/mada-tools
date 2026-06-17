---
hide:
  - navigation
---

# MADA Tools

Use the Multi-Agent Design Assistant (MADA) Tools project, a Python-powered repository that provides a centralized library of AI tools, like MCP servers, skills files, and more.

[On GitHub :fontawesome-brands-github:](https://github.com/llnl/mada-tools)

## Why use MADA Tools?

MADA Tools provide a unified, modular platform for running and managing computational tools and workflows. By centralizing a diverse set of MCP servers—each dedicated to specialized tasks such as simulation, geometry generation, job scheduling, and surrogate modeling—this project enables seamless integration and orchestration of engineering and scientific processes.

With MADA Tools, you can:

- Access a wide range of computational services from a single interface
- Easily scale and extend your workflows by adding new servers
- Simplify automation and collaboration across teams and projects
- Leverage natural language and API-driven interactions for flexible workflow design

## Goals and Motivations

The main goals of the MADA Tools project are:

- **Modularity:** Enable the development and deployment of specialized MCP servers that can be plugged into larger workflows.
- **Scalability:** Support distributed and parallel computational tasks across multiple domains.
- **Interoperability:** Provide standardized APIs and protocols for communication between servers, clients, and agents.
- **Extensibility:** Make it easy to add new tools, algorithms, and server types as project needs evolve.

## Getting Started

1. Install MADA Tools

    Follow the instructions in the [Basic Installation](./user_guide/installation.md#basic-installation) section of the [Installation Guide](./user_guide/installation.md).

2. Start the MCP Servers

    From the top-level of the repository, execute:

    ```bash
    mada-tools start-servers configs/development.json
    ```

3. Run the Simple Agent Application

    Open a new terminal and move into the `examples/` directory:

    ```bash
    cd examples
    ```

    Run the simple-agent loop application:

    ```bash
    python simple_agent_loop.py --config config.json
    ```

    This configuration file utilizes the Flux MCP server. You can modify this to use any servers that MADA supports. See a table of these [here](./user_guide/supported_servers/index.md#available-servers).

The application is now running and you can interact with the agent to runs jobs Flux!
