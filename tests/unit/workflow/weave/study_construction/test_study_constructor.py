# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Unit tests for WEAVEStudyConstructor.

These tests validate template directory initialization, context extraction,
tool documentation generation, YAML rendering and writing, path normalization,
and helper parsing behavior.
"""

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.shared import TemplateContextError
from mada_tools.workflow.weave.study_construction.study_constructor import WEAVEStudyConstructor


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """
    Create a temporary template directory populated with sample Jinja YAML templates.

    Args:
        tmp_path (Path):
            Pytest tmp_path fixture.

    Returns:
            Path to the created template directory.
    """
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    (template_dir / "simple.yaml").write_text(
        """
description: simple study
value: {{ required_value }}
optional: {{ optional_value | default("abc") }}
""".strip(),
        encoding="utf-8",
    )

    (template_dir / "doc_template.yaml").write_text(
        """
{#-
mcp_doc: |
  Construct a documented study.
  This template is for unit testing.
-#}
description: documented
value: {{ required_value }}
optional: {{ optional_value | default("xyz") }}
""".strip(),
        encoding="utf-8",
    )

    (template_dir / "sw_render.yaml").write_text(
        """
sw.render:
  engine: jinja2
  notes: remove me
description: rendered
value: {{ required_value }}
""".strip(),
        encoding="utf-8",
    )

    return template_dir


@pytest.fixture
def constructor(templates_dir: Path) -> WEAVEStudyConstructor:
    """
    Create a `WEAVEStudyConstructor` instance for tests.

    Args:
        templates_dir (Path):
            Temporary templates directory.

    Returns:
        Configured constructor instance.
    """
    return WEAVEStudyConstructor(templates_dir)


class TestWEAVEStudyConstructorInit:
    """Unit tests for `WEAVEStudyConstructor.__init__`."""

    def test_raises_if_study_templates_dir_is_none(self):
        """
        It should raise `ValueError` when the study templates directory is not provided.
        """
        with pytest.raises(ValueError, match="`study_templates_dir` must be provided."):
            WEAVEStudyConstructor(None)

    def test_raises_if_study_templates_dir_does_not_exist(self, tmp_path: Path):
        """
        It should raise `ValueError` when the study templates directory does not exist.

        Args:
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        missing = tmp_path / "missing_dir"

        with pytest.raises(ValueError, match="does not exist"):
            WEAVEStudyConstructor(missing)

    def test_raises_if_study_templates_dir_is_not_a_directory(self, tmp_path: Path):
        """
        It should raise `ValueError` when the provided path is not a directory.

        Args:
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello", encoding="utf-8")

        with pytest.raises(ValueError, match="is not a directory"):
            WEAVEStudyConstructor(file_path)

    def test_initializes_with_valid_directory(self, templates_dir: Path):
        """
        It should initialize successfully with a valid template directory.

        Args:
            templates_dir (Path):
                Temporary templates directory.
        """
        instance = WEAVEStudyConstructor(templates_dir)

        assert instance.study_templates_dir == templates_dir.resolve()
        assert instance.study_templates_env is not None


class TestGetContextFromTemplate:
    """Unit tests for `WEAVEStudyConstructor.get_context_from_template`."""

    def test_returns_context_with_required_override_only(self, constructor: WEAVEStudyConstructor):
        """
        It should return a context containing only supplied overrides.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        context = constructor.get_context_from_template("simple.yaml", required_value=123)

        assert context == {"required_value": 123}

    def test_ignores_none_overrides(self, constructor: WEAVEStudyConstructor):
        """
        It should ignore overrides whose values are None.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        context = constructor.get_context_from_template(
            "simple.yaml",
            required_value=123,
            optional_value=None,
        )

        assert context == {"required_value": 123}

    def test_raises_for_unknown_override_keys(self, constructor: WEAVEStudyConstructor):
        """
        It should raise `TemplateContextError` when unknown override keys are provided.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        with pytest.raises(TemplateContextError, match="unknown template variables"):
            constructor.get_context_from_template(
                "simple.yaml",
                required_value=123,
                extra_key="bad",
            )

    def test_raises_when_required_template_variables_are_missing(self, constructor: WEAVEStudyConstructor):
        """
        It should raise `TemplateContextError` when required variables are not provided.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        with pytest.raises(TemplateContextError, match="missing required template variables"):
            constructor.get_context_from_template("simple.yaml")

    def test_accepts_absolute_template_path(self, constructor: WEAVEStudyConstructor, templates_dir: Path):
        """
        It should accept an absolute template path.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            templates_dir (Path):
                Temporary templates directory.
        """
        template_path = templates_dir / "simple.yaml"

        context = constructor.get_context_from_template(template_path, required_value=456)

        assert context == {"required_value": 456}


class TestGetToolDocFromTemplate:
    """Unit tests for `WEAVEStudyConstructor.get_tool_doc_from_template`."""

    def test_returns_combined_doc_with_required_and_supported_keys(self, constructor: WEAVEStudyConstructor):
        """
        It should return template MCP documentation plus generated variable summaries.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        doc = constructor.get_tool_doc_from_template("doc_template.yaml")

        assert "Construct a documented study." in doc
        assert "This template is for unit testing." in doc
        assert "Template-backed tool." in doc
        assert "Required template variables: required_value" in doc
        assert "Supported override keys:" in doc
        assert "required_value" in doc
        assert "optional_value" in doc

    def test_returns_generated_doc_when_no_mcp_doc_exists(self, constructor: WEAVEStudyConstructor):
        """
        It should still generate tool documentation when no MCP doc block is present.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        doc = constructor.get_tool_doc_from_template("simple.yaml")

        assert "Template-backed tool." in doc
        assert "Required template variables: required_value" in doc
        assert "Supported override keys:" in doc

    def test_accepts_absolute_template_path(self, constructor: WEAVEStudyConstructor, templates_dir: Path):
        """
        It should accept an absolute template path when generating documentation.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            templates_dir (Path):
                Temporary templates directory.
        """
        doc = constructor.get_tool_doc_from_template(templates_dir / "doc_template.yaml")

        assert "Construct a documented study." in doc


class TestWriteYaml:
    """Unit tests for `WEAVEStudyConstructor.write_yaml`."""

    def test_writes_rendered_yaml_to_current_working_directory(
        self,
        constructor: WEAVEStudyConstructor,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should write rendered YAML to the current working directory when `output_dir` is not provided.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        monkeypatch.chdir(tmp_path)

        output_path = constructor.write_yaml("simple.yaml", {"required_value": 99})

        assert output_path == tmp_path / "simple.yaml"
        assert output_path.exists()
        contents = output_path.read_text(encoding="utf-8")
        assert "value: 99" in contents

    def test_writes_rendered_yaml_to_explicit_output_dir(
        self,
        constructor: WEAVEStudyConstructor,
        tmp_path: Path,
    ):
        """
        It should write rendered YAML to an explicitly provided output directory.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        output_dir = tmp_path / "out"

        output_path = constructor.write_yaml("simple.yaml", {"required_value": 42}, output_dir=output_dir)

        assert output_path == output_dir / "simple.yaml"
        assert output_path.exists()
        assert "value: 42" in output_path.read_text(encoding="utf-8")

    def test_creates_output_directory_if_needed(self, constructor: WEAVEStudyConstructor, tmp_path: Path):
        """
        It should create the output directory if it does not already exist.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        output_dir = tmp_path / "nested" / "dir"

        output_path = constructor.write_yaml("simple.yaml", {"required_value": 7}, output_dir=output_dir)

        assert output_dir.exists()
        assert output_path.exists()

    def test_removes_top_level_sw_render_block(self, constructor: WEAVEStudyConstructor, tmp_path: Path):
        """
        It should strip the top-level `sw.render` block from rendered output.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        output_path = constructor.write_yaml("sw_render.yaml", {"required_value": 1}, output_dir=tmp_path)
        contents = output_path.read_text(encoding="utf-8")

        assert "sw.render:" not in contents
        assert "description: rendered" in contents
        assert "value: 1" in contents


class TestBuildContext:
    """Unit tests for `WEAVEStudyConstructor.build_context`."""

    def test_returns_success_and_context_for_valid_input(self, constructor: WEAVEStudyConstructor):
        """
        It should return a success tuple and constructed context for valid overrides.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        success, payload = constructor.build_context(
            "simple.yaml",
            overrides={"required_value": 12},
        )

        assert success is True
        assert payload == {"required_value": 12}

    def test_filters_none_values_before_processing(self, constructor: WEAVEStudyConstructor):
        """
        It should remove None-valued overrides before building context.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        success, payload = constructor.build_context(
            "simple.yaml",
            overrides={"required_value": 12, "optional_value": None},
        )

        assert success is True
        assert payload == {"required_value": 12}

    def test_applies_preprocess_hook(self, constructor: WEAVEStudyConstructor):
        """
        It should apply the preprocess hook before building context.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """

        def preprocess(overrides):
            overrides = dict(overrides)
            overrides["required_value"] = overrides["required_value"] * 2
            return overrides

        success, payload = constructor.build_context(
            "simple.yaml",
            overrides={"required_value": 5},
            preprocess=preprocess,
        )

        assert success is True
        assert payload == {"required_value": 10}

    def test_returns_failure_tuple_on_exception(self, constructor: WEAVEStudyConstructor):
        """
        It should return a failure tuple when context creation raises an exception.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        success, payload = constructor.build_context("simple.yaml", overrides={})

        assert success is False
        assert "missing required template variables" in payload


class TestWriteYamlTool:
    """Unit tests for `WEAVEStudyConstructor.write_yaml_tool`."""

    def test_returns_success_message_when_yaml_is_written(
        self,
        constructor: WEAVEStudyConstructor,
        tmp_path: Path,
    ):
        """
        It should return a success tuple with the written file path.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        success, payload = constructor.write_yaml_tool(
            "simple.yaml",
            {"required_value": 100},
            output_dir=tmp_path,
        )

        assert success is True
        assert "Wrote Maestro study YAML to" in payload
        assert str(tmp_path / "simple.yaml") in payload

    def test_returns_failure_tuple_when_write_fails(self, constructor: WEAVEStudyConstructor):
        """
        It should return a failure tuple when writing YAML fails.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        success, payload = constructor.write_yaml_tool(
            "missing.yaml",
            {"required_value": 100},
        )

        assert success is False
        assert payload


class TestAbspath:
    """Unit tests for `WEAVEStudyConstructor.abspath`."""

    def test_returns_absolute_path_for_relative_input(
        self,
        constructor: WEAVEStudyConstructor,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ):
        """
        It should resolve a relative path against the current working directory.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        monkeypatch.chdir(tmp_path)

        success, payload = constructor.abspath("foo/bar.yaml")

        assert success is True
        assert payload == str((tmp_path / "foo" / "bar.yaml").resolve(strict=False))

    def test_returns_absolute_path_for_absolute_input(self, constructor: WEAVEStudyConstructor, tmp_path: Path):
        """
        It should return a normalized absolute path when given an absolute input path.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            tmp_path (Path):
                Pytest-provided temporary directory.
        """
        absolute_path = tmp_path / "abc.yaml"

        success, payload = constructor.abspath(str(absolute_path))

        assert success is True
        assert payload == str(absolute_path.resolve(strict=False))


class TestExtractTemplateVariables:
    """Unit tests for `WEAVEStudyConstructor._extract_template_variables`."""

    def test_extracts_undeclared_template_variables(self, constructor: WEAVEStudyConstructor):
        """
        It should extract undeclared variables from template text.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        template_text = """
value: {{ alpha }}
other: {{ beta }}
"""

        variables = constructor._extract_template_variables(template_text)

        assert variables == {"alpha", "beta"}


class TestExtractDefaultedVariables:
    """Unit tests for `WEAVEStudyConstructor._extract_defaulted_variables`."""

    def test_extracts_variables_with_default_filter(self, constructor: WEAVEStudyConstructor):
        """
        It should extract variables that use the Jinja default filter.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        template_text = """
a: {{ alpha | default(1) }}
b: {{ beta }}
c: {{ gamma | default("x") }}
"""

        variables = constructor._extract_defaulted_variables(template_text)

        assert variables == {"alpha", "gamma"}


class TestExtractMcpDoc:
    """Unit tests for `WEAVEStudyConstructor._extract_mcp_doc`."""

    def test_returns_none_when_no_doc_block_exists(self, constructor: WEAVEStudyConstructor):
        """
        It should return None when no mcp_doc block exists.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        template_text = """
description: test
value: {{ x }}
"""

        doc = constructor._extract_mcp_doc(template_text)

        assert doc is None

    def test_extracts_mcp_doc_from_comment_block(self, constructor: WEAVEStudyConstructor):
        """
        It should extract mcp_doc text from a Jinja comment block.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        template_text = """
{#-
mcp_doc: |
  Hello world.
  Another line.
-#}
description: test
"""

        doc = constructor._extract_mcp_doc(template_text)

        assert doc == "Hello world.\nAnother line."

    def test_raises_when_doc_block_yaml_is_invalid(self, constructor: WEAVEStudyConstructor):
        """
        It should raise TemplateContextError when the mcp_doc block cannot be parsed as YAML.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        template_text = """
{#-
mcp_doc: |
  test
bad: [unterminated
-#}
"""

        with pytest.raises(TemplateContextError, match="Failed to parse mcp_doc block"):
            constructor._extract_mcp_doc(template_text)


class TestRenderYaml:
    """Unit tests for `WEAVEStudyConstructor._render_yaml`."""

    def test_renders_yaml_from_relative_template_name(self, constructor: WEAVEStudyConstructor):
        """
        It should render YAML from a template name relative to the template loader.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
        """
        rendered_yaml, output_filename = constructor._render_yaml(
            "simple.yaml",
            {"required_value": 321},
        )

        assert output_filename == "simple.yaml"
        assert "value: 321" in rendered_yaml

    def test_renders_yaml_from_absolute_template_path(
        self,
        constructor: WEAVEStudyConstructor,
        templates_dir: Path,
    ):
        """
        It should render YAML from an absolute template path.

        Args:
            constructor (WEAVEStudyConstructor):
                An instance of the `WEAVEStudyConstructor`.
            templates_dir (Path):
                Temporary templates directory.
        """
        template_path = templates_dir / "simple.yaml"

        rendered_yaml, output_filename = constructor._render_yaml(
            template_path,
            {"required_value": 654},
        )

        assert output_filename == "simple.yaml"
        assert "value: 654" in rendered_yaml
