# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Factory for output handlers (simplified version).

This provides a simple factory for instantiating output handlers.
"""

from .base_output_handler import BaseOutputHandler
from .csv_output_handler import CSVOutputHandler
from .folder_output_handler import FolderOutputHandler


class OutputHandlerFactory:
    """
    Simple factory for output handlers.
    """

    _handlers = {
        "csv": CSVOutputHandler,
        "folder": FolderOutputHandler,
        "directory": FolderOutputHandler,
        "dir": FolderOutputHandler,
    }

    @classmethod
    def create(cls, handler_type: str) -> BaseOutputHandler:
        """
        Create an output handler by type.

        Args:
            handler_type: Type of handler ("csv", "folder", "directory", "dir")

        Returns:
            Instance of the requested handler

        Raises:
            ValueError: If handler type is not supported
        """
        if handler_type not in cls._handlers:
            raise ValueError(f"Unknown handler type: {handler_type}")

        return cls._handlers[handler_type]()
