# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The folder output handler.

This module defines the `FolderOutputHandler` class, which is responsible for
writing samples to a folder structure. It's used by the Flux and Slurm job managers.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Set

import numpy as np
import pandas as pd

from .....shared.base_settings import BaseSettings
from ...models import RunInstance, SampleOutputResult
from ...samples.output.base_output_handler import BaseOutputHandler


@dataclass
class FolderOutputSettings(BaseSettings):
    """
    A class to encapsulate the settings for how to output samples to a directory structure.

    This class is implemented to follow the common architecture used throughout the
    sample generation and output handling of the job management system. If more settings
    are needed, they can be added here easily.

    Dataclasses like this help with type checking and setting defaults.

    Attributes:
        output_dir (str): Directory where samples will be saved (for folder mode).
        param_file (str): File name for each parameter set (for folder mode).

    Methods:
        validate: Validates the input settings.
        __str__: Returns a string representation of the settings.
        __repr__: Returns a detailed string representation of the settings.
    """

    output_dir: str = os.path.join(os.getcwd(), f"fourier_perturbations_{time.strftime('%Y%m%d-%H%M%S')}")
    param_file: str = "params.txt"

    def validate(self):
        """
        Validates the input settings.
        """
        if not isinstance(self.output_dir, str):
            raise TypeError("output_dir must be a string")

        if not isinstance(self.param_file, str):
            raise TypeError("param_file must be a string")


class FolderOutputHandler(BaseOutputHandler):
    """
    Output handler for writing samples to a folder.

    Attributes:
        settings_class: The settings class for this output handler.
        supported_kwargs: The full set of supported keyword arguments for the `write` method.
        required_kwargs: The set of required keyword arguments for the `write` method.

    Methods:
        write: Writes samples to a folder structure.
    """

    def _get_settings_class(self) -> FolderOutputSettings:
        """
        Get the settings class for this output handler.

        Returns:
            The settings class for this output handler.
        """
        return FolderOutputSettings

    def _get_supported_kwargs(self) -> Set[str]:
        """
        Get the set of supported keyword arguments for the `write` method.

        Returns:
            A set of supported keyword argument names for output configuration.
        """
        return {"output_dir", "param_file"}

    def _get_required_kwargs(self) -> Set[str]:
        """
        Get the set of required keyword arguments for the `write` method.

        Returns:
            A set of required keyword argument names for output configuration.
        """
        return {}

    def write(
        self,
        samples: np.ndarray,
        parameter_names: List[str] | None = None,
        **kwargs: Dict[str, Any],
    ) -> SampleOutputResult:
        """
        Creates a folder structure for each sample, writes the parameters to individual files,
        and dumps all `RunInstances` to a JSON file.

        Args:
            samples: A list of samples, where each sample is a list of floats.
            parameter_names: List of parameter names.
            **kwargs: Additional keyword arguments for output configuration.

        Returns:
            A `SampleOutputResult` object containing the output path, output type, and run instances.
        """
        self.check_if_samples_are_empty(samples)

        output_settings = self.build_settings_from_kwargs(kwargs)

        print(f"Creating folder structure in '{output_settings.output_dir}'...")

        # Ensure the base output directory exists
        if not os.path.exists(output_settings.output_dir):
            os.makedirs(output_settings.output_dir)
            print(f"Created base output directory: {output_settings.output_dir}")
        else:
            print(f"Base output directory already exists: {output_settings.output_dir}")

        # Create subdirectories and RunInstance objects for each sample
        padding = len(str(len(samples)))  # Determine padding for folder names (e.g., run001)
        run_instances = []  # List to store all RunInstance objects

        if parameter_names is not None:
            # Build DataFrame
            run_ids = [str(i).zfill(padding) for i in range(len(samples))]
            df = pd.DataFrame(samples, columns=parameter_names)
            df.insert(0, "run#", run_ids)

            # Save CSV
            csv_path = os.path.join(output_settings.output_dir, "run_parameters.csv")
            df.to_csv(csv_path, index=False)
            print(f"Saved run parameter summary CSV: {csv_path}\n")

        for i, sample in enumerate(samples):
            # Create a subdirectory for the sample
            sample_dir = os.path.join(output_settings.output_dir, f"run{str(i).zfill(padding)}")
            os.makedirs(sample_dir, exist_ok=True)

            # Write the sample parameters to the specified file
            param_file_path = os.path.join(sample_dir, output_settings.param_file)
            with open(param_file_path, "w") as param_file:
                if parameter_names is not None:
                    param_file.write("\n".join(f"{name}: {value}" for name, value in zip(parameter_names, sample)))
                else:
                    param_file.write("\n".join(map(str, sample)))

            # Create a RunInstance object
            run_id = str(i).zfill(padding)
            run_instance = RunInstance(run_location=sample_dir, id=run_id)
            run_instances.append(run_instance)

            print(f"Created folder: {sample_dir}")
            print(f"\tWritten parameters to: {param_file_path}")
            print(f"\tRunInstance created: {run_instance}")

        # Dump all RunInstances to a JSON file in case they need to be loaded later
        run_instances_json_path = os.path.join(output_settings.output_dir, "run_instances.json")
        with open(run_instances_json_path, "w") as json_file:
            json.dump([run.to_dict() for run in run_instances], json_file, indent=4)

        print(f"RunInstances dumped to JSON file: {run_instances_json_path}")
        print("Folder structure created successfully.")

        return SampleOutputResult(
            output_path=output_settings.output_dir,
            output_type="folders",
            run_instances=run_instances,
        )
