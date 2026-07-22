# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the `manifest.py` module."""

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration


def test_mcp_server_registration_stores_expected_fields():
    """Verify that `MCPServerRegistration` stores all provided field values."""
    registration = MCPServerRegistration(
        name="template",
        module_path="example.template.server",
        package="example",
        description="Example server",
    )

    assert registration.name == "template"
    assert registration.module_path == "example.template.server"
    assert registration.package == "example"
    assert registration.description == "Example server"


def test_mcp_server_registration_description_defaults_to_none():
    """Verify that `description` defaults to `None` when omitted."""
    registration = MCPServerRegistration(
        name="template",
        module_path="example.template.server",
        package="example",
    )

    assert registration.description is None


def test_extension_manifest_stores_expected_fields():
    """Verify that `ExtensionManifest` stores its package metadata and registrations."""
    registration = MCPServerRegistration(
        name="template",
        module_path="example.template.server",
        package="example",
    )

    manifest = ExtensionManifest(
        display_name="Example Extension",
        version="1.2.3",
        provider_package="example",
        mcp_servers=(registration,),
    )

    assert manifest.display_name == "Example Extension"
    assert manifest.version == "1.2.3"
    assert manifest.provider_package == "example"
    assert manifest.mcp_servers == (registration,)


def test_extension_manifest_supports_multiple_servers():
    """Verify that one manifest can hold multiple MCP server registrations."""
    manifest = ExtensionManifest(
        display_name="Example Extension",
        version="1.2.3",
        provider_package="example",
        mcp_servers=(
            MCPServerRegistration("alpha", "example.alpha.server", "example"),
            MCPServerRegistration("beta", "example.beta.server", "example"),
        ),
    )

    assert [server.name for server in manifest.mcp_servers] == ["alpha", "beta"]
