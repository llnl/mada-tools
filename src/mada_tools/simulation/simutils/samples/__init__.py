# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
This package defines the functionality for generating samples and writing them to files.

Each sub-package here follows the following architecture:

    - A base class for defining the sample generation and writing process.
    - Concrete implementations of the base class for specific sample and output types.
    - A factory class for creating instances of the sample generators and output handlers.

Packages:
    generation: Provides functionality for generating samples.
    output: Provides functionality for writing samples to files.
"""
