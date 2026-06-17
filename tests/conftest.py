# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
This module contains pytest fixtures to be used throughout the entire test suite.
"""

import json
import os
import sys
from pathlib import Path
from typing import Callable, Generator

import pytest
from _pytest.tmpdir import TempPathFactory

TESTS_DIR = Path(__file__).parent
E2E_DIR = TESTS_DIR / "e2e"
INTEGRATION_DIR = TESTS_DIR / "integration"
UNIT_DIR = TESTS_DIR / "unit"


################################
# Custom Pytest Configurations #
################################


def pytest_collection_modifyitems(config, items):
    """
    Modifies pytest items prior to running the tests. In our case,
    this is specifically marking tests appropriately.
    """
    # Resolve test directories
    e2e_dir = E2E_DIR.resolve()
    integration_dir = INTEGRATION_DIR.resolve()
    unit_dir = UNIT_DIR.resolve()

    # Loop through and mark tests appropriately
    for item in items:
        try:
            path = item.path.resolve()
        except Exception:
            continue

        # Mark end-to-end tests
        if e2e_dir in path.parents or path == e2e_dir:
            item.add_marker(pytest.mark.e2e)

        # Mark integration tests
        if integration_dir in path.parents or path == integration_dir:
            item.add_marker(pytest.mark.integration)

        # Mark unit tests
        if unit_dir in path.parents or path == unit_dir:
            item.add_marker(pytest.mark.unit)


def pytest_addoption(parser):
    """
    Add custom command-line options to pytest.

    Args:
        parser: The pytest command-line option parser.
    """
    parser.addoption(
        "--include-allocation-required",
        action="store_true",
        default=False,
        help="Run tests marked with 'allocation_required'.",
    )


def pytest_runtest_setup(item):
    """
    Perform setup checks before running a test.

    This hook checks for the presence of required environment variables for tests
    marked with `@pytest.mark.requires_env`. If any required environment variables
    are missing, the test is skipped.

    Args:
        item: The pytest test item being set up.
    """
    requires_env_mark = item.get_closest_marker("requires_env")
    if requires_env_mark:
        # marker can be used as @pytest.mark.requires_env("VAR")
        # or @pytest.mark.requires_env("VAR", "OTHER_VAR")
        env_vars = requires_env_mark.args
        missing = [var for var in env_vars if os.getenv(var) is None]

        if missing:
            pytest.skip(f"Skipping {item.name} because required env var(s) not set: {', '.join(missing)}")


###################
# Global Fixtures #
###################


@pytest.fixture(scope="session")
def create_testing_dir() -> Callable:
    """
    Fixture to create a temporary testing directory.

    Returns:
        A function that creates the testing directory.
    """

    def _create_testing_dir(base_dir: str, sub_dir: str) -> Path:
        """
        Helper function to create a temporary testing directory.

        Args:
            base_dir:
                The base directory where the testing directory will be created.
            sub_dir:
                The name of the subdirectory to create.

        Returns:
            The path to the created testing directory.
        """
        testing_dir = Path(base_dir) / sub_dir
        testing_dir.mkdir(parents=True, exist_ok=True)
        return testing_dir

    return _create_testing_dir


@pytest.fixture(scope="session")
def temp_output_dir(tmp_path_factory: TempPathFactory) -> Generator[str, None, None]:
    """
    This fixture will create a temporary directory to store output files of integration tests.
    The temporary directory will be stored at /tmp/`whoami`/pytest-of-`whoami`/. There can be at most
    3 temp directories in this location so upon the 4th test run, the 1st temp directory will be removed.

    Args:
        tmp_path_factory:
            A built in factory with pytest to help create temp paths for testing

    Yields:
        The path to the temp output directory we'll use for this test run
    """
    # Log the cwd, then create and move into the temporary one
    cwd = os.getcwd()
    temp_integration_outfile_dir = tmp_path_factory.mktemp(
        f"python_{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}_"
    )
    os.chdir(temp_integration_outfile_dir)

    yield temp_integration_outfile_dir

    # Move back to the directory we started at
    os.chdir(cwd)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    """
    Provide an isolated state file path for integration tests.

    Args:
        tmp_path (Path): Built-in pytest temporary directory fixture.

    Returns:
        Path: Path to a test-local state file.
    """
    return tmp_path / "server_state.json"


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """
    Provide a sample server configuration file.

    Args:
        tmp_path (Path): Built-in pytest temporary directory fixture.

    Returns:
        Path: Path to the generated JSON config file.
    """
    config = {
        "servers": {
            "alpha": {
                "host": "127.0.0.1",
                "port": 8001,
                "env_vars": {"MODE": "test"},
                "log_file": str(tmp_path / "logs" / "alpha.log"),
            },
            "beta": {
                "host": "localhost",
                "port": 8002,
                "env_vars": {"DEBUG": "1"},
                "log_file": str(tmp_path / "logs" / "beta.log"),
            },
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path
