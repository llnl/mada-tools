# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Integration tests for template-backed MCP tool flows.

These tests exercise `BaseMaestroServer` and `MaestroStudyConstructor` together
through registered MCP tool callables.
"""

from pathlib import Path

import pytest

from mada_tools.shared import ToolExecutionError


@pytest.fixture
def registered_tools_map(dummy_study_construction_server) -> dict:
    """
    Register all tools on the dummy server and return the tool registry.

    Args:
        dummy_study_construction_server (DummyWEAVEStudyConstructionServer):
            Concrete test server instance.

    Returns:
        dict:
            Mapping of tool names to registered callables.
    """
    dummy_study_construction_server._register_tools()
    return dummy_study_construction_server.mcp.tools


class TestTemplateToolFlows:
    """
    Integration tests for template-backed study construction tools.
    """

    def test_register_single_template_tool_and_render_yaml(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should register a single template-backed tool and execute the full
        context-build and YAML-write flow successfully.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        tool = registered_tools_map["construct_example_study"]

        result = tool(
            overrides={
                "study_name": "integration-study",
                "required_value": 123,
            },
            output_dir=tmp_path,
        )

        output_file = tmp_path / "example.yaml"

        assert "Wrote Maestro study YAML to" in result
        assert str(output_file) in result
        assert output_file.exists()

        contents = output_file.read_text(encoding="utf-8")
        assert "name: integration-study" in contents
        assert "value: 123" in contents
        assert "optional: fallback" in contents
        assert "prep_flag: yes" in contents

    def test_template_tool_applies_preprocess_before_rendering(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should apply the server preprocess hook before rendering the template.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        tool = registered_tools_map["construct_example_study"]

        tool(
            overrides={
                "study_name": "prep-test",
                "required_value": 9,
            },
            output_dir=tmp_path,
        )

        output_file = tmp_path / "example.yaml"
        contents = output_file.read_text(encoding="utf-8")

        assert "prep_flag: yes" in contents

    def test_template_tool_rejects_unknown_override_keys(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should surface unknown override-key validation failures as `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        tool = registered_tools_map["construct_example_study"]

        with pytest.raises(ToolExecutionError, match="unknown template variables"):
            tool(
                overrides={
                    "study_name": "bad-study",
                    "required_value": 1,
                    "not_a_real_key": "boom",
                },
                output_dir=tmp_path,
            )

    def test_template_tool_rejects_missing_required_keys(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should surface missing required template-variable failures as `ToolExecutionError`.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        tool = registered_tools_map["construct_example_study"]

        with pytest.raises(ToolExecutionError, match="missing required template variables"):
            tool(
                overrides={
                    "study_name": "missing-required-value",
                },
                output_dir=tmp_path,
            )

    def test_template_tool_docstring_is_generated_from_template_metadata(
        self,
        registered_tools_map: dict,
    ):
        """
        It should attach a generated docstring based on template metadata and inferred variables.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
        """
        tool = registered_tools_map["construct_example_study"]
        doc = tool.__doc__

        assert doc is not None
        assert "Construct the example study." in doc
        assert "This template is used for integration testing." in doc
        assert "Template-backed tool." in doc
        assert "Required template variables:" in doc
        assert "Supported override keys:" in doc
        assert "study_name" in doc
        assert "required_value" in doc
        assert "optional_value" in doc

    def test_register_directory_of_templates_creates_multiple_tools(
        self,
        dummy_study_construction_server,
    ):
        """
        It should register one tool per YAML template when directory registration is used.

        Args:
            dummy_study_construction_server:
                Concrete test server instance.
        """
        dummy_study_construction_server.mcp.tools.clear()

        dummy_study_construction_server.register_jinja_study_tool(templates_dir=".")

        assert "construct_example_study" in dummy_study_construction_server.mcp.tools
        assert "construct_secondary_study" in dummy_study_construction_server.mcp.tools

    def test_directory_registered_tool_can_render_yaml(
        self,
        dummy_study_construction_server,
        tmp_path: Path,
    ):
        """
        It should allow a directory-registered tool to execute the full render flow.

        Args:
            dummy_study_construction_server:
                Concrete test server instance.
            tmp_path (Path):
                Pytest temporary directory.
        """
        dummy_study_construction_server.mcp.tools.clear()
        dummy_study_construction_server.register_jinja_study_tool(templates_dir=".")

        tool = dummy_study_construction_server.mcp.tools["construct_secondary_study"]

        result = tool(
            overrides={"alpha_value": 42},
            output_dir=tmp_path,
        )

        output_file = tmp_path / "secondary_study.yaml"

        assert "Wrote Maestro study YAML to" in result
        assert output_file.exists()

        contents = output_file.read_text(encoding="utf-8")
        assert "alpha: 42" in contents
        assert "beta: 5" in contents

    def test_template_tool_ignores_none_override_values(
        self,
        registered_tools_map: dict,
        tmp_path: Path,
    ):
        """
        It should ignore None-valued overrides so template defaults remain in effect.

        Args:
            registered_tools_map (dict):
                Registered MCP tool callables keyed by tool name.
            tmp_path (Path):
                Pytest temporary directory.
        """
        tool = registered_tools_map["construct_example_study"]

        tool(
            overrides={
                "study_name": "none-test",
                "required_value": 10,
                "optional_value": None,
            },
            output_dir=tmp_path,
        )

        output_file = tmp_path / "example.yaml"
        contents = output_file.read_text(encoding="utf-8")

        assert "optional: fallback" in contents
