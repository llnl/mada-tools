# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Job Monitor MCP Server.

Provides log inspection, failure detection, and structured diagnostics for jobs
executed through the MADA Job Manager. This server exposes tools to read log
files, extract tails, and classify failures using regex-based patterns.
"""

from typing import Optional

from mada_tools.monitor.job_monitor_helper import JobMonitorHelper
from mada_tools.shared.base_server import BaseMCPServer
from mada_tools.shared.env import get_env_var


class JobMonitorServer(BaseMCPServer):
    """
    MCP server that provides tools for job log inspection, failure detection,
    and diagnostic summarization.

    The server exposes tools that read stdout and stderr logs, extract tail
    segments, and classify failures using the regex-based patterns defined in
    the job_monitor.failure_patterns module.

    Attributes:
        tail_bytes (int): Maximum number of bytes to read from the end of each
            log file. Used to avoid sending excessive log content to the client.
            Default is obtained from the MONITOR_LOG_TAIL_BYTES environment
            variable or falls back to 50000.

        status_depth (int): Number of historical status entries to inspect when
            summarizing job state. Default is obtained from the
            MONITOR_DEFAULT_STATUS_DEPTH environment variable or falls back
            to 20.

    Methods:
        summarize_status: Inspect logs, classify failures, and return a
            structured summary suitable for planning or diagnosis.
        read_logs: Return the tailed stdout and stderr logs for a specific job.
    """

    def __init__(self):
        super().__init__(
            "Job Monitor",
            "Tools for log inspection, failure detection, and job diagnostics.",
        )

        self.tail_bytes = int(get_env_var("MONITOR_LOG_TAIL_BYTES", 50000))
        self.status_depth = int(get_env_var("MONITOR_DEFAULT_STATUS_DEPTH", 20))
        self.job_monitor_helper = JobMonitorHelper(tail_bytes=self.tail_bytes, status_depth=self.status_depth)

    def _register_tools(self):
        """
        Register all MCP tools exposed by the Job Monitor Server.

        Tools defined:
            read_logs: Return tailed stdout and stderr content.
            summarize_status: Produce a structured diagnostic summary.
        """

        @self.mcp.tool()
        def read_logs(run_location: str, stdout_file: str, stderr_file: str) -> str:
            """
            Read and return the tailed stdout and stderr logs for a job.

            Args:
                run_location (str): Path to the directory containing output logs.
                stdout_file (str): Name of the stdout file to read.
                stderr_file (str): Name of the stderr file to read.

            Returns:
                str: JSON-encoded object containing:
                    - stdout (str): Tail of the stdout log.
                    - stderr (str): Tail of the stderr log.

            Raises:
                ToolExecutionError: If log reading fails for any reason.
            """
            return self.run_tool(self.job_monitor_helper.read_logs, run_location, stdout_file, stderr_file)

        @self.mcp.tool()
        def summarize_status(
            run_location: str,
            stdout_file: str,
            stderr_file: str,
            exit_code: Optional[int] = None,
        ) -> str:
            """
            Produce a structured job status summary including failure analysis.

            This tool reads the tails of stdout and stderr, concatenates them,
            classifies any detected failures, and returns a JSON-encoded
            diagnostic bundle. Used by the Job Manager or other agents to
            determine job health and identify root causes of failures.

            Args:
                run_location (str): Directory containing output logs.
                stdout_file (str): Name of the stdout file to read.
                stderr_file (str): Name of the stderr file to read.
                exit_code (Optional[int]): Exit code from the scheduler or runtime,
                    if available.

            Returns:
                str: JSON-encoded dictionary containing:
                    - exit_code (int or None)
                    - stdout_tail (str): Tail of the stdout log.
                    - stderr_tail (str): Tail of the stderr log.
                    - detected_failures (List[Dict]):
                        List of matched failure signatures or a fallback
                        unclassified entry with excerpt context.

            Notes:
                The classification logic is defined in failure_patterns.py and
                supports matching patterns such as segmentation faults, MPI
                aborts, scheduler preemption signatures, missing output, and
                other known error indicators.
            """
            return self.run_tool(
                self.job_monitor_helper.summarize_status,
                run_location,
                stdout_file,
                stderr_file,
                exit_code=exit_code,
            )


def main():
    """Main entry point for the Job Monitor MCP server."""
    server = JobMonitorServer()
    server.run_with_args("job_monitor")


if __name__ == "__main__":
    main()
