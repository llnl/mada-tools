# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Flux MCP Server for job scheduling and execution.

This server provides MCP tools for interacting with the Flux scheduler,
including resource-aware job submission and monitoring.
"""

import logging
from typing import Optional

from mada_tools.scheduler.flux.flux_manager import FluxJobManager
from mada_tools.shared.base_server import BaseMCPServer

LOG = logging.getLogger(__name__)


class FluxServer(BaseMCPServer):
    """
    MCP server for Flux scheduler operations.

    Attributes:
        job_manager: Flux-backed job manager created after configuration
            environment variables are applied.

    Methods:
        _register_tools: Register Flux job submission and monitoring tools.
    """

    def __init__(self):
        super().__init__("Flux Scheduler", "Flux scheduler for job scheduling and execution")
        self.job_manager = None

    def __del__(self):
        """Cleanup when server is destroyed."""
        if hasattr(self, "job_manager") and self.job_manager:
            try:
                self.job_manager.stop_persistent_executor()
            except Exception as exc:
                LOG.warning("Failed to stop persistent executor during cleanup: %s", exc)
                pass

    def _register_tools(self):
        """Register MCP tools for Flux operations."""
        # Delay Flux connection setup until after BaseMCPServer has applied
        # config-provided env vars in run_with_args().
        self.job_manager = FluxJobManager()

        @self.mcp.tool()
        def submit_command(
            command: str,
            nodes: int = 1,
            tasks: int = 1,
            cores_per_task: int = 1,
            gpus_per_task: int = 0,
            time_limit: str = "1h",
            job_name: Optional[str] = None,
            working_directory: Optional[str] = None,
            queue: Optional[str] = None,
            bank: Optional[str] = None,
            exclusive: bool = False,
            urgency: int = 16,
        ) -> str:
            """
            Submit one ad hoc command to the Flux scheduler.

            Use this for running a single known command. For batch simulation runs
            from manifest files like run_instances.json, use `submit_jobs` instead.

            Args:
                command: Command to execute
                nodes: Number of nodes to request
                tasks: Total number of tasks to request
                cores_per_task: Number of CPU cores per task
                gpus_per_task: Number of GPUs per task
                time_limit: Time limit (e.g., "1h", "30m", "120s")
                job_name: Optional job name
                working_directory: Working directory for the job
                queue: Optional Flux queue, for example `pdebug` or `pbatch`
                bank: Optional Flux bank/account
                exclusive: Whether to request exclusive nodes
                urgency: Flux job urgency from 0 to 31

            Returns:
                str: JSON describing the submitted Flux job
            """
            return self.run_tool(
                self.job_manager.submit_command,
                command,
                working_directory=working_directory,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                job_name=job_name,
                urgency=urgency,
            )

        @self.mcp.tool()
        def submit_jobs(
            run_info_json: str,
            blocking: bool = False,
            nodes: int = 1,
            tasks: int = 1,
            cores_per_task: int = 1,
            gpus_per_task: int = 0,
            time_limit: str = "1h",
            queue: Optional[str] = None,
            bank: Optional[str] = None,
            exclusive: bool = False,
            job_name_prefix: str = "mada",
            urgency: int = 16,
        ) -> str:
            """
            Submit batch jobs from a run manifest file or JSON string.

            This is the only tool for submitting generated simulation runs. Use
            the default `blocking=False` for scheduler-backed submission that
            returns local tracking IDs plus real Flux job IDs immediately. Set
            `blocking=True` only for small debug runs where the caller explicitly
            wants this tool call to wait for completion.

            Args:
                run_info_json: JSON string, list, or file path (e.g., "run_instances.json").
                blocking: If False (default), submit jobs and return immediately with job IDs.
                          If True, submit jobs and wait for all to complete before returning.
                nodes: Number of nodes to request per run.
                tasks: Total number of tasks to request per run.
                cores_per_task: Number of CPU cores per task.
                gpus_per_task: Number of GPUs per task.
                time_limit: Time limit string, e.g., "1h" or "30m".
                queue: Flux queue name, e.g., "pdebug" or "pbatch".
                bank: Flux bank/account name.
                exclusive: Whether to request exclusive nodes.
                job_name_prefix: Prefix for generated job names.
                urgency: Flux job urgency from 0 to 31.

            Returns:
                str: JSON containing submission results and job IDs.
            """
            return self.run_tool(
                self.job_manager.submit_jobs,
                run_info_json,
                blocking=blocking,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                job_name_prefix=job_name_prefix,
                urgency=urgency,
            )

        @self.mcp.tool()
        def check_job_status(job_id: str = None, flux_job_id: str = None) -> str:
            """
            Check the status of tracked jobs or one real Flux job ID.

            Args:
                job_id: Specific local MADA tracking ID to check.
                flux_job_id: Specific real Flux job ID to check, even if untracked locally.

            Returns:
                str: JSON containing job status information
            """
            return self.run_tool(self.job_manager.get_job_status, job_id=job_id, flux_job_id=flux_job_id)

        @self.mcp.tool()
        def continuously_check_job_status(
            job_id: str = None,
            flux_job_id: str = None,
            wait_until: str = "terminal",
            poll_interval_seconds: float = 10.0,
            timeout_seconds: float = 3600.0,
        ) -> str:
            """
            Poll Flux job status until a condition is met or the timeout expires.

            Use this after `submit_jobs(blocking=False)` when the caller needs the MCP
            server to wait, such as end-to-end tests or starting downstream work
            after jobs begin running. This is bounded by `timeout_seconds`; it is
            not an infinite loop.

            Args:
                job_id: Specific local MADA tracking ID to monitor.
                flux_job_id: Specific real Flux job ID to monitor.
                wait_until: `terminal` waits for selected jobs to finish;
                    `any_running` returns once any selected job is running, or
                    when all selected jobs have already reached terminal states.
                poll_interval_seconds: Seconds between status checks.
                timeout_seconds: Maximum seconds to wait before returning.

            Returns:
                str: JSON containing polling metadata plus the last status response.
            """
            return self.run_tool(
                self.job_manager.continuously_check_job_status,
                job_id=job_id,
                flux_job_id=flux_job_id,
                wait_until=wait_until,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )


def main():
    """Main entry point for the Flux MCP server."""
    server = FluxServer()
    server.run_with_args("flux")


if __name__ == "__main__":
    main()
