# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for files in this `cli/` test directory.
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Callable

import pytest

from mada_tools.cli.commands.base_cmd import BaseCmd


@pytest.fixture(scope="session")
def cli_testing_dir(create_testing_dir: Callable, temp_output_dir: str) -> Path:
    """
    Fixture to create a temporary output directory for tests related to testing the
    `cli` directory.

    Args:
        create_testing_dir: A fixture which returns a function that creates the testing directory.
        temp_output_dir: The path to the temporary ouptut directory we'll be using for this test run.

    Returns:
        The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    return create_testing_dir(temp_output_dir, "cli_testing")


@pytest.fixture
def create_parser() -> Callable:
    """
    A fixture to help create a parser for any command.

    Returns:
        A function that creates a parser.
    """

    def _create_parser(cmd: BaseCmd) -> ArgumentParser:
        """
        Returns an `ArgumentParser` configured with the `cmd` command and its subcommands.

        Returns:
            Parser with the `cmd` command and its subcommands registered.
        """
        parser = ArgumentParser()
        subparsers = parser.add_subparsers(dest="main_command")
        cmd.add_parser(subparsers)
        return parser

    return _create_parser
