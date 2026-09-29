# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Internal CLI command used to execute detached direct background tasks."""

import json
from argparse import SUPPRESS, ArgumentParser, Namespace
from datetime import UTC, datetime
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.shared.direct_cli import load_direct_background_runner
from mada_tools.shared.task_state_manager import TaskStateManager


class RunDirectTaskCmd(BaseCmd):
    """Execute one detached direct background task in a worker process."""

    def add_parser(self, subparsers: ArgumentParser):
        """Register the hidden worker command used for detached execution.

        Args:
            subparsers: Parent subparser collection for the main CLI parser.
        """
        run_direct_task = subparsers.add_parser("_run-direct-task", help=SUPPRESS)
        run_direct_task.add_argument("--task-id", required=True)
        run_direct_task.add_argument("--callable-path", required=True)
        run_direct_task.add_argument("--action", required=True)
        run_direct_task.add_argument("--payload", required=True)
        run_direct_task.add_argument("--tasks-file", default=None)
        run_direct_task.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """Resolve the direct-command runner and execute it for one task.

        Args:
            args: Parsed CLI arguments describing the detached task to execute.

        Raises:
            Exception: Re-raises any worker failure after persisting a failed
                task payload for later inspection.
        """
        task_state_manager = TaskStateManager(Path(args.tasks_file) if args.tasks_file else None)
        runner = load_direct_background_runner(args.callable_path)

        try:
            runner(
                task_id=args.task_id,
                action=args.action,
                payload=json.loads(args.payload),
                tasks_file=args.tasks_file,
            )
        except Exception as exc:
            existing_task = task_state_manager.get_task(args.task_id)
            failure_payload = {
                "task_id": args.task_id,
                "task_name": existing_task.get("task_name", args.action),
                "status": "failed",
                "submitted_at": existing_task.get("submitted_at"),
                "completed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "result": None,
                "error": str(exc),
            }
            task_state_manager.upsert_task(failure_payload)
            raise
