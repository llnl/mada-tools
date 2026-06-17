# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Maestro MCP server for command execution.

This module defines an MCP server that wraps Maestro CLI workflow operations
and exposes them as tools. It provides support for:

- Running Maestro workflows
- Querying workflow status
- Canceling running workflows
- Updating workflow settings

The server delegates command execution to `MaestroCommandExecutor` and
registers the corresponding MCP tools for use by clients.
"""

from pathlib import Path
from typing import List

from mada_tools import BaseMCPServer
from mada_tools.workflow.weave.maestro.command_executor import MaestroCommandExecutor


class MaestroCommandExecutionServer(BaseMCPServer):
    """
    MCP Server for Maestro command execution.

    Attributes:
        command_executor: A `MaestroCommandExecutor` instance used to invoke
            Maestro CLI commands for running and managing workflows.

    Methods:
        register_jinja_study_tool: Register a tool backed by a single Jinja
            study template, or register multiple tools from a templates
            directory.
        register_study_construction_tools: Abstract hook for subclasses to
            register their own study construction tools.
        _register_path_tools: Register tools for working with filesystem paths.
        _register_workflow_management_tools: Register tools for running,
            querying, canceling, and updating Maestro workflows.
        _register_tools: Register all built-in and subclass-provided tools.
    """

    def __init__(self):
        """
        Constructor for `MaestroCommandExecutionServer`.
        """
        super().__init__("Maestro Command Execution Application", "A server for executing Maestro commands")

        # Command executor for running Maestro CLI commands
        self.command_executor = MaestroCommandExecutor()

    def _register_tools(self):
        """
        Register MCP tools for Maestro command execution operations.
        """

        @self.mcp.tool()
        def run_workflow(
            workflow_yaml: str | Path,
            attempts: int = 1,
            rlimit: int = 1,
            throttle: int = 0,
            sleeptime: int = 60,
            output_path: str | Path = None,
            pgen: str | Path = None,
            pargs: List[str] | None = None,
            dry: bool = False,
            foreground: bool = False,
            hash_ws: bool = False,
            use_tmp: bool = False,
        ) -> str:
            """
            Given a workflow YAML file, run the workflow using Maestro.

            This tool will execute the `maestro run` command with the provided workflow YAML file in
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
                str: The output message from the command execution.

            Raises:
                ValueError: If argument validation fails.
                ToolExecutionError: If the underlying Maestro command fails.

            Example:

                ```python
                run_workflow("/path/to/workflow.yaml")
                run_workflow("/path/to/workflow.yaml", attempts=4)
                run_workflow("/path/to/workflow.yaml", throttle=10, dry=True)
                run_workflow("/path/to/workflow.yaml", pgen="/path/to/pgen.py")
                ```
            """
            return self.run_tool(
                self.command_executor.run_workflow,
                workflow_yaml,
                attempts=attempts,
                rlimit=rlimit,
                throttle=throttle,
                sleeptime=sleeptime,
                output_path=output_path,
                pgen=pgen,
                pargs=pargs,
                dry=dry,
                foreground=foreground,
                hash_ws=hash_ws,
                use_tmp=use_tmp,
            )

        @self.mcp.tool()
        def get_statuses(
            workflow_dirs: List[str | Path],
            layout: str = "flat",
            disable_theme: bool = False,
        ) -> str:
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
                str: The output message from the command execution.

            Raises:
                ToolExecutionError: If the underlying Maestro command fails.

            Example:

                ```python
                get_statuses(["/path/to/workflow/dir", "/path/to/another_workflow/dir"])
                get_statuses(
                    ["/path/to/workflow/dir", "/path/to/another_workflow/dir"],
                    layout="narrow",
                    disable_theme=True
                )
                ```
            """
            return self.run_tool(
                self.command_executor.get_statuses, workflow_dirs, layout=layout, disable_theme=disable_theme
            )

        @self.mcp.tool()
        def cancel_workflows(workflow_dirs: List[str | Path]) -> str:
            """
            Cancel one or more running Maestro workflows.

            This tool will run a subprocess to execute the `maestro cancel` command.
            This command will take in a list of output directories where the output of
            currently running workflows are located, shut down any running jobs for these
            workflows, and stop any future jobs associated with these workflows from running.

            Args:
                workflow_dirs (List[str | Path]): A list of paths to Maestro workflow
                    output directories.

            Returns:
                str: The output message from the command execution.

            Raises:
                ToolExecutionError: If the underlying Maestro command fails.

            Example:

                ```python
                command_executor = MaestroCommandExecutor()
                workflows_to_cancel = ["/path/to/workflow/dir", "/path/to/another_workflow/dir"]
                success, msg = command_executor.cancel_workflows(workflows_to_cancel)
                if success:
                    print(f"Workflow cancelled successfully: {msg}")
                else:
                    print(f"Failed to cancel workflow: {msg}")
                ```
            """
            return self.run_tool(self.command_executor.cancel_workflows, workflow_dirs)

        @self.mcp.tool()
        def update_workflows(
            workflow_dirs: List[str | Path],
            rlimit: int = None,
            throttle: int = None,
            sleeptime: int = None,
        ) -> str:
            """
            Update the configs of running studies (throttle, rlimit, and/or sleep).

            This tool will run a subprocess to execute the `maestro update` command.
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
                str: The output message from the command execution.

            Raises:
                ToolExecutionError: If the underlying Maestro command fails.
            """
            return self.run_tool(
                self.command_executor.update_workflows,
                workflow_dirs,
                rlimit=rlimit,
                throttle=throttle,
                sleeptime=sleeptime,
            )


def main():
    """Main entry point for the Maestro Command Execution MCP server."""
    server = MaestroCommandExecutionServer()
    server.run_with_args("maestro_command_executor")


if __name__ == "__main__":
    main()
