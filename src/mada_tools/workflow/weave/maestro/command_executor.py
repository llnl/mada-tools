# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
This module provides the `MaestroCommandExecutor` class, a Python interface for managing
Maestro workflow executions via command-line interactions. Maestro is a workflow
management tool used to define, execute, and monitor computational workflows
described in YAML specification files.

The `MaestroCommandExecutor` class wraps common Maestro CLI commands, allowing users to:
    - Run workflows from YAML specification files
    - Query the status of running or completed workflows
    - Cancel running workflows
    - Update configuration parameters (such as throttle, rlimit, and sleeptime) for active workflows

All Maestro operations are executed in subprocesses, and the results (including
success status and output messages) are returned for further handling in Python.
"""

import subprocess
from pathlib import Path
from typing import List, Tuple


class MaestroCommandExecutor:
    """
    Class to execute Maestro commands.

    This class essentially acts as a wrapper to Maestro CLI commands.

    Methods:
        execute_command: Executes a given command in a subprocess.
        run_workflow: Run a Maestro workflow YAML spec.
        get_statuses: Given a list of workflows, retrieve their statuses.
        cancel_workflows: Given a list of workflows, cancel them all.
        update_workflows: Given a list of workflows, update their configurations.
    """

    def execute_command(self, command: List[str], confirm: str = None) -> Tuple[bool, str]:
        """
        Given a command, run it as a subprocess and return a tuple indicating success and the output or error message.

        This should be how each Maestro command is executed. The try/except clause helps
        prevent errors from arising and taking down a chat session.

        Args:
            command: List of strings representing the command and its arguments to be executed.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and the command output or error message.
        """
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                input=confirm,  # necessary for the `maestro cancel` command that requires user input from the CLI
            )
            output = proc.stdout + proc.stderr
            if proc.returncode == 0:
                return True, output
            else:
                return False, output
        except Exception as e:
            return False, str(e)

    # TODO how should we handle pgen/pargs?
    def run_workflow(
        self,
        workflow_yaml: str | Path,
        attempts: int = 1,
        rlimit: int = 1,
        throttle: int = 0,
        sleeptime: int = 60,
        output_path: str | Path = None,
        pgen: str = None,
        pargs: List[str] = None,
        dry: bool = False,
        foreground: bool = False,
        hash_ws: bool = False,
        use_tmp: bool = False,
    ) -> Tuple[bool, str]:
        """
        Given a workflow YAML file, run the workflow using Maestro.

        This method will execute the `maestro run` command with the provided workflow YAML file in
        a subprocess. Behind the scenes of this command, Maestro will convert the workflow YAML into
        a DAG, expand parameters/variables throughout the spec file, and excecute the DAG by converting
        steps into shell scripts that get executed.

        Args:
            workflow_yaml (str | Path): Path to the Maestro workflow YAML file.
            attempts (int): Maximum number of submission attempts before a step is marked as failed.
                Default 1.
            rlimit (int): Maximum number of restarts allowed when steps specify a restart command (0
                denotes no limit). Default 1.
            throttle (int): Maximum number of inflight jobs allowed to execute simultaneously (0 denotes
                not throttling). Default 0.
            sleeptime (int): Amount of time (in seconds) for the manager to wait between job status checks.
                Default 60.
            output_path (str | Path): Output path to place study in (NOTE: overrides OUTPUT_PATH in the
                specified specification). Default None.
            pgen (str | Path): Path to a Python file that defines a custom Maestro ParameterGenerator.
                    Passed through to `maestro run --pgen ...`. Default None.
            pargs (List[str] | None): Optional arguments to pass to the custom parameter generation
                function. Passed through as one or more `maestro run --pargs ...` values. Requires `pgen`.
                Each list entry should be of the form "PARAM_NAME:VALUE".
            dry (bool): Generate the directory structure and scripts for a study but do not launch it.
                Default False.
            foreground (bool): Runs the backend conductor in the foreground instead of using nohup.
                Default False.
            hash_ws (bool): Enable hashing of subdirectories in parameterized studies (NOTE: breaks commands
                that use parameter labels to search directories). Default False.
            use_tmp (bool): make use of a temporary directory for dumping scripts and other Maestro-related
                files. Default False.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and a message.

        Example:

            ```python
            command_executor = MaestroCommandExecutor()
            success, msg = command_executor.run_workflow("path/to/workflow.yaml")
            if success:
                print(f"Workflow running successfully: {msg}")
            else:
                print(f"Failed to run workflow: {msg}")
            ```
        """
        # Validate workflow YAML
        if workflow_yaml == "":
            return False, "Workflow YAML specification cannot be an empty string."
        if not Path(workflow_yaml).exists():
            return False, "The provided workflow YAML specification does not exist in the file system."

        # Validate pgen is provided if pargs exist
        if pargs and not pgen:
            raise ValueError("run_workflow: `pargs` requires `pgen` to also be provided.")

        # Construct `maestro run` command
        command = [
            "maestro",
            "run",
            str(workflow_yaml),
            "--autoyes",  # Used to automatically launch the study
            "--attempts",
            str(attempts),
            "--rlimit",
            str(rlimit),
            "--throttle",
            str(throttle),
            "--sleeptime",
            str(sleeptime),
        ]
        if output_path:
            command += ["--out", output_path]
        if pgen:
            pgen_path = Path(pgen).expanduser()
            if not pgen_path.is_absolute():
                pgen_path = (Path.cwd() / pgen_path).resolve(strict=False)
            normalized_pgen = str(pgen_path)
            pargs_entries = [parg_entry for parg in pargs for parg_entry in ("--pargs", parg)]
            command += ["--pgen", normalized_pgen] + pargs_entries
        if dry:
            command += ["--dry"]
        if foreground:
            command += ["-fg"]
        if hash_ws:
            command += ["--hashws"]
        if use_tmp:
            command += ["--usetmp"]

        # Execute the command
        return self.execute_command(command)

    def get_statuses(
        self,
        workflow_dirs: List[str | Path],
        layout: str = "flat",
        disable_theme: bool = False,
    ) -> Tuple[bool, str]:
        """
        Get the statuses of currently running Maestro workflows.

        This tool will run a subprocess to execute the `maestro status` command.
        This command will take in a list of output directories where the output of
        currently running workflows are located and return their statuses.

        Args:
            workflow_dirs (List[str | Path]): A list of paths to Maestro workflow
                output directories.
            layout (str): The layout of the status table. Options are "flat", "legacy",
                and "narrow". Default "flat".
            disable_theme (bool): Turn off styling for the status layout.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and a message.

        Example:

            ```python
            command_executor = MaestroCommandExecutor()
            workflows_to_check = ["/path/to/workflow/dir", "/path/to/another_workflow/dir"]
            success, msg = command_executor.get_workflow_status(workflows_to_check)
            if success:
                print(f"Workflow statuses retrieved successfully: {msg}")
            else:
                print(f"Failed to retrieve workflow statuses: {msg}")
            ```
        """
        if not workflow_dirs:
            return False, "No workflows provided to `get_statuses`."

        # Construct the `maestro status` command
        command = (
            ["maestro", "status"]
            + [str(workflow_dir) for workflow_dir in workflow_dirs]
            + [
                "--disable-pager",  # We disable pager so output goes directly to terminal
                "--layout",
                layout,
            ]
        )
        if disable_theme:
            command += ["--disable-theme"]

        # Execute the command
        return self.execute_command(command)

    def cancel_workflows(self, workflow_dirs: List[str | Path]) -> Tuple[bool, str]:
        """
        Cancel one or more running Maestro workflows.

        This method will run a subprocess to execute the `maestro cancel` command.
        This command will take in a list of output directories where the output of
        currently running workflows are located, shut down any running jobs for these
        workflows, and stop any future jobs associated with these workflows from running.

        Cancelling a study *is not* instantaneous. The background conductor is a daemon
        which spins up periodically, so cancellation occurs the next time the conductor
        returns from sleeping and sees that a cancel has been triggered.

        Args:
            workflow_dirs (List[str | Path]): A list of paths to Maestro workflow
                output directories.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and a message.

        Example:

            ```python
            command_executor = MaestroCommandExecutor()
            workflows_to_cancel = ["/path/to/workflow/dir", "/path/to/another_workflow/dir"]
            success, msg = command_executor.cancel_workflows(workflows_to_cancel)
            if success:
                print(f"Workflows cancelled successfully: {msg}")
            else:
                print(f"Failed to cancel workflows: {msg}")
            ```
        """
        if not workflow_dirs:
            return False, "No workflows provided to `cancel_workflows`."

        return self.execute_command(
            ["maestro", "cancel"] + [str(workflow_dir) for workflow_dir in workflow_dirs], confirm="y"
        )

    def update_workflows(
        self,
        workflow_dirs: List[str | Path],
        rlimit: int = None,
        throttle: int = None,
        sleeptime: int = None,
    ) -> Tuple[bool, str]:
        """
        Update the configs of running studies (throttle, rlimit, and/or sleep).

        This method will run a subprocess to execute the `maestro update` command.
        This command will take in a list of output directories where the output of
        currently running workflows are located and rlimit, throttle, and/or sleeptime
        settings. It will then update the configurations of any workflow provided
        with the new settings.

        Args:
            workflow_dirs (List[str | Path]): A list of paths to Maestro workflow output directories.
            rlimit (int): Maximum number of restarts allowed when steps specify a restart command (0
                denotes no limit). Default 1.
            throttle (int): Maximum number of inflight jobs allowed to execute simultaneously (0 denotes
                not throttling). Default 0.
            sleeptime (int): Amount of time (in seconds) for the manager to wait between job status checks.
                Default 60.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and a message.

        Example:

            ```python
            command_executor = MaestroCommandExecutor()
            workflows_to_update = ["/path/to/workflow/dir", "/path/to/another_workflow/dir"]
            success, msg = command_executor.cancel_workflows(workflows_to_update, rlimit=0, throttle=10, sleeptime=120)
            if success:
                print(f"Workflows updated successfully: {msg}")
            else:
                print(f"Failed to update workflows: {msg}")
            ```
        """
        # Check that at least one workflow directory was provided
        if not workflow_dirs:
            return False, "No workflows provided to `update_workflows`."

        # Check that at least one setting was provided
        if rlimit is None and throttle is None and sleeptime is None:
            return False, "No settings to update. Need to provide one of 'rlimit', 'throttle', or 'sleeptime'."

        # Construct the `maestro update` command
        command = ["maestro", "update"] + [str(workflow_dir) for workflow_dir in workflow_dirs]
        if rlimit is not None:
            command += ["--rlimit", str(rlimit)]
        if throttle is not None:
            command += ["--throttle", str(throttle)]
        if sleeptime is not None:
            command += ["--sleep", str(sleeptime)]

        # Execute the command
        return self.execute_command(command)
