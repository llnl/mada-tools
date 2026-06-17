# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Shared fixtures for Maestro MCP server integration tests.
"""

import json
from pathlib import Path

import pytest

from mada_tools.workflow.weave import MaestroCommandExecutionServer, WEAVEStudyConstructionServer


class FakeMCP:
    """
    Minimal fake MCP registry used for integration tests.

    This fake captures registered tool callables by name so tests can invoke
    them directly without starting a real MCP server.
    """

    def __init__(self):
        """Initialize the fake tool registry."""
        self.tools = {}

    def tool(self):
        """
        Return a decorator that registers a tool function by its __name__.

        Returns:
            callable:
                A decorator that stores the function in the registry.
        """

        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class DummyMaestroCommandExecutionServer(MaestroCommandExecutionServer):
    def __init__(self):
        super().__init__()
        self.mcp = FakeMCP()


class DummyWEAVEStudyConstructionServer(WEAVEStudyConstructionServer):
    def __init__(self, templates_dir: Path):
        super().__init__(
            server_name="dummy-weave-study-server",
            description="Dummy WEAVE study construction server",
            study_templates_dir=templates_dir,
        )
        self.mcp = FakeMCP()

    def _prep_example(self, overrides: dict) -> dict:
        processed = dict(overrides)
        processed["prep_flag"] = "yes"
        return processed

    def register_study_construction_tools(self) -> None:
        self.register_jinja_study_tool(
            tool_name="construct_example_study",
            template_name="example.yaml",
            preprocess=self._prep_example,
        )


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """
    Create a temporary templates directory with realistic Jinja-backed YAML templates.

    Args:
        tmp_path (Path):
            Pytest temporary directory.

    Returns:
        Path:
            Path to the template directory.
    """
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    (template_dir / "example.yaml").write_text(
        """
{#-
mcp_doc: |
  Construct the example study.
  This template is used for integration testing.
-#}
description: example
name: {{ study_name }}
value: {{ required_value }}
optional: {{ optional_value | default("fallback") }}
prep_flag: {{ prep_flag | default("unset") }}
""".strip(),
        encoding="utf-8",
    )

    (template_dir / "secondary_study.yaml").write_text(
        """
{#-
mcp_doc: |
  Construct the secondary study.
-#}
description: secondary
alpha: {{ alpha_value }}
beta: {{ beta_value | default(5) }}
""".strip(),
        encoding="utf-8",
    )

    return template_dir


@pytest.fixture
def dummy_command_execution_server() -> DummyMaestroCommandExecutionServer:
    """
    Create a DummyMaestroCommandExecutionServer instance.

    Returns:
        DummyMaestroCommandExecutionServer:
            Configured server instance.
    """
    return DummyMaestroCommandExecutionServer()


@pytest.fixture
def dummy_study_construction_server(templates_dir: Path) -> DummyWEAVEStudyConstructionServer:
    """
    Create a DummyWEAVEStudyConstructionServer instance.

    Args:
        templates_dir (Path):
            Directory of test templates.

    Returns:
        DummyWEAVEStudyConstructionServer:
            Configured server instance.
    """
    return DummyWEAVEStudyConstructionServer(templates_dir)


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """
    Create a temporary JSON config file for integration tests that need server config.

    Args:
        tmp_path (Path):
            Pytest temporary directory.

    Returns:
        Path:
            Path to the config file.
    """
    config = {
        "servers": {
            "dummy-maestro": {
                "host": "127.0.0.1",
                "port": 8123,
                "transport": "streamable-http",
                "env_vars": {
                    "TEST_STATIC": "hello",
                    "TEST_EXPANDED": "${HOME}",
                    "TEST_DEFAULTED": "${MISSING_TEST_VAR:-default_value}",
                },
            }
        }
    }

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path
