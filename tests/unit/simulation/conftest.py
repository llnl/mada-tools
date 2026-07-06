"""
Fixtures for files in `tests/unit/simulation/`.
"""

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture(scope="session")
def simulation_testing_dir(create_testing_dir: Callable, temp_output_dir: str) -> Path:
    """
    Fixture to create a temporary output directory for tests related to testing the
    `simulation` directory.

    Args:
        create_testing_dir: A fixture which returns a function that creates the testing directory.
        temp_output_dir: The path to the temporary output directory we'll be using for this test run.

    Returns:
        The path to the temporary testing directory for tests of files in the `simulation` directory.
    """
    return create_testing_dir(temp_output_dir, "unit_test_simulation")
