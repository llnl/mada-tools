# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
This module defines the `BaseKwargsHandler` class, an abstract base class for handling keyword arguments
and converting them into settings objects. Subclasses should implement specific logic for different types
of settings.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Set

from .base_settings import BaseSettings


class BaseKwargsHandler(ABC):
    """
    Base class for handling keyword arguments to help convert them into settings objects.

    Subclasses should implement the `_get_settings_class`, `_get_supported_kwargs`,
    and `_get_required_kwargs` methods.
    """

    def __init__(self):
        """
        Initialize the BaseKwargsHandler.
        """
        self.settings_class = self._get_settings_class()
        self.supported_kwargs = self._get_supported_kwargs()
        self.required_kwargs = self._get_required_kwargs()

    def find_missing_required_kwargs(self, kwargs: Dict[str, Any]) -> Set[str]:
        """
        Find missing required keyword arguments.

        Args:
            kwargs: The keyword arguments to validate.

        Returns:
            A set of missing keys if any are missing, otherwise an empty set.
        """
        return self.required_kwargs - kwargs.keys()

    def build_settings_from_kwargs(self, kwargs: Dict[str, Any]) -> BaseSettings:
        """
        Validate the keyword arguments and build the settings object.

        Args:
            kwargs: The keyword arguments to validate and use for settings.

        Returns:
            The constructed settings object.
        """
        # 1. Check required keys
        missing_keys = self.find_missing_required_kwargs(kwargs)
        if missing_keys:
            raise ValueError(f"Missing required arguments: {missing_keys}")

        # 2. Warn about unknown keys
        extra_unknown_kwargs = set(kwargs.keys()) - set(self.supported_kwargs)
        if extra_unknown_kwargs:
            print(f"Unknown keyword arguments: {extra_unknown_kwargs}")

        # 3. Filter kwargs to only pass in supported kwargs
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in self.supported_kwargs}

        # 4. Construct settings object
        settings = self.settings_class(**filtered_kwargs)

        # 5. Print string representation
        print(settings)

        return settings

    @abstractmethod
    def _get_settings_class(self) -> BaseSettings:
        """
        Get the settings class for this handler.

        Returns:
            The settings class.
        """

    @abstractmethod
    def _get_supported_kwargs(self) -> Set[str]:
        """
        Get the set of supported keyword arguments.

        This method will return a set of ALL keyword arguments that are supported
        by this handler.

        Returns:
            A set of supported keyword argument names.
        """

    @abstractmethod
    def _get_required_kwargs(self) -> Set[str]:
        """
        Get the set of required keyword arguments.

        This method will only return a set of keyword arguments that are
        required for this handler. This could be an empty set if no specific
        arguments are required.

        Returns:
            A set of required keyword argument names.
        """
