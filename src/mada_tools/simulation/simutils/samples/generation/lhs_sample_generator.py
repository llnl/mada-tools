# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Latin Hypercube Sample (LHS) generator component.
"""

from dataclasses import dataclass
from typing import Dict, List, Set, Union

import numpy as np
from scipy.stats import qmc

from .....shared.base_settings import BaseSettings
from ...samples.generation.base_sample_generator import BaseSampleGenerator


@dataclass
class LHSampleSettings(BaseSettings):
    """
    A class to encapsulate the settings for generating Latin Hypercube samples.

    Attributes:
        dims (int): The number of dimensions (variables).
        n_samples (int): The number of samples to generate.
        lower_bounds (List[float]): The lower bounds for each dimension.
        upper_bounds (List[float]): The upper bounds for each dimension.
    """

    dims: int
    n_samples: int
    lower_bounds: List[Union[float, int]]
    upper_bounds: List[Union[float, int]]

    def validate(self):
        """
        Validates the input parameters.
        """
        if not isinstance(self.dims, int) or self.dims <= 0:
            raise ValueError("Invalid 'dims' value.")

        if not isinstance(self.n_samples, int) or self.n_samples <= 0:
            raise ValueError("Invalid 'n_samples' value.")

        if not self.lower_bounds or not all(isinstance(x, float) or isinstance(x, int) for x in self.lower_bounds):
            raise ValueError("Invalid 'lower_bounds' value.")

        if not self.upper_bounds or not all(isinstance(x, float) or isinstance(x, int) for x in self.upper_bounds):
            raise ValueError("Invalid 'upper_bounds' value.")

        len_lower_bounds = len(self.lower_bounds)
        len_upper_bounds = len(self.upper_bounds)
        if not len_lower_bounds == len_upper_bounds == self.dims:
            raise ValueError(
                f"Length of lower bounds ({len_lower_bounds}) and upper bounds "
                f"({len_upper_bounds}) must both match number of dimensions ({self.dims})"
            )


class LHSampleGenerator(BaseSampleGenerator):
    """
    Latin Hypercube Sample generator component.

    Attributes:
        settings_class: The settings class for this output handler.
        supported_kwargs: The full set of supported keyword arguments for the `write` method.
        required_kwargs: The set of required keyword arguments for the `write` method.

    Methods:
        find_missing_required_kwargs: Validates that all required keyword arguments are present.
        build_settings_from_kwargs: Validates the keyword arguments and builds the settings object.
        generate: Generate a list of samples from the provided data.
    """

    def _get_settings_class(self) -> LHSampleSettings:
        """
        Get the settings class for this sample generator.

        Returns:
            The settings class for this sample generator.
        """
        return LHSampleSettings

    def _get_supported_kwargs(self):
        """
        Get the full set of supported keyword arguments for the `generate` method.

        Returns:
            A set of supported keyword argument names.
        """
        return {"dims", "n_samples", "lower_bounds", "upper_bounds"}

    def _get_required_kwargs(self) -> Set[str]:
        """
        Get the set of required keyword arguments for the `generate` method.

        Returns:
            A set of required keyword argument names for sample generation.
        """
        return {"dims", "n_samples", "lower_bounds", "upper_bounds"}

    def generate(self, **kwargs: Dict[str, int | List[float]]) -> np.ndarray:
        """
        Generate a list of samples from the provided data.

        This method will convert the keyword arguments into a `LHSampleSettings` object
        for validation and logging purposes. It will then use these settings to generate
        samples using the Latin Hypercube Sampling method.

        Args:
            **kwargs: Keyword arguments for sample generation. For LHS sampling, this must include:
                - dims: int, number of dimensions
                - n_samples: int, number of samples to generate
                - lower_bounds: List[float], lower bounds for each dimension
                - upper_bounds: List[float], upper bounds for each dimension

        Returns:
            A numpy array of generated samples.
        """
        print("Generating samples...")

        sample_settings = self.build_settings_from_kwargs(kwargs)

        lower = np.asarray(sample_settings.lower_bounds, dtype=float)
        upper = np.asarray(sample_settings.upper_bounds, dtype=float)

        varying_mask = lower < upper
        fixed_mask = lower == upper

        result = np.empty((sample_settings.n_samples, sample_settings.dims), dtype=float)

        if np.any(varying_mask):
            lhs = qmc.LatinHypercube(d=int(np.sum(varying_mask)))
            samples = lhs.random(n=sample_settings.n_samples)

            scaled = qmc.scale(
                samples,
                l_bounds=lower[varying_mask],
                u_bounds=upper[varying_mask],
            )

            result[:, varying_mask] = scaled

        if np.any(fixed_mask):
            result[:, fixed_mask] = lower[fixed_mask]

        print("Samples generated successfully!\n")
        return result
