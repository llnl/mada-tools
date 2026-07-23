# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Environment-variable helpers shared throughout the codebase."""

import os
import re
from typing import Optional


def expand_env_vars(value: str, missing: str = "error", strip_names: bool = True) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` placeholders in a string.

    Args:
        value: String that may contain environment variable placeholders.
        missing: Behavior for missing variables without defaults. ``"error"``
            raises ``ValueError`` and ``"preserve"`` leaves the placeholder
            unchanged.
        strip_names: Whether to strip whitespace around variable names and
            default values inside the placeholder.

    Raises:
        ValueError: If ``missing`` is invalid, or if ``missing="error"`` and a
            required environment variable is unset.
    """
    if missing not in {"error", "preserve"}:
        raise ValueError("missing must be 'error' or 'preserve'")

    def replace_env_var(match: re.Match[str]) -> str:
        var_expr = match.group(1)
        if ":-" in var_expr:
            var_name, default_value = var_expr.split(":-", 1)
            if strip_names:
                var_name = var_name.strip()
                default_value = default_value.strip()
            return os.getenv(var_name, default_value)

        var_name = var_expr.strip() if strip_names else var_expr
        env_value = os.getenv(var_name)
        if env_value is not None:
            return env_value
        if missing == "preserve":
            return match.group(0)
        raise ValueError(f"Environment variable {var_expr} is not set")

    return re.sub(r"\$\{([^}]+)\}", replace_env_var, value)


def get_env_var(var_name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Get an environment variable with optional default and required validation.

    Environment variable resolution is OS dependent; for example, on Windows,
    environment variable names are case-insensitive while on Linux and macOS they
    are case-sensitive. This function does not perform any normalization of the
    variable name.

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
