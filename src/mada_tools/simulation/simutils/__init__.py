# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Job management utilities for simulation servers.

Provides sample generation, output handling, and run management utilities
adapted from mada-job-management jobkit.
"""

from .models import RunInstance, SampleOutputResult
from .samples.generation.lhs_sample_generator import LHSampleGenerator
from .samples.generation.parameter_samples_generator import (
    ParameterSampleGenerator,
    ParameterSampleResult,
    ParameterSpec,
    create_sampling_rngs,
    normalize_cli_value,
)
from .samples.output.folder_output_handler import FolderOutputHandler
from .utils import get_run_instances

__all__ = [
    "RunInstance",
    "SampleOutputResult",
    "LHSampleGenerator",
    "ParameterSampleGenerator",
    "ParameterSampleResult",
    "ParameterSpec",
    "create_sampling_rngs",
    "normalize_cli_value",
    "FolderOutputHandler",
    "get_run_instances",
]
