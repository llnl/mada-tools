# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Unit tests for WEAVEStudyConstructionServer.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.workflow.weave import WEAVEStudyConstructionServer


class FakeMCP:
    """Minimal fake MCP object that records registered tool functions."""

    def __init__(self):
        """Initialize the fake MCP registry."""
        self.registered_tools = []

    def tool(self):
        """Return a decorator that records the decorated function."""

        def decorator(func):
            self.registered_tools.append(func)
            return func

        return decorator


class DummyWEAVEStudyConstructionServer(WEAVEStudyConstructionServer):
    """Concrete test subclass of `WEAVEStudyConstructionServer`."""

    def __init__(self, study_templates_dir: str | Path):
        """Initialize the dummy server."""
        super().__init__(
            server_name="dummy-maestro-server",
            description="Dummy Maestro server for tests",
            study_templates_dir=study_templates_dir,
        )
        self.mcp = FakeMCP()

    def register_study_construction_tools(self) -> None:
        """Register no custom tools for most tests."""
        return None

    def _prep_example(self, overrides):
        """Simple preprocess hook used by tests."""
        overrides = dict(overrides)
        overrides["preprocessed"] = True
        return overrides


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """
    Create a temporary templates directory with sample YAML templates.

    Args:
        tmp_path (Path):
            Pytest tmp_path fixture.

    Returns:
        A path containing template studies for testing.
    """
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()

    (tmpl_dir / "example.yaml").write_text(
        """{#-
mcp_doc: |
  Example tool doc.
-#}
description:
    name: example
    description: example study for testing

env:
    variables:
        VALUE: {{ required_value }}
        OPTIONAL: {{ optional_value | default("abc") }}
""",
        encoding="utf-8",
    )

    (tmpl_dir / "alpha_study.yaml").write_text(
        """description:
    name: alpha
    description: alpha test study

env:
    variables:
        VALUE: {{ alpha_value }}
""",
        encoding="utf-8",
    )

    (tmpl_dir / "beta.yaml").write_text(
        """description:
    name: beta
    description: beta test study

env:
    variables:
        VALUE: {{ beta_value | default(5) }}
""",
        encoding="utf-8",
    )

    return tmpl_dir


@pytest.fixture
def server(templates_dir: Path) -> DummyWEAVEStudyConstructionServer:
    """
    Create a `DummyWEAVEStudyConstructionServer` instance for tests.

    Args:
        templates_dir (Path):
            A path containing template studies for testing.

    Returns:
        A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
    """
    return DummyWEAVEStudyConstructionServer(templates_dir)


class TestWEAVEStudyConstructionServerInit:
    """Unit tests for `WEAVEStudyConstructionServer.__init__`."""

    def test_initializes_study_constructor(self, templates_dir: Path):
        """
        It should initialize `study_constructor`.

        Args:
            templates_dir (Path):
                A path containing template studies for testing.
        """
        srv = DummyWEAVEStudyConstructionServer(templates_dir)

        assert srv.server_name == "dummy-maestro-server"
        assert srv.description == "Dummy Maestro server for tests"
        assert srv.study_constructor is not None


class TestRegisterJinjaStudyTool:
    """Unit tests for `WEAVEStudyConstructionServer.register_jinja_study_tool`."""

    def test_raises_when_args_are_missing(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should raise `ValueError` if neither full mode nor directory mode is used.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        with pytest.raises(ValueError, match="Pass `tool_name` \\+ `template_name`, or pass `templates_dir`"):
            server.register_jinja_study_tool()

    def test_raises_when_templates_dir_is_combined_with_other_args(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should raise `ValueError` when templates_dir is mixed with incompatible args.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        with pytest.raises(ValueError, match="When `templates_dir` is provided"):
            server.register_jinja_study_tool(
                templates_dir=".",
                tool_name="construct_example_study",
            )

    def test_raises_when_templates_dir_does_not_exist(self, server: DummyWEAVEStudyConstructionServer, tmp_path: Path):
        """
        It should raise `FileNotFoundError` if the provided templates directory does not exist.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        missing_dir = tmp_path / "does_not_exist"

        with pytest.raises(FileNotFoundError, match="Templates directory .* does not exist"):
            server.register_jinja_study_tool(templates_dir=missing_dir)

    def test_registers_single_template_backed_tool(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should register one MCP tool for a single template.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        server.register_jinja_study_tool(
            tool_name="construct_example_study",
            template_name="example.yaml",
        )

        tool_names = [tool.__name__ for tool in server.mcp.registered_tools]
        assert "construct_example_study" in tool_names

    def test_registered_tool_has_generated_docstring(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should assign the template-derived docstring to the registered tool.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        server.register_jinja_study_tool(
            tool_name="construct_example_study",
            template_name="example.yaml",
        )

        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "construct_example_study")
        assert tool.__doc__ is not None
        assert "Example tool doc." in tool.__doc__
        assert "Required template variables" in tool.__doc__
        assert "Supported override keys" in tool.__doc__

    def test_registered_tool_builds_context_and_writes_yaml(
        self,
        server: DummyWEAVEStudyConstructionServer,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should call `build_context` and `write_yaml_tool` through `run_tool` when invoked.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest tmp_path fixture.
        """
        server.register_jinja_study_tool(
            tool_name="construct_example_study",
            template_name="example.yaml",
        )
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "construct_example_study")

        build_context_mock = MagicMock(return_value=(True, {"required_value": 123}))
        write_yaml_mock = MagicMock(return_value=(True, f"Wrote Maestro study YAML to {tmp_path / 'example.yaml'}"))

        monkeypatch.setattr(server.study_constructor, "build_context", build_context_mock)
        monkeypatch.setattr(server.study_constructor, "write_yaml_tool", write_yaml_mock)

        result = tool(overrides={"required_value": 123}, output_dir=tmp_path)

        assert "Wrote Maestro study YAML to" in result
        build_context_mock.assert_called_once()
        write_yaml_mock.assert_called_once()

    def test_registers_all_yaml_templates_from_directory(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should register one tool per YAML template in directory mode.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        server.register_jinja_study_tool(templates_dir=".")

        tool_names = sorted(tool.__name__ for tool in server.mcp.registered_tools)
        assert "construct_alpha_study" in tool_names
        assert "construct_beta_study" in tool_names
        assert "construct_example_study" in tool_names

    def test_directory_mode_uses_derived_preprocess_hook_when_present(
        self, server: DummyWEAVEStudyConstructionServer, monkeypatch: MonkeyPatch
    ):
        """
        It should use a matching `_prep_<stem>` preprocess hook when available.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        captured = {}

        original = server.register_jinja_study_tool

        def spy_register_jinja_study_tool(*args, **kwargs):
            if kwargs.get("tool_name") == "construct_example_study":
                captured["preprocess"] = kwargs.get("preprocess")
            return original(*args, **kwargs)

        monkeypatch.setattr(server, "register_jinja_study_tool", spy_register_jinja_study_tool)
        spy_register_jinja_study_tool(templates_dir=".")

        assert captured["preprocess"] == server._prep_example


class TestRegisterPathTools:
    """Unit tests for `WEAVEStudyConstructionServer._register_path_tools`."""

    def test_registers_abspath_tool(self, server: DummyWEAVEStudyConstructionServer):
        """
        It should register an abspath MCP tool.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
        """
        server._register_path_tools()

        tool_names = [tool.__name__ for tool in server.mcp.registered_tools]
        assert "abspath" in tool_names

    def test_abspath_tool_calls_run_tool(self, server: DummyWEAVEStudyConstructionServer, monkeypatch: MonkeyPatch):
        """
        The abspath tool should delegate to `run_tool` with `study_constructor.abspath`.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        server._register_path_tools()
        tool = next(t for t in server.mcp.registered_tools if t.__name__ == "abspath")

        run_tool_mock = MagicMock(return_value="/tmp/output.yaml")
        monkeypatch.setattr(server, "run_tool", run_tool_mock)

        result = tool("relative/path.yaml")

        assert result == "/tmp/output.yaml"
        run_tool_mock.assert_called_once()


class TestRegisterTools:
    """Unit tests for `WEAVEStudyConstructionServer._register_tools`."""

    def test_register_tools_calls_component_registration_methods(
        self, server: DummyWEAVEStudyConstructionServer, monkeypatch: MonkeyPatch
    ):
        """
        It should register path tools, workflow tools, and subclass study construction tools.

        Args:
            server (DummyWEAVEStudyConstructionServer):
                A dummy, concrete implementation of the `WEAVEStudyConstructionServer` class.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        path_mock = MagicMock()
        study_mock = MagicMock()

        monkeypatch.setattr(server, "_register_path_tools", path_mock)
        monkeypatch.setattr(server, "register_study_construction_tools", study_mock)

        server._register_tools()

        path_mock.assert_called_once_with()
        study_mock.assert_called_once_with()
