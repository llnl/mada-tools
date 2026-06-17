# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Utility functions for job management.

This module provides helper functions to interact with job-related files and data structures.
"""

import json
import os
from typing import List

from .models import RunInstance


def get_run_instances(run_instances_json_path: str) -> List[RunInstance]:
    """
    Reads the run_instances.json file from the specified study directory and
    converts it into a list of RunInstance objects.

    Args:
        run_instances_json_path: The path to the run_instances.json file.

    Returns:
        A list of RunInstance objects.
    """
    print(f"Attempting to retrieve run instances from '{run_instances_json_path}'...")

    # Check if the file exists
    if not os.path.exists(run_instances_json_path):
        print(f"ERROR: The file containing run instances does not exist: '{run_instances_json_path}'.")
        print("Did you run the sample generation script yet?")
        return []

    # Read the JSON file and convert it into RunInstance objects
    with open(run_instances_json_path, "r") as json_file:
        try:
            run_instances_data = json.load(json_file)  # Load the JSON data as a list of dictionaries
            run_instances = []
            for data in run_instances_data:
                run_instance = RunInstance(run_location=data["run_location"], id=data["id"])
                # Set command and args if present
                if "command" in data:
                    run_instance.command = data["command"]
                if "args" in data:
                    run_instance.args = data["args"]
                run_instances.append(run_instance)
            print("Successfully retrieved run instances.")
            return run_instances
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON file: {run_instances_json_path}.")
            print(f"Details: {e}")
            return []
        except KeyError as e:
            print(f"ERROR: Missing expected key in JSON data: {e}")
            return []
