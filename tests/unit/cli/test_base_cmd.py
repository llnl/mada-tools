# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `base_cmd.py` file.
"""

from argparse import ArgumentParser, Namespace

import pytest

from mada_tools.cli.commands.base_cmd import BaseCmd


def test_cannot_instantiate_abstract_class():
    """Ensure instantiating `BaseCmd` directly raises TypeError."""
    with pytest.raises(TypeError):
        BaseCmd()


def test_concrete_subclass_must_implement_add_parser_and_process_command():
    """Ensure subclass missing methods raises TypeError."""

    # Only implements add_parser
    class IncompleteCommand(BaseCmd):
        def add_parser(self, subparsers: ArgumentParser):
            pass

    with pytest.raises(TypeError):
        IncompleteCommand()


def test_concrete_subclass_runs_successfully():
    """Test that a fully implemented subclass works as expected."""

    class DummyCommand(BaseCmd):
        def __init__(self):
            self.called_add = False
            self.called_process = False

        def add_parser(self, subparsers: ArgumentParser):
            self.called_add = True

        def process_command(self, args: Namespace):
            self.called_process = True

    dummy = DummyCommand()

    # Add parser should run
    dummy.add_parser(ArgumentParser())
    assert dummy.called_add is True

    # Process command should run
    dummy.process_command(Namespace())
    assert dummy.called_process is True
