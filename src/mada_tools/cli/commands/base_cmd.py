# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Defines the abstract base class for all CLI commands.

This module provides the `BaseCmd` abstract base class that all command
implementations must inherit from. It standardizes the interface for
adding command-specific argument parsers and processing CLI command logic.
"""

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace


class BaseCmd(ABC):
    """
    Abstract base class for a CLI commands.

    Methods:
        add_parser: Adds the parser for a specific command to the main `ArgumentParser`.
        process_command: Executes the logic for this CLI command.
    """

    @abstractmethod
    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        raise NotImplementedError("Subclasses of `CommandEntryPoint` must implement an `add_parser` method.")

    @abstractmethod
    def process_command(self, args: Namespace):
        """
        Execute the logic for this CLI command.

        Args:
            args (Namespace): Parsed CLI arguments from the user.
        """
        raise NotImplementedError("Subclasses of `CommandEntryPoint` must implement an `process_command` method.")
