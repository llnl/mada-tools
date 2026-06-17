# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for files in this `server_management/` test directory.
"""

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture(scope="session")
def server_management_testing_dir(create_testing_dir: Callable, temp_output_dir: str) -> Path:
    """
    Fixture to create a temporary output directory for tests related to testing the
    `server_management` directory.

    Args:
        create_testing_dir: A fixture which returns a function that creates the testing directory.
        temp_output_dir: The path to the temporary ouptut directory we'll be using for this test run.

    Returns:
        The path to the temporary testing directory for tests of files in the `server_management` directory.
    """
    return create_testing_dir(temp_output_dir, "server_management_testing")
