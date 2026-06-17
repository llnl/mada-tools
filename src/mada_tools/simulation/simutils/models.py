# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Models for job management.

This module defines data classes for various job management settings and results.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class RunInstance:
    """
    Represents a single instance of a computational run, storing relevant data
    and metadata associated with the run.

    Attributes:
        run_location (str): The directory where the run will be executed.
        id (str): The identifier for a run instance.
        command (str): The executable command to run (optional).
        args (List[str]): The arguments to pass to the command (optional).

    Methods:
        to_dict: Converts the RunInstance object into a JSON-serializable dictionary.
        get_command_with_args: Returns the command and arguments for execution.
    """

    run_location: str
    id: str
    command: str = None
    args: List[str] = None

    def to_dict(self) -> Dict:
        """
        Converts the RunInstance object into a JSON-serializable dictionary.

        Returns:
            A dictionary representation of the RunInstance object.
        """
        result = {"id": self.id, "run_location": self.run_location}

        # Include command and args if they are set
        if self.command:
            result["command"] = self.command
        if self.args:
            result["args"] = self.args

        return result

    @classmethod
    def from_dict(cls, data: Dict) -> "RunInstance":
        """
        Creates a RunInstance object from a dictionary.

        Args:
            data: Dictionary containing run instance data

        Returns:
            RunInstance object with data from the dictionary
        """
        return cls(
            run_location=data.get("run_location"),
            id=data.get("id"),
            command=data.get("command"),
            args=data.get("args"),
        )

    def __str__(self) -> str:
        """
        Returns a human-readable string representation of the RunInstance object.

        Returns:
            str: A string describing the run instance.
        """
        result = f"RunInstance '{self.id}':\n\tLocation: {self.run_location}"
        if self.command:
            result += f"\n\tCommand: {self.command}"
        if self.args:
            result += f"\n\tArgs: {self.args}"
        return result

    def __repr__(self) -> str:
        """
        Returns a detailed string representation of the RunInstance object for debugging.

        Returns:
            str: A detailed string representation of the object.
        """
        return f"RunInstance(id={self.id}, run_location={self.run_location}, command={self.command}, args={self.args})"

    def get_command_with_args(self) -> Tuple[str, List[str]]:
        """
        Returns the command and arguments for execution.

        Returns:
            Tuple[str, List[str]]: The command and its arguments.
        """
        if self.command and self.args:
            return self.command, self.args
        else:
            raise ValueError("Command and args not set for this RunInstance")

    def get_run_command(self) -> str:
        """
        Constructs the shell command to execute this run instance.

        Returns:
            str: The shell command to execute this run.
        """
        if self.command and self.args:
            return f"{self.command} {' '.join(self.args)}"
        else:
            raise ValueError("No command specified for this RunInstance")


@dataclass
class SampleOutputResult:
    """
    Represents the result of sample output generation, storing the output path,
    output type, and optionally the run instances (if necessary).

    Attributes:
        output_path (str): The path where the samples are written. For "csv" output, this
            is the path to the CSV file. For "folder" output, this is the path to the directory.
        output_type (str): The type of output generated (e.g., "csv", "folder").
        run_instances (List[RunInstance]): A list of RunInstance objects if the output type is "folder".
    """

    output_path: str
    output_type: str  # e.g., "csv", "folder"
    run_instances: List[RunInstance] = None

    def __str__(self) -> str:
        """
        Returns a human-readable string representation of the SampleOutputResult object.

        Returns:
            str: A string describing the sample output result.
        """
        return (
            f"SampleOutputResult:\n"
            f"  Output path: {self.output_path}\n"
            f"  Output type: {self.output_type}\n"
            f"  Run instances: {self.run_instances}"
        )

    def __repr__(self) -> str:
        """
        Returns a detailed string representation of the SampleOutputResult object for debugging.

        Returns:
            str: A detailed string representation of the object.
        """
        return (
            f"SampleOutputResult(output_path={self.output_path}, "
            f"output_type={self.output_type}, run_instances={self.run_instances})"
        )
