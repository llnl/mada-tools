# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The base class for sample generation.

Subclasses should implement the `generate` method.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np

from .....shared.base_kwargs_handler import BaseKwargsHandler


class BaseSampleGenerator(BaseKwargsHandler, ABC):
    """
    Base class for sample generator components.

    Attributes:
        settings_class: The settings class for this output handler.
        supported_kwargs: The full set of supported keyword arguments for the `write` method.
        required_kwargs: The set of required keyword arguments for the `write` method.

    Methods:
        find_missing_required_kwargs: Validates that all required keyword arguments are present.
        build_settings_from_kwargs: Validates the keyword arguments and builds the settings object.
        generate: Generate a list of samples from the provided data.
    """

    @abstractmethod
    def generate(self, **kwargs: Dict[str, Any]) -> np.ndarray:
        """
        Generate a list of samples from the provided data.

        Args:
            **kwargs: Keyword arguments for sample generation. This will vary by implementation.
                We use kwargs as each sampling method may require different parameters.

        Returns:
            A numpy array of generated samples.
        """
