# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Helper class for Job Monitor MCP tools.

This module contains the non-MCP business logic used by `JobMonitorServer` so
the server can delegate execution through `BaseMCPServer.run_tool()` while
keeping the tool-registration layer thin.
"""

import json
import os
from typing import Optional

from mada_tools.monitor.job_monitor.log_utils import classify_failure, tail_log


class JobMonitorHelper:
    """Encapsulate Job Monitor tool implementations behind the run_tool contract.

    Attributes:
        tail_bytes: Maximum number of bytes to read from the end of each log
            file.
        status_depth: Optional future-facing status-history depth setting stored
            alongside the helper configuration.

    Methods:
        read_logs: Read tailed stdout and stderr content for a job run.
        summarize_status: Build a structured status payload with failure
            classification data.
    """

    def __init__(self, tail_bytes: int = 50000, status_depth: Optional[int] = None):
        """Initialize the helper with log-tail configuration.

        Args:
            tail_bytes: Maximum number of bytes to read from the end of each
                log file.
            status_depth: Optional status-history depth value retained for
                compatibility with server-level configuration.
        """
        self.tail_bytes = tail_bytes
        self.status_depth = status_depth

    def read_logs(self, run_location: str, stdout_file: str, stderr_file: str) -> tuple[bool, str]:
        """Return tailed stdout and stderr logs for a job.

        Args:
            run_location: Path to the directory containing the log files.
            stdout_file: Name of the stdout log file.
            stderr_file: Name of the stderr log file.

        Returns:
            A `(success, payload)` tuple where `success` is always `True` and
            `payload` is a JSON string containing `stdout` and `stderr` log
            tails.
        """
        out_path = os.path.join(run_location, stdout_file)
        err_path = os.path.join(run_location, stderr_file)

        result = {
            "stdout": tail_log(out_path, self.tail_bytes),
            "stderr": tail_log(err_path, self.tail_bytes),
        }
        return True, json.dumps(result, indent=2)

    def summarize_status(
        self,
        run_location: str,
        stdout_file: str,
        stderr_file: str,
        exit_code: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Return a structured status summary including failure classification.

        Args:
            run_location: Path to the directory containing the log files.
            stdout_file: Name of the stdout log file.
            stderr_file: Name of the stderr log file.
            exit_code: Optional scheduler or application exit code to include in
                the returned summary.

        Returns:
            A `(success, payload)` tuple where `success` is always `True` and
            `payload` is a JSON string containing the exit code, tailed logs,
            and detected failure classifications.
        """
        out_path = os.path.join(run_location, stdout_file)
        err_path = os.path.join(run_location, stderr_file)

        out_text = tail_log(out_path, self.tail_bytes)
        err_text = tail_log(err_path, self.tail_bytes)
        combined = out_text + "\n" + err_text

        findings = classify_failure(combined, self.tail_bytes)

        summary = {
            "exit_code": exit_code,
            "stdout_tail": out_text,
            "stderr_tail": err_text,
            "detected_failures": findings,
        }

        return True, json.dumps(summary, indent=2)
