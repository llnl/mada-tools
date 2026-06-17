# The MADA Tools Developer Guide

Welcome to the Developer Guide for the MADA Tools project! This comprehensive guide is designed to provide developers with a detailed understanding of the various modules, classes, and functions available within this project's API. It will also provide:

- A guide to the [architecture of the codebase](./architecture.md).
- A [Testing Guide](./testing.md)
- Instructions for [Creating MCP Servers](./server_creation/index.md), including:
    - [Adding Servers Directly to the MADA Tools Repository](./server_creation/adding_new_servers.md)
    - [Creating Plugin MCP Servers](./server_creation/plugin_servers.md)


## Installation for Developers

Follow the [Basic Installation](../user_guide/installation.md#basic-installation) instructions, but for the final step install all dependencies:

```bash
pip install -e .[all]
```

Once installed, set up `pre-commit`:

```bash
pre-commit install
```

Now the pre-commit hooks will run before each commit. You can automatically fix most linting and formatting issues by running the following commands from the top of the repository:

```bash
ruff check --fix
ruff format
```

We appreciate your contributions!
