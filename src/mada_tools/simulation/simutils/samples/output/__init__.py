# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The output package provides functionality for writing samples to files.

This is designed to be easily extended with additional output strategies.

Modules:
    base_output_handler: Defines the base class for output handling.
    csv_output_handler: Provides a concrete implementation for writing CSV files.
    folder_output_handler: Provides a concrete implementation for writing to folders.
    output_handler_factory: Provides a factory class for creating output handlers.
"""
