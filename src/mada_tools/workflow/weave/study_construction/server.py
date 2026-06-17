# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Abstract MCP server for WEAVE study construction.

This module provides a base server for registering MCP tools that build
Jinja-templated WEAVE study YAML files. It supports common path utilities
and template-backed study construction, while leaving project-specific tool
registration to subclasses.

The server is designed to work with WEAVE orchestration command execution
servers such as Maestro, Merlin, and StudyWeaver.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict

from mada_tools import BaseMCPServer
from mada_tools.workflow.weave.study_construction.study_constructor import WEAVEStudyConstructor


class WEAVEStudyConstructionServer(BaseMCPServer, ABC):
    """
    Abstract base class for constructing studies that WEAVE Orchestration tools
    can execute. WEAVE Orchestration tools include Maestro, Merlin, and StudyWeaver.

    This class is not intended to be instantiated directly. Subclasses define
    project-specific tools for constructing studies from Jinja-templated
    workflow templates, while inheriting common utilities for path handling.

    This server should be used alongside WEAVE-Orchestration-tool-specific command
    execution servers. For instance, the `MaestroCommandExecutionServer`.

    Attributes:
        study_constructor: A `WEAVEStudyConstructor` instance used to build
            template contexts, render templates, and write WEAVE YAML files.

    Methods:
        register_jinja_study_tool: Register a tool backed by a single Jinja
            study template, or register multiple tools from a templates
            directory.
        register_study_construction_tools: Abstract hook for subclasses to
            register their own study construction tools.
        _register_path_tools: Register tools for working with filesystem paths.
        _register_tools: Register all built-in and subclass-provided tools.
    """

    def __init__(
        self,
        server_name: str,
        description: str,
        study_templates_dir: str | Path,
    ):
        """
        Constructor for `WEAVEStudyConstructionServer`.

        Args:
            server_name (str):
                The name of the MCP server
            description (str):
                Description of the server
            study_templates_dir (str | Path):
                The path to the directory where templated study YAML files live.
        """
        super().__init__(server_name, description)

        # Class for constructing workflows from templates
        self.study_constructor = WEAVEStudyConstructor(study_templates_dir)

    def register_jinja_study_tool(
        self,
        *,
        tool_name: str | None = None,
        template_name: str | Path | None = None,
        templates_dir: str | Path | None = None,
        preprocess: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    ) -> None:
        """Register a template-backed tool with a minimal call signature.

        The tool signature is intentionally small so we don't have to re-declare
        template keys/defaults in Python. Agents discover valid keys via the
        template `mcp_doc` section (plus the auto-generated key list).

        Args:
            tool_name: MCP tool name to register (required when `templates_dir` is not provided).
            template_name: Template filename or absolute path (required when `templates_dir` is not provided).
            templates_dir: If provided, register one tool per `*.yaml` file in this directory.
                Tool names are derived as `construct_{template_stem}_study` and preprocess hooks are
                resolved as `self._prep_{template_stem}` when present.
            preprocess: Optional hook to validate/normalize override values before rendering.

        Returns:
            None

        Raises:
            ValueError: If arguments are inconsistent (e.g., both `templates_dir` and `template_name` are provided).
            FileNotFoundError: If `templates_dir` does not exist.
        """

        if templates_dir is not None:
            if tool_name is not None or template_name is not None or preprocess is not None:
                raise ValueError(
                    "When `templates_dir` is provided, do not pass `tool_name`, `template_name`, or `preprocess`."
                )
            dir_path = templates_dir if isinstance(templates_dir, Path) else Path(str(templates_dir))
            if not dir_path.is_absolute():
                dir_path = self.study_constructor.study_templates_dir / dir_path
            if not dir_path.exists():
                raise FileNotFoundError(f"Templates directory '{dir_path}' does not exist.")

            for template_path in sorted(dir_path.glob("*.yaml")):
                stem = template_path.stem
                if stem.endswith("_study"):
                    stem = stem[: -len("_study")]
                derived_tool_name = f"construct_{stem}_study"
                derived_preprocess = getattr(self, f"_prep_{stem}", None)
                self.register_jinja_study_tool(
                    tool_name=derived_tool_name,
                    template_name=template_path,
                    preprocess=derived_preprocess,
                )
            return

        if tool_name is None or template_name is None:
            raise ValueError("Pass `tool_name` + `template_name`, or pass `templates_dir`.")

        def _tool(
            overrides: Dict[str, Any] | None = None,
            output_dir: str | Path | None = None,
        ) -> str:
            """Render the registered Jinja study template and write a Maestro YAML."""
            context = self.run_tool(
                self.study_constructor.build_context,
                template_name,
                overrides=overrides,
                preprocess=preprocess,
            )
            return self.run_tool(
                self.study_constructor.write_yaml_tool,
                template_name,
                context,
                output_dir=output_dir,
            )

        _tool.__name__ = tool_name
        _tool.__doc__ = self.study_constructor.get_tool_doc_from_template(template_name)
        self.mcp.tool()(_tool)

    def _register_path_tools(self):
        """Register tools related to file system paths."""

        @self.mcp.tool()
        def abspath(output_path: str, base_path: str = None) -> str:
            """Convert a user-provided path into an absolute path on the server.

            Args:
                output_path: Path to convert. Relative paths are resolved against the `base_path`.
                base_path: The base path that the `output_path` is relative to. Defaults to the
                    current working directory.

            Returns:
                The absolute path as a string.
            """
            return self.run_tool(self.study_constructor.abspath, output_path, base_path=base_path)

    @abstractmethod
    def register_study_construction_tools(self) -> None:
        """Hook for subclasses to register their own template-backed study tools.

        Each tool defined here should utilize the `self.register_jinja_study_tool()`.
        Preprocessing can be added to each tool by creating a separate method in your
        class and linking your tool to it.

        Example:

            Here's a full example that defines a study construction tool with preprocessing.
            In this example, we're targeting the creation of a study called `my_cool_study`
            that needs a path `py3_utils` in order to run. As part of the preprocessing, we
            coerce the path of `py3_utils` to ensure it's provided and exists.

            ```python
            from mada_tools.workflow.weave import WEAVEStudyConstructionServer

            class MyProjectStudyConstructionServer(WEAVEStudyConstructionServer):
                def _prep_my_cool_study(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
                    # Preprocess this study by validating a path that's needed
                    raw_py3 = overrides.get("py3_utils")
                    if raw_py3 is None:
                        py3_utils_path = Path(__file__).parent / "py3utils"
                    else:
                        py3_utils_path = raw_py3 if isinstance(raw_py3, Path) else Path(str(raw_py3))
                    if not py3_utils_path.exists():
                        raise FileNotFoundError(f"The py3utils directory '{py3_utils_path}' does not exist.")
                    overrides["py3_utils"] = str(py3_utils_path)
                    return overrides

                def register_study_construction_tools(self):

                    # Register the tool that constructs your cool study
                    self.register_jinja_study_tool(
                        tool_name="construct_my_cool_study",
                        template_name="my_cool_study.yaml",
                        preprocess=self._prep_my_cool_study,
                    )
            ```
        """
        pass

    def _register_tools(self):
        """Register MCP tools for WEAVE study construction operations."""

        self._register_path_tools()
        self.register_study_construction_tools()
