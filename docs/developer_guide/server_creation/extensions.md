# Registering MADA Extensions

MADA extensions provide a package-level registration mechanism for plugins.
This page covers registering MCP server plugins through an extension manifest.

## Why Use an Extension Manifest?

Using a manifest factory gives each package one place to describe what it adds
to MADA. For MCP server plugins, that provides a few benefits:

- It keeps all registrations from one package in one place.
- It gives MADA a single discovery contract for built-ins and external packages.
- It keeps server registration separate from server process management.

## Entry Point Contract

Extensions register a factory under the `mada_tools.extensions` entry point
group. The factory must return an `ExtensionManifest` instance that describes
the plugin's MCP server registrations.

Example:

```toml
[project.entry-points."mada_tools.extensions"]
my_package = "my_package.mada_extension:get_extension_manifest"
```

## Creating an Extension Manifest

Create a Python module that returns an `ExtensionManifest` containing one or
more `MCPServerRegistration` entries.

```python
from mada_tools.extensions import ExtensionManifest, MCPServerRegistration


def get_extension_manifest() -> ExtensionManifest:
    return ExtensionManifest(
        display_name="My Package",
        version="0.1.0",
        provider_package="my_package",
        mcp_servers=(
            MCPServerRegistration(
                name="template",
                module_path="my_package.template.server",
                package="my_package",
            ),
        ),
    )
```

Each registered server module must still be importable and expose a callable
`main()` function.

## Manifest Fields

The main fields used for MCP server plugins are:

- `display_name`: Human-readable name shown in developer-facing contexts.
- `version`: Extension package version.
- `provider_package`: Python package providing the extension.
- `mcp_servers`: Tuple of `MCPServerRegistration` entries.

Each `MCPServerRegistration` should provide:

- `name`: The server name used by MADA configuration.
- `module_path`: Importable Python module path for the server.
- `package`: Provider package name shown in available-server listings.
- `description`: Optional descriptive text for the registration.

In most cases, `provider_package` should match the package you publish and
install with `pip`.

## Full Example

The following example shows a minimal external package that registers one MCP
server plugin through an extension manifest.

Example package layout:

```text
my_package/
|- pyproject.toml
`- src/
   `- my_package/
      |- __init__.py
      |- mada_extension.py
      `- template/
         |- __init__.py
         `- server.py
```

Example `pyproject.toml`:

```toml
[project]
name = "my_package"
version = "0.1.0"
dependencies = ["mada_tools"]

[project.entry-points."mada_tools.extensions"]
my_package = "my_package.mada_extension:get_extension_manifest"
```

Example `src/my_package/mada_extension.py`:

```python
from mada_tools.extensions import ExtensionManifest, MCPServerRegistration


def get_extension_manifest() -> ExtensionManifest:
    return ExtensionManifest(
        display_name="My Package",
        version="0.1.0",
        provider_package="my_package",
        mcp_servers=(
            MCPServerRegistration(
                name="template",
                module_path="my_package.template.server",
                package="my_package",
                description="Example MCP server provided by my_package.",
            ),
        ),
    )
```

Example `src/my_package/template/server.py`:

```python
from mada_tools import BaseMCPServer


class TemplateHelper:
    def custom_tool(self, text: str) -> tuple[bool, str]:
        if not text:
            return False, "text must not be empty"
        return True, text.upper()


class TemplateServer(BaseMCPServer):
    def __init__(self):
        super().__init__("Template Server", "Example extension-provided MCP server.")
        self.helper = TemplateHelper()

    def _register_tools(self):
        @self.mcp.tool()
        def custom_mcp_tool(text: str) -> str:
            return self.run_tool(self.helper.custom_tool, text)


def main():
    server = TemplateServer()
    server.run_with_args("template")
```

After installing the package, `mada-tools available-servers` should list the
`template` server under the `my_package` provider package.

## Server Implementation Guidance

The extension manifest handles registration only. Each registered MCP server
should still follow the normal MADA server pattern:

- Keep the server module importable.
- Expose a callable `main()` entry point.
- Keep the MCP-facing server class thin and place tool behavior in helper
  classes or other reusable Python code.

## Validating the Registration

After installing your package, run
[`mada-tools available-servers`](../../user_guide/cli.md#available-servers-mada-tools-available-servers)
to confirm that your extension's servers are being discovered.

For AI-driven end-to-end tests, extension packages can also reuse the shared
test helpers in `mada_tools.testing`. The supported reusable agent is
`mada_tools.agents.MultiServerAgent`, which is also the implementation behind
the repository's interactive example app.

Example test import:

```python
from mada_tools.testing import AgentTestRunner
```

## Legacy Registration

MADA still supports legacy registration through
`[project.entry-points."mada_tools.servers"]`, but new plugin packages should
register through `mada_tools.extensions`.

If a package uses both registration styles during a migration, MADA resolves
them per server name:

- manifest-registered server names win over legacy registrations with the same name
- legacy server names that do not collide remain discoverable

This allows packages to migrate incrementally from `mada_tools.servers` to
`mada_tools.extensions` instead of moving every server in one change.

## Plugin Documentation

Plugin repositories should build plugin-local combined docs when they need to publish documentation alongside the core MADA Tools guides. This keeps each plugin responsible for its own docs while still showing the matching installed MADA Tools reference in the same MkDocs site.

The combined docs workflow exports the core docs from the installed `mada-tools` package, then stages plugin docs into a generated docs tree. Install the docs dependencies in the environment that builds or serves the site:

```bash
pip install "mada_tools[docs]"
```

Keep plugin pages namespaced so they do not collide with core docs, such as `example_plugin_index.md`, `example_plugin_user_guide`, or `example_plugin_developer_guide`. The staging tool does not require those exact names, but it refuses to overwrite paths exported from the core docs.

Create a config file such as `docs/plugin_docs.yaml`:

```yaml
project_root: ..
mkdocs_config: mkdocs.yaml
generated_root: .generated_docs
plugin_docs_dir: docs
```

The `mkdocs_config`, `generated_root`, and `plugin_docs_dir` settings should all be relative paths to the `project_root`.

If a field is omitted, these defaults are used:

| Field | Default | Path base |
| ---- | ---- | ---- |
| `project_root` | `.` | directory containing `plugin_docs.yaml` |
| `mkdocs_config` | `mkdocs.yaml` | `project_root` |
| `generated_root` | `.generated_docs` | `project_root` |
| `plugin_docs_dir` | `docs` | `project_root` |

The plugin docs directory is copied into the staged MkDocs `docs/` directory. For example, a plugin repository can use this source layout:

```text
docs/
  plugin_docs.yaml              # config file; read by the CLI, not copied into the staged site
  example_plugin_index.md
  example_plugin_user_guide/
    index.md
  example_plugin_developer_guide/
    index.md
```

During staging, the content under `plugin_docs_dir` is copied into `.generated_docs/docs`. The plugin docs config file itself is skipped, and Python cache artifacts like `__pycache__` and `.pyc` files are excluded.

Choose the command for the task:

```bash
mada-tools plugin-docs prepare --config docs/plugin_docs.yaml
mada-tools plugin-docs build --config docs/plugin_docs.yaml
mada-tools plugin-docs serve --config docs/plugin_docs.yaml
mada-tools plugin-docs clean --config docs/plugin_docs.yaml
```

Use `prepare` when you want to inspect the staged MkDocs source tree without building it. The `build` and `serve` commands call `prepare` automatically before running MkDocs. Use `clean` to remove the generated docs tree.

The `build` and `serve` commands pass trailing arguments to MkDocs:

```bash
mada-tools plugin-docs build --config docs/plugin_docs.yaml -- --strict
mada-tools plugin-docs serve --config docs/plugin_docs.yaml -- --dev-addr 127.0.0.1:9000
```

For plugin API reference pages, call the shared generator from the plugin's MkDocs `gen-files` script instead of copying MADA Tools' full `docs/gen_ref_pages.py` implementation:

```python
from pathlib import Path

from mada_tools.docs import ApiReferenceMapping, generate_api_reference_pages

generate_api_reference_pages(
    [
        ApiReferenceMapping(
            package_name="example_plugin",
            api_reference_path=Path("example_plugin_developer_guide/api"),
            source_path=Path("src/example_plugin"),
        )
    ]
)
```
