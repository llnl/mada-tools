# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the ``plugin-docs`` CLI command group."""

from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest

from mada_tools.cli.commands.plugin_docs import PluginDocsCmd


@pytest.fixture
def plugin_docs_cmd() -> PluginDocsCmd:
    """Return a ``PluginDocsCmd`` instance for CLI tests."""
    return PluginDocsCmd()


def test_add_parser_registers_grouped_subcommands(create_parser: Callable, plugin_docs_cmd: PluginDocsCmd):
    """Verify that the ``plugin-docs`` command group parses subcommands."""
    parser = create_parser(plugin_docs_cmd)

    args = parser.parse_args(["plugin-docs", "prepare", "--config", "docs/plugin_docs.yaml"])

    assert args.main_command == "plugin-docs"
    assert args.plugin_docs_command == "prepare"
    assert args.config == "docs/plugin_docs.yaml"
    assert hasattr(args, "func")
    assert callable(args.func)


def test_add_parser_forwards_trailing_mkdocs_args(create_parser: Callable, plugin_docs_cmd: PluginDocsCmd):
    """Verify build/serve can capture arguments intended for MkDocs."""
    parser = create_parser(plugin_docs_cmd)

    args = parser.parse_args(["plugin-docs", "build", "--config", "docs/plugin_docs.yaml", "--", "--strict"])

    assert args.plugin_docs_command == "build"
    assert args.mkdocs_args == ["--", "--strict"]


@pytest.mark.parametrize(
    ("command", "helper_name"),
    [
        ("prepare", "prepare_plugin_docs_site"),
        ("build", "build_plugin_docs"),
        ("serve", "serve_plugin_docs"),
        ("clean", "clean_plugin_docs"),
    ],
)
def test_process_command_delegates_to_docs_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    helper_name: str,
):
    """Each grouped subcommand should call the matching docs helper."""
    config_path = tmp_path / "docs" / "plugin_docs.yaml"
    calls = []

    import mada_tools.cli.commands.plugin_docs as plugin_docs_mod

    def fake_helper(path, *mkdocs_args):
        calls.append((path, mkdocs_args))
        return tmp_path / ".generated_docs"

    monkeypatch.setattr(plugin_docs_mod, helper_name, fake_helper)

    PluginDocsCmd().process_command(Namespace(plugin_docs_command=command, config=config_path, mkdocs_args=[]))

    assert calls == [(config_path, ())]


def test_process_command_delegates_mkdocs_args_without_separator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Build and serve should pass trailing MkDocs args through to docs helpers."""
    config_path = tmp_path / "docs" / "plugin_docs.yaml"
    calls = []

    import mada_tools.cli.commands.plugin_docs as plugin_docs_mod

    monkeypatch.setattr(
        plugin_docs_mod,
        "build_plugin_docs",
        lambda path, *mkdocs_args: calls.append((path, mkdocs_args)),
    )

    PluginDocsCmd().process_command(
        Namespace(plugin_docs_command="build", config=config_path, mkdocs_args=["--", "--strict"])
    )

    assert calls == [(config_path, ("--strict",))]
