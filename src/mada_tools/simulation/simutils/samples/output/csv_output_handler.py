# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The CSV output handler.

This module defines the `CSVOutputHandler` class, which is responsible for
writing samples to a CSV file. It's used by the Merlin job manager.
"""

import csv
from dataclasses import dataclass
from typing import Dict, Set

import numpy as np

from .....shared.base_settings import BaseSettings
from ...models import SampleOutputResult
from ...samples.output.base_output_handler import BaseOutputHandler


@dataclass
class CSVOutputSettings(BaseSettings):
    """
    A class to encapsulate the settings for how to output samples to a csv file.

    This class is implemented to follow the common architecture used throughout the
    sample generation and output handling of the job management system. If more settings
    are needed, they can be added here easily.

    Dataclasses like this help with type checking and setting defaults.

    Attributes:
        output_file (str): CSV file to save all samples (for csv mode).

    Methods:
        validate: Validates the input settings.
        __str__: Returns a string representation of the settings.
        __repr__: Returns a detailed string representation of the settings.
    """

    output_file: str = "samples.csv"

    def validate(self):
        """
        Validates the input settings.
        """
        # Check if output_file is a string
        if not isinstance(self.output_file, str):
            raise TypeError("output_file must be a string")


class CSVOutputHandler(BaseOutputHandler):
    """
    Output handler for writing samples to a CSV file.

    Attributes:
        settings_class: The settings class for this output handler.
        supported_kwargs: The full set of supported keyword arguments for the `write` method.
        required_kwargs: The set of required keyword arguments for the `write` method.

    Methods:
        write: Writes a list of samples to a CSV file.
    """

    def _get_settings_class(self) -> CSVOutputSettings:
        """
        Get the settings class for this output handler.

        Returns:
            The settings class for this output handler.
        """
        return CSVOutputSettings

    def _get_supported_kwargs(self) -> Set[str]:
        """
        Get the set of supported keyword arguments for the `write` method.

        Returns:
            A set of supported keyword argument names for output configuration.
        """
        return {"output_file"}

    def _get_required_kwargs(self) -> Set[str]:
        """
        Get the set of required keyword arguments for the `write` method.

        Returns:
            A set of required keyword argument names for output configuration.
        """
        return {}

    def write(self, samples: np.ndarray, **kwargs: Dict[str, str]) -> SampleOutputResult:
        """
        Writes a list of samples to a CSV file.

        Args:
            samples: The samples to write, where each sample is a list of floats.
            **kwargs: Additional keyword arguments for output configuration. For CSV output, this must include:
                - output_file: The path to the CSV file where samples will be written.

        Returns:
            SampleOutputResult: A result object containing the output path and output type.
        """
        self.check_if_samples_are_empty(samples)

        output_settings = self.build_settings_from_kwargs(kwargs)

        print(f"Writing samples to '{output_settings.output_file}'...")
        with open(output_settings.output_file, "w") as outfile:
            writer = csv.writer(outfile)
            writer.writerows(samples)
        print("Samples written successfully.")

        return SampleOutputResult(output_path=output_settings.output_file, output_type="csv")
