# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Utility functions for reading, tailing, combining, and classifying job logs.

This module is used by the JobMonitorServer to extract stdout and stderr content
and to classify failures using regex-based patterns defined in failure_patterns.py.

Functions:
    read_log: Read the full text of a log file.
    tail_log: Return the last N bytes of a log file.
    combine_logs: Combine the tails of multiple logs into a single text blob.
    classify_failure: Apply regex-based failure detection to log content.
"""

import os
import re
from typing import Any, Dict, List

from .failure_patterns import FAILURE_PATTERNS, UNCLASSIFIED_FAILURE


def read_log(path: str) -> str:
    """
    Read the full contents of a log file.

    If the file cannot be opened or read, the function returns an empty string.

    Args:
        path (str): Path to the log file to read.

    Returns:
        str: Full contents of the log file, or an empty string if the file is missing
        or unreadable.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def tail_log(path: str, bytes_to_read: int) -> str:
    """
    Return the last `bytes_to_read` bytes of a log file.

    Handles missing or unreadable files by returning an empty string.

    Args:
        path (str): Path to the log file.
        bytes_to_read (int): Number of bytes from the end of the file to return.

    Returns:
        str: The requested tail of the log file decoded as UTF-8, or an empty string
        if the file is missing or cannot be read.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - bytes_to_read))
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def combine_logs(paths: List[str], tail_bytes: int) -> str:
    """
    Combine multiple logs into a single formatted text block.

    Each log file is tailed up to `tail_bytes`, then wrapped with a header naming
    the file. Missing files are included but reported with empty content.

    Args:
        paths (List[str]): Paths to log files.
        tail_bytes (int): Number of bytes to read from the end of each file.

    Returns:
        str: Combined and formatted log text for all paths.
    """
    logs = []
    for p in paths:
        logs.append(f"===== {os.path.basename(p)} =====\n")
        logs.append(tail_log(p, tail_bytes))
        logs.append("\n")
    return "".join(logs)


def classify_failure(log_text: str, tail_bytes: int = 50000) -> List[Dict[str, Any]]:
    """
    Classify failures in log data using regex-based patterns.

    The function scans the provided log text for known error signatures defined
    in FAILURE_PATTERNS. If one or more patterns match, a list of findings is
    returned. Each finding includes the failure type, matched text, and a
    recommended action.

    If no patterns match and the logs contain suspicious content (non-empty),
    an UNCLASSIFIED_FAILURE entry is returned.

    If no patterns match and logs are empty or clean, the function returns an
    empty list, indicating a successful run.

    Args:
        log_text (str): Complete or combined log content to analyze.
        tail_bytes (int): Maximum size of the excerpt included for unclassified
            failures.

    Returns:
        List[Dict[str, Any]]: A non-empty list of failure findings. Each finding
        includes keys such as:
            - failure_type (str)
            - matched_text (str or None)
            - recommendation (str)
            - log_excerpt (str) for unclassified failures
    """
    findings = []

    # Search for all known patterns
    for name, cfg in FAILURE_PATTERNS.items():
        pattern = cfg["pattern"]
        match = re.search(pattern, log_text, re.IGNORECASE)
        if match:
            findings.append(
                {
                    "failure_type": name,
                    "matched_text": match.group(0),
                    "recommendation": cfg["recommendation"],
                }
            )

    # Fallback case
    if not findings:
        # Detect if the log contains any generic failure signals
        generic_failure_signals = ["error", "exception", "fail", "killed", "abort"]
        text_lower = log_text.lower() if log_text else ""
        has_failure_signals = any(sig in text_lower for sig in generic_failure_signals)

        # Case 3: No failures → successful run → return empty list
        if not has_failure_signals:
            return []

        # Case 2: Failure occurred but does not match known patterns
        excerpt = log_text[-tail_bytes:] if log_text else ""
        findings.append({**UNCLASSIFIED_FAILURE, "matched_text": None, "log_excerpt": excerpt})

    return findings
