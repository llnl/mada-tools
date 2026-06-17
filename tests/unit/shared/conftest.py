# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for files in this `shared/` test directory.
"""

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture(scope="session")
def shared_testing_dir(create_testing_dir: Callable, temp_output_dir: str) -> Path:
    """
    Fixture to create a temporary output directory for tests related to testing the
    `shared` directory.

    Args:
        create_testing_dir: A fixture which returns a function that creates the testing directory.
        temp_output_dir: The path to the temporary ouptut directory we'll be using for this test run.

    Returns:
        The path to the temporary testing directory for tests of files in the `shared` directory.
    """
    return create_testing_dir(temp_output_dir, "shared_testing")
