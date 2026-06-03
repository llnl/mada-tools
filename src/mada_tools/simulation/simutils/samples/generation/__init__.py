# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The generation package provides functionality for generating samples.

This is designed to be easily extended with additional sample generation strategies.

Modules:
    base_sample_generator: Defines the base class for sample generation.
    lhs_sample_generator: Provides a concrete implementation for generating LHS samples.
    parameter_samples_generator: Provides structured mixed parameter sample generation.
    sample_generator_factory: Provides a factory class for creating sample generators.
"""

from .parameter_samples_generator import (
    ParameterSampleGenerator,
    ParameterSampleResult,
    ParameterSpec,
    create_sampling_rngs,
    normalize_cli_value,
)

__all__ = [
    "ParameterSampleGenerator",
    "ParameterSampleResult",
    "ParameterSpec",
    "create_sampling_rngs",
    "normalize_cli_value",
]
