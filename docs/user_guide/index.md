# The MADA Tools User Guide

## What is the MADA Tools Project?

<!-- TODO: Need to change this link when open source docs are live. -->

The MADA Tools project provides helpful AI tooling to be used with [MADA](https://software.llnl.gov/mada).

One key piece of tooling provided int his library are MCP (Model Context Protocol) servers. MADA MCP Servers are specialized backend services designed to support engineering and scientific workflows. Each server exposes a set of computational tools and APIs, allowing users and applications to perform tasks such as simulation, geometry generation, job scheduling, and surrogate modeling.

MADA MCP Servers are modular—each server focuses on a specific domain or functionality. For example, there are servers dedicated to running simulations, managing job schedulers (Flux, Slurm), generating geometry, and building surrogate models (Professor). This modularity makes it easy to scale, maintain, and extend the platform to meet diverse computational requirements.

## How do MADA MCP Servers Work?

Each MCP server runs as an independent process and communicates using a standardized API. [Servers are started](./server_management.md#starting-servers) with a configuration file that specifies details such as host, port, transport protocol, and environment variables.

Once running, MCP servers listen for requests from client applications or other services. Clients can connect to one or more MCP servers to access their computational tools. Requests are processed by the server, which executes the corresponding tool or workflow and returns results to the client.

MADA applications—such as the [simple agent app](./usage.md#single-agent-example-app) or the [MADA library](./usage.md#the-mada-library)—interact with MCP servers by sending natural language queries or structured API calls. These applications can leverage multiple servers simultaneously, routing requests to the appropriate server based on the required functionality.

This architecture enables flexible, distributed, and scalable computational workflows, making it easy to integrate new tools or servers as the needs of your project evolve.
