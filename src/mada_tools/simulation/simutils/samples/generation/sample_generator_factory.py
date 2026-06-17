# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Factory for sample generators (simplified version).

This provides a simple factory for instantiating sample generators.
"""

from .base_sample_generator import BaseSampleGenerator
from .lhs_sample_generator import LHSampleGenerator


class SampleGeneratorFactory:
    """
    Simple factory for sample generators.
    """

    _generators = {"lhs": LHSampleGenerator}

    @classmethod
    def create(cls, generator_type: str) -> BaseSampleGenerator:
        """
        Create a sample generator by type.

        Args:
            generator_type: Type of generator ("lhs")

        Returns:
            Instance of the requested generator

        Raises:
            ValueError: If generator type is not supported
        """
        if generator_type not in cls._generators:
            raise ValueError(f"Unknown generator type: {generator_type}")

        return cls._generators[generator_type]()
