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

## Legacy Registration

MADA still supports legacy registration through
`[project.entry-points."mada_tools.servers"]`, but new plugin packages should
register through `mada_tools.extensions`.
