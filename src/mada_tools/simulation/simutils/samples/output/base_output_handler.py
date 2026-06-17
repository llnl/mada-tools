# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Base class for output handler components.

Subclasses should implement the `write` method.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np

from .....shared.base_kwargs_handler import BaseKwargsHandler
from ...models import SampleOutputResult


class BaseOutputHandler(BaseKwargsHandler, ABC):
    """
    Base class for output handler components.

    Attributes:
        settings_class: The settings class for this output handler.
        supported_kwargs: The full set of supported keyword arguments for the `write` method.
        required_kwargs: The set of required keyword arguments for the `write` method.

    Methods:
        check_if_samples_are_empty: Checks if the given samples array is empty.
        find_missing_required_kwargs: Validates that all required keyword arguments are present.
        build_settings_from_kwargs: Validates the keyword arguments and builds the settings object.
        write: Write the generated samples to a file or other storage.
    """

    def check_if_samples_are_empty(self, samples: np.ndarray):
        """
        Checks if the given samples array is empty.

        Raises:
            ValueError: If samples have not been generated yet.
        """
        if samples is None or len(samples) == 0:
            raise ValueError("The provided samples list cannot be empty.")

    @abstractmethod
    def write(self, samples: np.ndarray, **kwargs: Dict[str, Any]) -> SampleOutputResult:
        """
        Write the generated samples to a file or other storage.

        Args:
            samples: The generated samples.
            **kwargs: Additional keyword arguments for output configuration. This will vary by implementation.
                We use kwargs as each output handler may require different parameters.

        Returns:
            A SampleOutputResult object containing the output path, output type, and run instances.
        """
