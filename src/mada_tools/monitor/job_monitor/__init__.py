# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Job monitor subpackage.
Provides log utilities, failure pattern detection, and the JobMonitorServer.

Modules:
    failure_patterns: Defines known failure signatures and maps them to structured classifications.
    log_utils: Utilities for reading logs, extracting tails, combining multiple logs, and classifying failures.
    server: Implements the JobMonitorServer MCP interface and exposes summarize_status and related tools.
"""

from .failure_patterns import FAILURE_PATTERNS, UNCLASSIFIED_FAILURE
from .log_utils import classify_failure, combine_logs, read_log, tail_log
from .server import JobMonitorServer

__all__ = [
    "JobMonitorServer",
    "tail_log",
    "classify_failure",
    "read_log",
    "combine_logs",
    "FAILURE_PATTERNS",
    "UNCLASSIFIED_FAILURE",
]
