# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the ``export-docs`` CLI command."""

from typing import Callable

import pytest

from mada_tools.cli.commands.export_docs import ExportDocsCmd


@pytest.fixture
def export_docs_cmd() -> ExportDocsCmd:
    """Return an ``ExportDocsCmd`` instance for CLI tests."""
    return ExportDocsCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, export_docs_cmd: ExportDocsCmd):
    """Verify that the ``export-docs`` subcommand is registered correctly."""
    parser = create_parser(export_docs_cmd)

    args = parser.parse_args(["export-docs", "docs-out"])

    assert args.main_command == "export-docs"
    assert args.destination == "docs-out"
    assert hasattr(args, "func")
    assert callable(args.func)


def test_process_command_exports_docs(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
    """Verify that the command delegates to the docs exporter and reports the output path."""
    destination = tmp_path / "docs-out"
    exported_path = destination.resolve()
    calls = []

    def fake_export_docs(path):
        calls.append(path)
        return exported_path

    import mada_tools.cli.commands.export_docs as export_docs_mod

    monkeypatch.setattr(export_docs_mod, "export_docs", fake_export_docs)

    ExportDocsCmd().process_command(type("Args", (), {"destination": destination})())

    assert calls == [destination]
    assert str(exported_path) in capsys.readouterr().out
