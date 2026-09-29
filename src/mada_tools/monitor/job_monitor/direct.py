# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Direct CLI adapter for the `job_monitor` capability."""

import asyncio
import json
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from typing import Any

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.monitor.job_monitor.job_monitor_helper import JobMonitorHelper
from mada_tools.shared.base_direct_executor import BaseDirectExecutor
from mada_tools.shared.env import get_env_var

CALLABLE_PATH = "mada_tools.monitor.job_monitor.direct:JobMonitorDirectCmd"


class JobMonitorDirectAdapter(BaseDirectExecutor):
    """Execute `job_monitor` helper operations through the shared task runtime."""

    capability_name = "job_monitor"

    def __init__(
        self,
        tail_bytes: int | None = None,
        status_depth: int | None = None,
        task_runtime=None,
    ):
        """Initialize the direct adapter using the same helper configuration as the MCP server.

        Args:
            tail_bytes: Optional explicit log-tail size override.
            status_depth: Optional explicit status-depth override.
            task_runtime: Optional shared background-task runtime. When omitted,
                a direct-CLI runtime is created.
        """
        super().__init__(task_runtime=task_runtime)
        resolved_tail_bytes = (
            tail_bytes if tail_bytes is not None else int(get_env_var("MONITOR_LOG_TAIL_BYTES", 50000))
        )
        resolved_status_depth = (
            status_depth if status_depth is not None else int(get_env_var("MONITOR_DEFAULT_STATUS_DEPTH", 20))
        )
        self.helper = JobMonitorHelper(tail_bytes=resolved_tail_bytes, status_depth=resolved_status_depth)

    async def read_logs(self, run_location: str, stdout_file: str, stderr_file: str) -> str:
        """Return tailed stdout and stderr logs for one run.

        Args:
            run_location: Path to the run directory containing the log files.
            stdout_file: Name of the stdout log file.
            stderr_file: Name of the stderr log file.

        Returns:
            str: JSON payload returned by `JobMonitorHelper.read_logs()`.
        """
        return await self.execute_handler(
            self.helper.read_logs,
            {
                "run_location": run_location,
                "stdout_file": stdout_file,
                "stderr_file": stderr_file,
            },
            action_name="read_logs",
        )

    async def summarize_status(
        self,
        run_location: str,
        stdout_file: str,
        stderr_file: str,
        exit_code: int | None = None,
    ) -> str:
        """Return a structured status summary including failure classifications.

        Args:
            run_location: Path to the run directory containing the log files.
            stdout_file: Name of the stdout log file.
            stderr_file: Name of the stderr log file.
            exit_code: Optional scheduler or application exit code.

        Returns:
            str: JSON payload returned by `JobMonitorHelper.summarize_status()`.
        """
        return await self.execute_handler(
            self.helper.summarize_status,
            {
                "run_location": run_location,
                "stdout_file": stdout_file,
                "stderr_file": stderr_file,
                "exit_code": exit_code,
            },
            action_name="summarize_status",
        )

    def get_action_handler(self, action: str):
        """Return the bound helper method that implements one direct action.

        Args:
            action: Direct action name to resolve.

        Returns:
            Callable[..., tuple[bool, str]]: Bound helper method implementing
            the requested action.

        Raises:
            ValueError: If `action` is unsupported.
        """
        action_handlers = {
            "read_logs": self.helper.read_logs,
            "summarize_status": self.helper.summarize_status,
        }
        try:
            return action_handlers[action]
        except KeyError as exc:
            raise ValueError(f"Unsupported job-monitor action: {action}") from exc


class JobMonitorDirectCmd(BaseCmd):
    """CLI command that exposes direct `job_monitor` capability execution."""

    adapter_class = JobMonitorDirectAdapter

    def add_parser(self, subparsers: ArgumentParser):
        """Register the `job-monitor` direct CLI command tree.

        Args:
            subparsers: Parent subparser collection for the main CLI parser.
        """
        job_monitor_parser = subparsers.add_parser(
            "job-monitor",
            help="Run job monitor capabilities directly without starting MCP.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        job_monitor_subparsers = job_monitor_parser.add_subparsers(dest="job_monitor_action", required=True)

        read_logs = job_monitor_subparsers.add_parser(
            "read-logs",
            help="Read tailed stdout and stderr logs for one run.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        self._add_common_task_arguments(read_logs)
        read_logs.add_argument("run_location", help="Path to the run directory containing the log files.")
        read_logs.add_argument("stdout_file", help="Name of the stdout log file.")
        read_logs.add_argument("stderr_file", help="Name of the stderr log file.")
        read_logs.set_defaults(func=self.process_command, direct_action="read_logs")

        summarize_status = job_monitor_subparsers.add_parser(
            "summarize-status",
            help="Summarize job status and classify failure signatures.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        self._add_common_task_arguments(summarize_status)
        summarize_status.add_argument("run_location", help="Path to the run directory containing the log files.")
        summarize_status.add_argument("stdout_file", help="Name of the stdout log file.")
        summarize_status.add_argument("stderr_file", help="Name of the stderr log file.")
        summarize_status.add_argument(
            "--exit-code",
            type=int,
            default=None,
            help="Optional scheduler or application exit code to include in the summary.",
        )
        summarize_status.set_defaults(func=self.process_command, direct_action="summarize_status")

    def process_command(self, args: Namespace) -> None:
        """Execute one direct `job_monitor` command in foreground or background mode.

        Args:
            args: Parsed CLI arguments for one `job-monitor` direct command.

        Raises:
            ValueError: If the selected direct action is unsupported.
        """
        if args.background:
            task_info = self.adapter_class.start_background_task(
                callable_path=CALLABLE_PATH,
                action=args.direct_action,
                payload=self._build_payload(args),
                tasks_file=args.tasks_file,
            )
            print(json.dumps(task_info, indent=2, default=str))
            return

        adapter = JobMonitorDirectAdapter()
        if args.direct_action == "read_logs":
            result = asyncio.run(adapter.read_logs(args.run_location, args.stdout_file, args.stderr_file))
        elif args.direct_action == "summarize_status":
            result = asyncio.run(
                adapter.summarize_status(
                    args.run_location,
                    args.stdout_file,
                    args.stderr_file,
                    exit_code=args.exit_code,
                )
            )
        else:
            raise ValueError(f"Unsupported job-monitor action: {args.direct_action}")

        print(result)

    @staticmethod
    def _add_common_task_arguments(parser: ArgumentParser) -> None:
        """Add shared direct-task arguments to one command parser.

        Args:
            parser: Parser for one direct `job-monitor` subcommand.
        """
        parser.add_argument(
            "--background",
            action="store_true",
            help="Run the direct command in the background and return a task id.",
        )
        parser.add_argument(
            "--tasks-file",
            default=None,
            help="Optional path to the direct task state file.",
        )

    @staticmethod
    def _build_payload(args: Namespace) -> dict[str, Any]:
        """Build the JSON-safe payload sent to a detached worker process.

        Args:
            args: Parsed CLI arguments for one `job-monitor` direct command.

        Returns:
            dict[str, Any]: JSON-safe payload forwarded to the detached worker.
        """
        payload = {
            "run_location": args.run_location,
            "stdout_file": args.stdout_file,
            "stderr_file": args.stderr_file,
        }
        if args.direct_action == "summarize_status":
            payload["exit_code"] = args.exit_code
        return payload
