# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
A base class to store common logic needed from settings classes.
"""

from abc import ABC
from dataclasses import dataclass


@dataclass
class BaseSettings(ABC):
    """
    A base class to store common logic needed from settings classes.

    Dataclasses like this help with type checking and setting defaults.
    They also make it really easy to add new settings.

    Methods:
        __post_init__: Optionally validates the input settings after the dataclass is initialized.
        validate: Validates the input settings.
        __str__: Returns a string representation of the settings.
        __repr__: Returns a string representation of the settings.
    """

    def __post_init__(self):
        """
        Optionally validates the input settings after the dataclass is initialized.
        """
        self.validate()

    def validate(self):
        """
        Validates the input settings.

        This method can be overridden by subclasses to provide specific validation logic.
        """
        pass

    def __str__(self):
        """
        Returns a string representation of the settings.
        """
        result = [f"{self.__class__.__name__} settings"]
        for key, value in self.__dict__.items():
            result.append(f"  - {key}: {value}")
        return "\n".join(result) + "\n"

    def __repr__(self):
        """
        Returns a string representation of the settings.
        """
        return f"{self.__class__.__name__}({self.__dict__})"
