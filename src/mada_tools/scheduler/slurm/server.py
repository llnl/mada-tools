# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Slurm MCP Server for job scheduling and execution.

This server provides MCP tools for interacting with the Slurm workload manager,
including queued `sbatch` submission and direct `srun` execution.
"""

from typing import Optional

from mada_tools.scheduler.slurm.slurm_manager import SlurmJobManager
from mada_tools.shared.base_server import BaseMCPServer


class SlurmServer(BaseMCPServer):
    """
    MCP server for Slurm workload manager operations.

    Attributes:
        job_manager: Slurm-backed job manager used by registered MCP tools.

    Methods:
        _register_tools: Register Slurm job submission, status, and utility tools.
    """

    def __init__(self):
        super().__init__("Slurm Scheduler", "Slurm workload manager for job scheduling and execution")

        # Initialize SLURM job manager
        self.job_manager = SlurmJobManager()

    def _register_tools(self):
        """Register MCP tools for Slurm operations."""

        @self.mcp.tool()
        def submit_jobs(
            run_info_json: str,
            blocking: bool = False,
            nodes: int = 1,
            tasks: int = 1,
            time_limit: str = "01:00:00",
            account: Optional[str] = None,
            partition: Optional[str] = None,
            exclusive: bool = False,
            cpus_per_task: Optional[int] = None,
            job_name_prefix: str = "mada",
        ) -> str:
            """
            Submit batch jobs from a run manifest file or JSON string.

            This is the only tool for submitting generated simulation runs. Use
            the default `blocking=False` for queued `sbatch` submission that
            returns real Slurm job IDs immediately. Set `blocking=True` only for
            small debug runs where direct execution without queued Slurm IDs is
            explicitly requested.

            Args:
                run_info_json: JSON string, list, or file path (e.g., "run_instances.json").
                blocking: If False (default), submit to queue and return immediately.
                          If True, use direct execution for debugging (not recommended for production).
                nodes: Number of nodes to request per run.
                tasks: Total number of tasks to request per run.
                time_limit: Time limit string, e.g., "01:00:00".
                account: Slurm account name.
                partition: Slurm partition name.
                exclusive: Whether to request exclusive node access.
                cpus_per_task: Number of CPUs per task.
                job_name_prefix: Prefix for job names.

            Returns:
                str: JSON containing submission results and job IDs.
            """
            return self.run_tool(
                self.job_manager.submit_jobs,
                run_info_json,
                blocking=blocking,
                nodes=nodes,
                tasks=tasks,
                time_limit=time_limit,
                account=account,
                partition=partition,
                exclusive=exclusive,
                cpus_per_task=cpus_per_task,
                job_name_prefix=job_name_prefix,
            )

        @self.mcp.tool()
        def check_job_status(job_set_id: str = None, slurm_job_id: str = None) -> str:
            """
            Check the status of submitted job sets or one tracked Slurm job.

            Args:
                job_set_id: Job set ID to check. If not provided, shows all tracked job sets.
                slurm_job_id: Real Slurm job ID to check. Mutually exclusive with `job_set_id`.

            Returns:
                str: JSON containing job status information
            """
            return self.run_tool(
                self.job_manager.get_job_status,
                job_set_id=job_set_id,
                slurm_job_id=slurm_job_id,
            )

        @self.mcp.tool()
        def continuously_check_job_status(
            job_set_id: str = None,
            slurm_job_id: str = None,
            wait_until: str = "terminal",
            poll_interval_seconds: float = 10.0,
            timeout_seconds: float = 3600.0,
        ) -> str:
            """
            Poll Slurm job status until a condition is met or the timeout expires.

            Use this after `submit_jobs(blocking=False)` when the caller needs the MCP
            server to wait, such as end-to-end tests or starting downstream work
            after jobs begin running. This is bounded by `timeout_seconds`; it is
            not an infinite loop.

            Args:
                job_set_id: Job set ID to monitor. If not provided, monitors all tracked job sets.
                slurm_job_id: Real Slurm job ID to monitor. Mutually exclusive with `job_set_id`.
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
                job_set_id=job_set_id,
                slurm_job_id=slurm_job_id,
                wait_until=wait_until,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )

        @self.mcp.tool()
        def submit_command(
            command: str, working_directory: Optional[str] = None, nodes: int = 1, tasks: int = 1
        ) -> str:
            """
            Submit one ad hoc command using `srun`.

            Use this for running a single known command, not for generated run manifests
            or parameter sweeps. For batch simulation runs, use `submit_jobs` instead.

            Args:
                command: Command to execute
                working_directory: Working directory for the command (optional)
                nodes: Number of nodes (default: 1)
                tasks: Number of tasks (default: 1)

            Returns:
                str: Command output and status
            """
            self.run_tool(
                self.job_manager.submit_command,
                command,
                nodes,
                tasks,
                working_directory=working_directory,
            )

        @self.mcp.tool()
        def list_queue() -> str:
            """List all jobs in the SLURM queue using squeue."""
            self.run_tool(self.job_manager.list_queue)

        @self.mcp.tool()
        def get_cluster_info() -> str:
            """
            Get information about the cluster nodes using `sinfo`.

            Returns:
                Information about the cluster nodes from `sinfo`.
            """
            self.run_tool(self.job_manager.get_cluster_info)


def main():
    """Main entry point for the Slurm MCP server."""
    server = SlurmServer()
    server.run_with_args("slurm")


if __name__ == "__main__":
    main()
