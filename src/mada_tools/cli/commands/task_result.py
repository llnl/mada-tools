# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""CLI command for retrieving direct background task results."""

import json
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.shared.task_state_manager import TaskStateManager


class TaskResultCmd(BaseCmd):
    """Retrieve the persisted result for one direct background task."""

    def add_parser(self, subparsers: ArgumentParser):
        """Register the `task-result` CLI command.

        Args:
            subparsers: Parent subparser collection for the main CLI parser.
        """
        task_result = subparsers.add_parser(
            "task-result",
            help="Retrieve the result of a background direct command.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        task_result.add_argument("task_id", help="Task id returned by a background direct command.")
        task_result.add_argument(
            "--tasks-file",
            default=None,
            help="Optional path to the direct task state file.",
        )
        task_result.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """Print the current persisted task state as formatted JSON.

        Args:
            args: Parsed CLI arguments containing the task id and optional task
                state file path.
        """
        task_state_manager = TaskStateManager(Path(args.tasks_file) if args.tasks_file else None)
        print(json.dumps(task_state_manager.get_task(args.task_id), indent=2, default=str))
