# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Environment-variable helpers shared throughout the codebase."""

import os
from typing import Optional


def get_env_var(var_name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Get an environment variable with optional default and required validation.

    Args:
        var_name: Name of the environment variable to read.
        default: Default value to return when the variable is not set.
        required: Whether the variable must resolve to a non-None value.

    Returns:
        The resolved environment variable value, or `default` when the variable
        is not set.

    Raises:
        ValueError: If `required` is True and the resolved value is None.
    """
    value = os.getenv(var_name, default)
    if required and value is None:
        raise ValueError(f"Required environment variable {var_name} is not set")
    return value
