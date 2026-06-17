# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Utility functions for configuring application wide logging.
"""

import logging
import sys

# Map string levels to logging constants
LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def setup_logging(
    level: str = "INFO",
    log_to_stdout: bool = True,
    log_file: str | None = None,
):
    """
    Configure root logger for the entire application.

    Called once when argparse is loaded up. Other modules
    should just use logging.getLogger(__name__).

    Args:
        level (str): Log level name, for example: "DEBUG",
            "INFO", "WARNING".
        log_to_stdout (bool): If True, log to stdout.
        log_file (str | None): If given, also log to this file.
    """
    # Convert level string to numeric value
    level_upper = level.upper()
    numeric_level = LEVEL_MAP.get(level_upper, logging.INFO)

    # Remove any existing handlers if reconfiguring
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_to_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(numeric_level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def set_log_level(level: str):
    f"""
    Change log level globally at runtime.

    Args:
        level (str): A string indicating what level to set
            the logger to. Choices are {LEVEL_MAP.keys()}.

    Example:
        set_log_level("DEBUG")
    """
    level_upper = level.upper()
    numeric_level = LEVEL_MAP.get(level_upper)
    if numeric_level is None:
        raise ValueError(f"Invalid log level: {level}")
    logging.getLogger().setLevel(numeric_level)

    # Also update all existing handlers
    for handler in logging.getLogger().handlers:
        handler.setLevel(numeric_level)
