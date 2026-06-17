# Creating WEAVE Study Construction Servers

If you need an MCP server for constructing Jinja-templated WEAVE studies for your project, you should generally build it on top of [`WEAVEStudyConstructionServer`](../workflow/weave/study_construction/server.md#workflow.weave.study_construction.server.WEAVEStudyConstructionServer) rather than directly on [`BaseMCPServer`](../shared/base_server.md#shared.base_server.BaseMCPServer). Here, "WEAVE studies" refer to any study supported by [WEAVE Workflow Orchestration Tools](https://llnl-weave.readthedocs.io/en/latest/tools.html#workflow-orchestration).

`WEAVEStudyConstructionServer` is a specialized base class for MCP servers that expose study-construction functionality through template-backed tools. It is designed for servers that:

- Construct studies from Jinja-templated YAML files
- Validate or normalize user-provided template overrides before rendering
- Write rendered study YAML files to disk

In most cases, concrete implementations of `WEAVEStudyConstructionServer` should be created as [plugin MCP servers](./plugin_servers.md), since they are often tightly coupled to project-specific templates, helper scripts, filesystem conventions, and preprocessing logic.

## When to Use `WEAVEStudyConstructionServer`

Use `WEAVEStudyConstructionServer` when your server needs to do one or more of the following:

- Expose one or more study-construction tools backed by Jinja YAML templates
- Allow an LLM or user to supply template overrides dynamically
- Bundle project-specific preprocessing or validation logic for workflow inputs
- Provide a standard set of study-construction tools for WEAVE-based workflows

If your server does not construct WEAVE studies, or if it simply exposes unrelated computational tools, you should likely inherit directly from [`BaseMCPServer`](../shared/base_server.md#shared.base_server.BaseMCPServer) instead.

## What `WEAVEStudyConstructionServer` Provides

`WEAVEStudyConstructionServer` builds on top of `BaseMCPServer` and adds study-construction helpers and tools.

### Study construction support

A `WEAVEStudyConstructionServer` instance automatically creates a `WEAVEStudyConstructor`, which is used to:

- load workflow templates
- inspect template metadata
- build template rendering contexts
- write rendered YAML files to disk

### Path utilities

`WEAVEStudyConstructionServer` also registers a simple path utility tool `abspath`. This can be helpful when an agent needs to normalize or verify filesystem paths before constructing a study and while constructing the response to the user.

## Recommended Development Pattern

In most cases, you should treat `WEAVEStudyConstructionServer` as a framework for building concrete, project-specific plugin servers.

This is the preferred pattern because WEAVE-backed servers usually depend on:

| Concern | Why plugins are a good fit |
|---|---|
| Workflow templates | Templates are usually project-owned and evolve independently |
| Preprocessing logic | Input validation and defaults are often specific to one project |
| External assets | Helper scripts, parameter generators, and support files are easier to package together |
| Versioning | Plugins allow template behavior to be pinned to project releases |
| Maintenance | Project teams can update workflow behavior without modifying the core MADA-tools repository |

As a result, concrete study-construction servers should usually be implemented as plugins unless their templates and behavior are broadly reusable across MADA.

## Implementing a WEAVE Study Construction Server

To create a WEAVE-based study-construction server, define a class that inherits from `WEAVEStudyConstructionServer` and implement the `register_study_construction_tools()` method.

At construction time, you must provide:

- a server name
- a server description
- a path to the directory containing your Jinja-templated study YAML files

## Understanding Jinja Templated Studies

`WEAVEStudyConstructionServer` uses Jinja-templated YAML files to define studies. Jinja lets you parameterize a template so users can provide values at construction time instead of hardcoding everything in the file.

Template authors should use Jinja to expose only the values that need to vary, while keeping sensible defaults in the template where appropriate.

For full Jinja syntax and templating behavior, see the [Jinja documentation](https://jinja.palletsprojects.com/).

### How Jinja Template Variables Work

Study templates registered through `WEAVEStudyConstructionServer` are Jinja-templated YAML files. Any value written with Jinja syntax, such as `{{ variable_name }}`, is treated as a template field that can be filled by user-provided overrides during study construction.

If a template variable includes a Jinja `default(...)` expression, the tool can still render successfully even when that override is not provided. In that case, the default value from the template is used.

For example:
```yaml
env:
  variables:
    STORE: {{ store | default("store.sql") }}
    BUILD_DATAFILE_A: {{ build_datafile_a | default("datafile_A.dat") }}
    BUILD_DATAFILE_B: {{ build_datafile_b }}
```
Here, `store` and `build_datafile_a` are optional overrides. If they are not provided, the rendered study will use `"store.sql"` and `"datafile_A.dat"`. The `build_datafile_b` variable is required and *must* be provided.

This means an agent using the tool should interpret these Jinja expressions as configurable inputs to the study template:

- If the user provides a value, the agent can pass it as an override
- If no value is provided, and the template supplies a default, the agent may omit that override
- If no value is provided and no default exists, the template author should ensure preprocessing or validation handles the missing value appropriately

In practice, this allows templates to expose only the values that need to vary while keeping sensible defaults in the YAML itself.

### Important, Template Documentation with `mcp_doc`

Template-backed tools derive their user-facing tool documentation directly from the template itself. This is done by placing an `mcp_doc` YAML block inside a Jinja comment near the top of the template.

Example:
```jinja
{#-
mcp_doc: |
  Construct a study for My Cool Workflow.

  Use this tool when you want to generate a workflow YAML for the
  standard project pipeline. You may override selected template
  parameters if needed.
-#}
```
This documentation is extracted and used as the MCP tool docstring, which helps the LLM understand when and how to call the tool. If `mcp_doc` is missing or unclear, tool selection and tool usage may be worse.

## Registering Study Construction Tools

Concrete subclasses register their study-construction tools by calling `register_jinja_study_tool()` from inside `register_study_construction_tools()`.

This helper creates an MCP tool that:

1. collects user-provided overrides
2. optionally preprocesses them
3. builds a rendering context from the template
4. writes the rendered study YAML files to disk

### Single-template registration

Use this pattern when you want explicit control over the tool name, template, and preprocess hook.
```python
self.register_jinja_study_tool(
    tool_name="construct_my_cool_study",
    template_name="my_cool_study.yaml",
    preprocess=self._prep_my_cool_study,
)
```
### Directory-based registration

If you have many templates, `register_jinja_study_tool()` can also register one tool per `*.yaml` file in a directory.

Tool names are derived automatically using the template stem:

| Template file | Generated tool name |
|---|---|
| `my_cool_study.yaml` | `construct_my_cool_study` |
| `baseline.yaml` | `construct_baseline_study` |

If a method named `_prep_<template_stem>` exists on the server, it will be used automatically as the [preprocess hook](#preprocess-hooks) for that template.

For example, a template named `baseline.yaml` will look for:
```python
def _prep_baseline(self, overrides):
    ...
```
You can then register all templates in a directory like this:
```python
self.register_jinja_study_tool(templates_dir=".")
```

## Preprocess Hooks

!!! warning "Important"

    If you use [Single-template registration](#single-template-registration), then you can pass in `preprocess` to be any method/function you want. If you instead use [Directory-based registration](#directory-based-registration) then `register_jinja_study_tool()` will have to derive the preprocess methods and will look for methods with names of the form `_prep_<template_stem>`.

A preprocess hook gives you a place to validate, normalize, or enrich user-provided override values before the template is rendered.

Typical uses include:

- validating input paths
- converting relative paths to absolute paths
- filling in default project locations
- coercing values into strings or other expected formats
- rejecting unsupported combinations of inputs

### Important return-value requirement

A preprocess hook must return a mapping of override values.

For example, this is correct:
```python
def _prep_my_cool_study(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
    overrides["my_key"] = "normalized_value"
    return overrides
```
This is incorrect:
```python
def _prep_my_cool_study(self, overrides: Dict[str, Any]) -> Path:
    path = Path("some/path")
    overrides["my_key"] = str(path)
    return path
```
Returning anything other than a dictionary-like mapping will break context construction.

## Automatically Available Tools

In addition to your study-construction tools, `WEAVEStudyConstructionServer` automatically registers the following general-purpose tool:

| Tool | Purpose |
|---|---|
| `abspath` | Convert a path to an absolute path on the server |

This means most subclasses only need to focus on study-construction logic and template-specific validation.

## Relationship to Maestro Command Execution

`WEAVEStudyConstructionServer` only handles study construction. It does not run or manage workflows.

If you need workflow execution, monitoring, cancellation, or updates for Maestro studies, see the user guide page for the [Maestro Command Execution MCP Server](../../user_guide/supported_servers/workflow/maestro.md).

## Full Example

This example creates a WEAVE study construction server for a Hello World workflow.

First, start with the following Jinja-templated study:

```yaml title="src/hello_world_maestro/study_templates/hello_world.yaml"
{#-
mcp_doc: |
  Construct a Hello World study.

  Use this tool when you want to generate a workflow YAML for the
  hello world functionality. You may override selected template
  parameters if needed.
-#}  # (1)

description:
    name: hello_world
    description: A hello world example workflow

env:
    variables:
        USER: {{ user | default(default_user)}}  # (2)

study:
- name: say_hello
  description: Say hello to the user
  run:
    cmd: echo "Hello $(USER)!"  # (3)
- name: say_goodbye
  description: Say goodbye to the user
  run:
    cmd: echo "Goodbye $(USER)!"
    depends: [say_hello]
```

1. This section is *very* important as it will be converted into the description of the `construct_hello_world_study` tool (that will be created below) at run time. It is *not* required by [WEAVE Workflow Orchestration Tools](https://llnl-weave.readthedocs.io/en/latest/tools.html#workflow-orchestration) or MCP but without it, the model you use will not know how to utilize the `construct_hello_world_study` tool properly.

2. The `{{ }}` syntax is the Jinja syntax for a variable. If no `user` is provided to the template, the default will be `default_user`.

3. The `$( )` syntax is the Maestro/Merlin syntax for referencing a variable or parameter

Now let's create the `HelloWorldStudyConstructionServer` class:

```python title="src/hello_world_study_construction/server.py"
from pathlib import Path
from typing import Any, Dict

from mada_tools import ToolExecutionError, WEAVEStudyConstructionServer


class HelloWorldStudyConstructionServer(WEAVEStudyConstructionServer):
    """
    Example MCP server for constructing a hello-world workflow for WEAVE
    Workflow Orchestration Tooling.
    """

    def __init__(self):
        super().__init__(
            server_name="HelloWorldStudyConstructionServer",
            description="MCP server for constructing and managing Hello World WEAVE workflows",
            study_templates_dir=Path(__file__).parent / "study_templates",  # this is where the hello_world.yaml lives
        )

    def _prep_hello_world(self, overrides: Dict[str, Any] | None) -> Dict[str, Any]:
        """
        Validate and normalize template overrides before rendering.
        """
        overrides = overrides or {}

        user = overrides.get("user")

        # Don't do anything if user isn't given, there's a default in the yaml file
        if user is None:
            return overrides

        user = str(user).strip()
        if not user:
            raise ToolExecutionError("The 'user' override must be a non-empty string.")

        overrides["user"] = user
        return overrides

    def register_study_construction_tools(self) -> None:
        """
        Register template-backed study construction tools.
        """
        self.register_jinja_study_tool(
            tool_name="construct_hello_world",
            template_name="hello_world.yaml",
            preprocess=self._prep_hello_world,
        )


def main():
    """Main entry point for the Hello-World Study Construction MCP server."""
    server = HelloWorldStudyConstructionServer()
    server.run_with_args("hello_world_study_construction")


if __name__ == "__main__":
    main()
```

We'll add a `pyproject.toml` file:

```toml title="pyproject.toml"
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "hello_world_study_construction"
description = "Hello World Maestro MCP server"
version = "0.1.0"
requires-python = ">=3.10"
readme = "README.md"
dependencies = ["mada_tools", "maestrowf"]

[project.entry-points."mada_tools.servers"]
hello_world_study_construction = "hello_world_study_construction.server"

[tool.setuptools.packages.find]
where = ["src"]
```

We've included "maestrowf" as a dependency so that we can run this study with WEAVE's [Maestro Workflow Orchestration Tool](https://maestrowf.readthedocs.io/en/latest/).

All that's left is to install this project to your virtual environment so that the server can be registered with `mada_tools`:

```bash
pip install -e .
```

You can ensure the server is found using:

```bash
mada-tools available-servers
```

This will show `hello_world_study_construction` in the list of available MCP servers.

Here is a configuration file you can use to start the `HelloWorldStudyConstructionServer` and the `MaestroCommandExecutionServer`:

```json title="configs/hello_world_study_construction.json"
{
    "servers": {
        "hello_world_study_construction": {
            "host": "localhost",
            "port": 8500,
            "transport": "streamable-http",
            "env_vars": {}
        },
        "maestro_command_executor": {  // (1)
            "host": "localhost",
            "port": 8501,
            "transport": "streamable-http",
            "env_vars": {}
        }
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    }
}
```

1. This MCP server is necessary in order to run the study. Without this, all you can do is build the YAML file and write it to the file system.

The server can be started with:

```bash
mada-tools start-servers configs/hello_world_study_construction.json
```

Once you connect an agent to the MCP server (see [Using MADA MCP Servers](../../user_guide/usage.md)), try out the following prompts:

1. Creating the study:

    ```bash
    Create a hello world study for Brian
    ```

    The agent should utilize the `HelloWorldStudyConstructionServer` to write the `hello_world.yaml` file to the file system.

2. Execute the study using Maestro:

    ```bash
    Execute the study with Maestro
    ```

    The agent should utilize the `MaestroCommandExecutionServer` to launch the study.

3. Check the status of the study with Maestro:

    ```bash
    Check the status of the study
    ```

    The agent should utilize the `MaestroCommandExecutionServer` to check on the study.

## Multi-Template Example

We'll start by putting the following template files in a directory called `src/multi_template_study_construction/study_templates/`:

=== "study_templates/sim_workflow.yaml"

    ```yaml
    {#-
    mcp_doc: |
    Construct an example simulation workflow study.

    Use this tool when you want to generate a runnable workflow YAML for
    running a full simulation. You may override selected template parameters
    if needed.
    -#}

    description:
    name: sim_workflow
    description: A typical simulation workflow

    env:
    variables:
        USER: {{ user | default("default_user") }}
        MODE: {{ mode | default("standard") }}
        INPUT_DIR: {{ input_dir | default("inputs") }}
        OUTPUT_DIR: {{ output_dir | default("outputs") }}

    study:
    - name: prepare
        description: Prepare inputs
        run:
        cmd: mkdir -p "$(OUTPUT_DIR)" && echo "Preparing inputs for $(USER) in $(MODE) mode"

    - name: execute
        description: Execute the main workflow
        run:
        cmd: echo "Running main workflow for $(USER) in $(MODE) mode"
        depends: [prepare]

    - name: finalize
        description: Finalize results
        run:
        cmd: echo "Finalizing results in $(OUTPUT_DIR)"
        depends: [execute]
    ```

=== "study_templates/messenger.yaml"

    ```yaml
    {#-
    mcp_doc: |
    Construct a study that just displays a message.

    Use this tool when you want a lightweight workflow that
    just displays a message.
    -#}

    description:
    name: messenger
    description: A workflow that displays a message

    env:
    variables:
        USER: {{ user | default("default_user") }}
        MESSAGE: {{ message | default("Hello from the helper workflow") }}

    study:
    - name: echo_message
        description: Echo a message
        run:
        cmd: echo "$(MESSAGE) for $(USER)"
    ```

Now let's create the `MultiTemplateStudyConstructionServer` class:

```python title="src/multi_template_study_construction/server.py"
from pathlib import Path
from typing import Any, Dict

from mada_tools import ToolExecutionError, WEAVEStudyConstructionServer


class MultiTemplateStudyConstructionServer(WEAVEStudyConstructionServer):
    """
    Example WEAVE Study Construction MCP Server showcasing multiple studies.
    """

    def __init__(self):
        super().__init__(
            server_name="MultiTemplateStudyConstructionServer",
            description="MCP server for constructing and managing multiple WEAVE workflows",
            study_templates_dir=Path(__file__).parent / "study_templates",  # (1)
        )

    def _prep_messenger(self, overrides: Dict[str, Any] | None) -> Dict[str, Any]:
        """
        Validate and normalize template overrides for the messenger.yaml study before rendering.
        """
        overrides = overrides or {}

        user = overrides.get("user")

        # Don't do anything if user isn't given, there's a default in the yaml file
        if user is None:
            return overrides

        user = str(user).strip()
        if not user:
            raise ToolExecutionError("The 'user' override must be a non-empty string.")

        overrides["user"] = user
        return overrides

    def register_study_construction_tools(self) -> None:
        """
        Register template-backed Maestro study construction tools.
        """
        self.register_jinja_study_tool(  # (2)
            template_dir=self.study_constructor.study_templates_dir,
        )


def main():
    """Main entry point for the Multi-Template Maestro MCP server."""
    server = MultiTemplateStudyConstructionServer()
    server.run_with_args("multi_template_study_construction")


if __name__ == "__main__":
    main()
```

1. This will be stored in `self.study_constructor.study_templates_dir`

2. There's no need to pass in tool names or preprocess methods here. As mentioned in [Directory-Based Registration](#directory-based-registration), these will be derived automatically. In this example the tool names will be `construct_sim_workflow_study` and `construct_messenger_study`. The `sim_workflow` study does not have a preprocess method here but the `messenger` study does (`_prep_messenger`), so only the `construct_messenger_study` tool will have a preprocess method attached to it.

We'll add a `pyproject.toml` file:

```toml title="pyproject.toml"
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "multi_template_study_construction"
description = "Multi-Template Maestro MCP server"
version = "0.1.0"
requires-python = ">=3.10"
readme = "README.md"
dependencies = ["mada_tools", "maestrowf"]

[project.entry-points."mada_tools.servers"]
multi_template_study_construction = "multi_template_study_construction.server"

[tool.setuptools.packages.find]
where = ["src"]
```

All that's left is to install this project to your virtual environment so that the server can be registered with `mada_tools`:

```bash
pip install -e .
```

You can ensure the server is found using:

```bash
mada-tools available-servers
```

This will show `multi_template_study_construction` in the list of available MCP servers.

Here is a configuration file you can use to start the server:

```json title="configs/multi_template_study_construction.json"
{
    "servers": {
        "multi_template_study_construction": {
            "host": "localhost",
            "port": 8500,
            "transport": "streamable-http",
            "env_vars": {}
        }
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    }
}
```

The server can be started with:

```bash
mada-tools start-servers configs/multi_template_maestro.json
```

Once you connect an agent to the MCP server (see [Using MADA MCP Servers](../../user_guide/usage.md)), try out the following prompts:

1. Create a messenger.yaml study:

    ```bash
    Create a WEAVE study that tells Jorge he needs to vibe code everything.
    ```

    The agent should utilize the `MultiTemplateStudyConstructionServer` to write the `messenger.yaml` file to the file system.

2. Create a sim_workflow.yaml study:

    ```bash
    Create a simulation workflow with the following settings: user="CJ", input_dir="custom_inputs"
    ```

    The agent should utilize the `MultiTemplateStudyConstructionServer` to write the `sim_workflow.yaml` file to the file system. In this file, the `mode` and `output_dir` should use their respective default values of `standard` and `outputs`.
