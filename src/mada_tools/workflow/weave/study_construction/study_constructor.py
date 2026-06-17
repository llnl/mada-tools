# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Utilities for inspecting, validating, rendering, and writing Jinja-backed
WEAVE orchestration tool YAML templates. WEAVE orchestration tool refers to
any workflow orchestration tool managed by WEAVE (Maestro, Merlin, StudyWeaver).

This module provides the `WEAVEStudyConstructor` class, which is responsible
for:

- locating and validating a study template directory,
- introspecting Jinja templates to discover referenced variables,
- distinguishing required template variables from those with Jinja defaults,
- extracting embedded MCP-facing documentation from template comments,
- building validated render contexts from user overrides,
- rendering YAML output from templates, and
- writing rendered study definitions to disk.

The class also includes tool-oriented wrapper methods that convert exceptions
into `(success, payload)` tuples for easier integration with MCP-style tooling.

Typical usage consists of creating a `WEAVEStudyConstructor` with a directory
of study templates, building a context for a selected template, and then
rendering or writing the resulting YAML file.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import yaml
from jinja2 import Environment, FileSystemLoader, meta

from mada_tools.shared import TemplateContextError


class WEAVEStudyConstructor:
    """
    Construct, inspect, and render Maestro study YAML files from Jinja templates.

    This class manages a directory of Jinja-based study templates and provides
    helper methods for discovering template variables, validating caller
    overrides, extracting embedded tool documentation, rendering templates, and
    writing rendered YAML files to disk.

    It supports both direct API-style methods that raise exceptions on failure
    and tool-facing wrapper methods that return `(success, payload)` tuples for
    easier integration with external systems.

    Attributes:
        study_templates_dir (Path):
            Absolute path to the directory containing Maestro study templates.
        study_templates_env (jinja2.Environment):
            Jinja environment configured to load templates from
            `study_templates_dir`.

    Methods:
        get_context_from_template:
            Build a validated render context for a template using supplied
            override values.
        get_tool_doc_from_template:
            Extract embedded MCP documentation from a template and augment it
            with discovered template-variable information.
        write_yaml:
            Render a template and write the resulting YAML file to disk.
        build_context:
            Tool-facing wrapper that prepares and validates template context,
            returning a `(success, payload)` tuple.
        write_yaml_tool:
            Tool-facing wrapper that renders and writes YAML, returning a
            `(success, payload)` tuple.
        abspath:
            Resolve a user-provided path to an absolute filesystem path.
    """

    def __init__(self, study_templates_dir: Path):
        """
        Constructor method for `MaestroStudyConstructor`.

        Args:
            study_templates_dir (Path):
                The path to the directory where templated Maestro study YAML files live.
        """

        # Validation for the study templates directory
        if study_templates_dir is None:
            raise ValueError("`study_templates_dir` must be provided.")

        self.study_templates_dir = Path(study_templates_dir).expanduser().resolve()
        if not self.study_templates_dir.exists():
            raise ValueError(f"Study templates directory '{self.study_templates_dir}' does not exist.")
        if not self.study_templates_dir.is_dir():
            raise ValueError(f"Study templates directory '{self.study_templates_dir}' is not a directory.")

        # Environment for study templates
        self.study_templates_env = Environment(
            loader=FileSystemLoader(self.study_templates_dir),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    ##################
    ### Public API ###
    ##################

    def get_context_from_template(self, template_file: str | Path, **kwargs: Any) -> Dict[str, Any]:
        """Build a render context for a study template.

        Template defaults should be encoded in the template itself via Jinja's
        `default(...)` filter; values in `kwargs` override those defaults.

        Example:

            Say you have a study `my_study.yaml` with the following environment variable:

            ```yaml
            env:
                variables:
                    LZMIN: {{ lzmin | default(200.0) }}
            ```

            Calling this method without any kwargs, `get_context_from_template("my_study.yaml")`
            will result in an empty context `{}`. However, calling this method with the `lzmin`
            kwarg, `get_context_from_template("my_study.yaml", lzmin=300.0)` will result in a
            populated context `{"lzmin": 300.0}`.

        Args:
            template_file: Template filename (relative to this server's study template directory)
                or an absolute path to a template file on disk.
            **kwargs: Template variable overrides. Keys must correspond to variables referenced
                in the template; values override the template's own defaults.

        Returns:
            A dictionary suitable for rendering the Jinja template via `template.render(**context)`.

        Raises:
            ToolExecutionError: If overrides include unknown keys, required variables are missing,
                or the template's `mcp_doc`/metadata blocks cannot be parsed.
        """
        template_path = template_file if isinstance(template_file, Path) else Path(template_file)
        if not template_path.is_absolute():
            template_path = self.study_templates_dir / template_path

        template_text = template_path.read_text(encoding="utf-8")
        template_vars = self._extract_template_variables(template_text)
        defaulted_vars = self._extract_defaulted_variables(template_text)

        # Treat explicit None as "unset" so callers can supply a complete key set
        # (e.g., in examples) without overriding template defaults.
        cleaned_overrides: Dict[str, Any] = {k: v for k, v in kwargs.items() if v is not None}

        context: Dict[str, Any] = {}
        context.update(cleaned_overrides)

        unknown = set(cleaned_overrides) - template_vars
        if unknown:
            raise TemplateContextError(
                f"{template_path.name}: unknown template variables in overrides: {sorted(unknown)}"
            )

        missing_required = template_vars - defaulted_vars - set(context)
        if missing_required:
            raise TemplateContextError(
                f"{template_path.name}: missing required template variables: {sorted(missing_required)}"
            )

        return context

    def get_tool_doc_from_template(self, template_file: str | Path) -> str:
        """Build an MCP tool docstring from a Jinja study template.

        This reads the template text, extracts the trailing `{# mcp_doc: | ... #}` block (if present),
        then appends an auto-generated summary of supported override keys and which keys appear to be
        required (i.e., referenced without a `| default(...)` filter).

        Args:
            template_file: Template filename (relative to this server's study template directory)
                or an absolute path to a template file on disk.

        Returns:
            A human-facing docstring to attach to the corresponding MCP tool.

        Raises:
            ToolExecutionError: If the template cannot be read or its embedded `mcp_doc` block
                cannot be parsed.
        """
        template_path = template_file if isinstance(template_file, Path) else Path(template_file)
        if not template_path.is_absolute():
            template_path = self.study_templates_dir / template_path

        template_text = template_path.read_text(encoding="utf-8")
        base_doc = self._extract_mcp_doc(template_text) or ""

        template_vars = sorted(self._extract_template_variables(template_text))
        defaulted_vars = set(self._extract_defaulted_variables(template_text))
        required = [v for v in template_vars if v not in defaulted_vars]

        lines: List[str] = []
        if base_doc:
            lines.append(base_doc.strip())
            lines.append("")

        lines.append("Template-backed tool.")
        if required:
            lines.append(f"Required template variables: {', '.join(required)}")
        if template_vars:
            lines.append(f"Supported override keys: {', '.join(template_vars)}")

        return "\n".join(lines).strip()

    def write_yaml(self, template_name: str | Path, context: Dict[str, Any], output_dir: str | Path = None) -> Path:
        """
        Given the name of a jinja templated workflow and the context for it, fill out
        the template and write it to the file system.

        Args:
            template_name: The name of the template in the jinja environment.
            context: A dictionary of settings to pass to the template.
            output_dir: The location to write the file to. If None, uses the current
                working directory.

        Returns:
            The path to the YAML file that was written to the file system.

        Raises:
            OSError: If the output file cannot be written.
            jinja2.TemplateNotFound: If the template cannot be located by the loader.
        """
        rendered_yaml, output_filename = self._render_yaml(template_name, context)

        # StudyWeaver embeds a top-level `sw.render` block to enable pre-rendering
        # of Jinja-containing YAML. Maestro doesn't need it; strip it from outputs.
        #
        # Important: do not use DOTALL here, otherwise the match can consume the entire file.
        rendered_yaml = re.sub(
            r"(?m)^sw\.render:\n(?:^[ \t]+[^\n]*(?:\n|$))+",
            "",
            rendered_yaml,
        )

        # Create the directory if it doesn't already exist
        if output_dir is None:
            output_dir = Path.cwd()
        elif not isinstance(output_dir, Path):
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write the rendered template to the file system
        file_path = output_dir / output_filename
        with open(file_path, "w", encoding="utf-8") as outfile:
            outfile.write(rendered_yaml)

        return file_path

    ############################
    ### Tool-facing wrappers ###
    ############################

    def build_context(
        self,
        template_name: str | Path,
        overrides: Dict[str, Any] | None = None,
        preprocess: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    ) -> tuple[bool, Dict[str, Any] | str]:
        """Build a rendering context for a Maestro study template.

        This method merges user-provided override values, removes any entries
        with `None` values, optionally applies a preprocessing hook to validate
        or normalize the overrides, and then generates the final template
        context using `get_context_from_template`.

        **Note:** This method does not raise exceptions directly. Any exception
        is caught and returned in the failure payload as a string.

        Args:
            template_name: Name or path of the Jinja-backed Maestro template.
            overrides: Optional dictionary of values to override template defaults.
                Any keys with `None` values are ignored.
            preprocess: Optional callable that takes the merged overrides and
                returns a validated or normalized mapping before context creation.

        Returns:
            tuple[bool, Dict[str, Any] | str]:
                A `(success, payload)` tuple. On success, returns `True` and the
                constructed context dictionary. On failure, returns `False` and
                an error message.
        """
        try:
            merged = {k: v for k, v in (overrides or {}).items() if v is not None}
            if preprocess is not None:
                merged = preprocess(merged)

            context = self.get_context_from_template(template_name, **merged)
            return True, context
        except Exception as e:
            return False, str(e)

    def write_yaml_tool(
        self,
        template_name: str | Path,
        context: Dict[str, Any],
        output_dir: str | Path | None = None,
    ) -> tuple[bool, str]:
        """Render a Maestro study template and write the resulting YAML to disk.

        This method wraps `write_yaml` in the standard tool response format used
        by the MCP server, returning either a success message with the output
        file path or an error message.

        **Note:** This method does not raise exceptions directly. Any exception
        is caught and returned in the failure payload as a string.

        Args:
            template_name: Name or path of the Maestro template to render.
            context: Fully prepared rendering context for the template.
            output_dir: Optional directory where the rendered YAML file should be
                written. If not provided, the default output location is used.

        Returns:
            tuple[bool, str]:
                A `(success, payload)` tuple. On success, returns `True` and a
                message containing the written file path. On failure, returns
                `False` and an error message.
        """
        try:
            file_path = self.write_yaml(template_name, context, output_dir=output_dir)
            return True, f"Wrote Maestro study YAML to {file_path}"
        except Exception as e:
            return False, str(e)

    def abspath(self, output_path: str, base_path: str = None) -> tuple[bool, str]:
        """Convert a user-provided path into an absolute path on the server.

        Args:
            output_path: Path to convert. Relative paths are resolved against the `base_path`.
            base_path: The base path that the `output_path` is relative to. Defaults to the
                current working directory.

        Returns:
            A tuple containing a success flag and the absolute path as a string.
        """
        try:
            p = Path(output_path).expanduser()

            if not p.is_absolute():
                base = Path(base_path).expanduser() if base_path else Path.cwd()
                p = base / p

            return True, str(p.resolve(strict=False))
        except Exception as e:
            return False, str(e)

    #######################
    ### Private helpers ###
    #######################

    def _extract_template_variables(self, template_text: str) -> Set[str]:
        """Extract undeclared variable names referenced in a Jinja template.

        This method parses the provided template text using Jinja's AST utilities
        and returns the set of variable names that are referenced in the template
        but not defined within the template itself. These variables typically
        represent values that must be supplied externally when rendering.

        This is useful for:
        - identifying required or configurable template inputs,
        - generating documentation for template-backed tools,
        - validating that a caller has supplied all needed context values.

        Args:
            template_text: Raw text contents of a Jinja template.

        Returns:
            Set[str]: A set of undeclared variable names referenced by the template.
        """
        env = Environment()
        parsed = env.parse(template_text)
        return set(meta.find_undeclared_variables(parsed))

    def _extract_defaulted_variables(self, template_text: str) -> Set[str]:
        """Identify variables that appear to use Jinja's `default(...)` filter.

        This method performs a best-effort regex-based scan of the template text
        and returns variable names that are used in an expression containing the
        `| default(...)` filter. These variables are often optional, since the
        template provides a fallback value if they are not supplied at render time.

        This is primarily useful for documentation and input introspection, such as
        distinguishing between variables that may require caller-provided values and
        variables that already have a template-level fallback.

        Args:
            template_text: Raw text contents of a Jinja template.

        Returns:
            Set[str]: A set of variable names that appear with a `| default(...)`
            filter in the template.
        """
        default_filer_regex = re.compile(
            r"{{[^}]*\b(?P<var>[A-Za-z_]\w*)\b[^}]*\|\s*default\s*\(",
            flags=re.MULTILINE,
        )
        return {m.group("var") for m in default_filer_regex.finditer(template_text)}

    def _extract_mcp_doc(self, template_text: str) -> Optional[str]:
        """Extract a human-facing MCP tool description from a Jinja comment block.

        This method searches Jinja comment blocks in the template for a YAML snippet
        containing an `mcp_doc` field. If found, it parses the comment content as
        YAML and returns the string value of `mcp_doc`. This allows templates to
        embed their own user-facing documentation, which can then be exposed as the
        docstring for dynamically registered MCP tools.

        Expected template comment format:

            {#-
            mcp_doc: |
            Description of what this template-backed tool does.
            Additional usage notes can go here.
            -#}

        Args:
            template_text: Raw text contents of a Jinja template.

        Returns:
            Optional[str]:
                The extracted MCP documentation string if a valid `mcp_doc` field
                is found and contains non-empty text, otherwise `None`.

        Raises:
            TemplateContextError: If a comment block containing `mcp_doc:` is found
                but the block cannot be parsed as valid YAML.
        """
        for match in re.finditer(r"{#-?\s*(.*?)\s*-?#}", template_text, flags=re.DOTALL):
            block = match.group(1)
            if "mcp_doc:" not in block:
                continue
            try:
                parsed = yaml.safe_load(block) or {}
            except Exception as e:  # noqa: BLE001
                raise TemplateContextError(f"Failed to parse mcp_doc block: {e}")
            if isinstance(parsed, dict):
                doc = parsed.get("mcp_doc")
                if isinstance(doc, str) and doc.strip():
                    return doc.strip()
        return None

    def _render_yaml(self, template_ref: str | Path, context: Dict[str, Any]) -> tuple[str, str]:
        """Render a Jinja YAML template.

        Args:
            template_ref: Template name (relative to this server's template loader) or an
                absolute filesystem path to a template file.
            context: Template render context.

        Returns:
            (rendered_yaml, output_filename)

        Raises:
            OSError: If an absolute template file cannot be read.
            jinja2.TemplateNotFound: If a relative template cannot be found by the loader.
        """
        template_path = template_ref if isinstance(template_ref, Path) else Path(str(template_ref))
        if template_path.is_absolute():
            template_text = template_path.read_text(encoding="utf-8")
            template = self.study_templates_env.from_string(template_text)
            return template.render(**context), template_path.name

        template_name = str(template_ref)
        template = self.study_templates_env.get_template(template_name)
        return template.render(**context), template_name
