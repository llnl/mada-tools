# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Helpers shared by extension-provided direct CLI commands."""

import inspect
from importlib import import_module
from typing import Any, Callable

from mada_tools.cli.commands.base_cmd import BaseCmd


def load_direct_commands(callable_path: str) -> list[BaseCmd]:
    """Load `BaseCmd` instances from one direct-command registration target.

    The manifest-declared target may be a `BaseCmd` subclass, a `BaseCmd`
    instance, or a callable that returns one or more `BaseCmd` instances. This
    keeps extension-provided direct commands aligned with the rest of the CLI
    command architecture while minimizing registration boilerplate for the
    common single-command case.

    Args:
        callable_path: Manifest-defined import target in
            `module.path:callable_name` form.

    Returns:
        list[BaseCmd]: Instantiated direct command objects provided by the
        registration target.

    Raises:
        ValueError: If `callable_path` does not follow the expected manifest
        format.
        RuntimeError: If the target is missing, is not callable, or does not
            return `BaseCmd` instances.
    """
    # Split the manifest path into module and callable parts.
    module_path, separator, callable_name = callable_path.partition(":")
    if not separator or not module_path or not callable_name:
        raise ValueError(f"Invalid direct command callable_path: {callable_path}")

    # Load the module and verify that the callable exists.
    module = import_module(module_path)
    if not hasattr(module, callable_name):
        raise RuntimeError(f"Direct command target '{callable_path}' is missing")
    direct_command_target = getattr(module, callable_name)

    # Normalize the loaded target into one or more `BaseCmd` instances.
    return _normalize_direct_commands(callable_path, direct_command_target)


def load_direct_background_runner(callable_path: str) -> Callable[..., None]:
    """Resolve the background runner for one registered direct command target.

    Background execution is routed through the registered direct command's
    `adapter_class`, which must expose callable `run_background_task()`.

    Args:
        callable_path: Manifest-defined import target in
            `module.path:callable_name` form.

    Returns:
        Callable[..., None]: The direct executor classmethod used to run one
        detached background task.

    Raises:
        ValueError: If `callable_path` does not follow the expected manifest
            format.
        RuntimeError: If the direct command does not resolve to exactly one
            command with an `adapter_class` that exposes callable
            `run_background_task()`.
    """
    commands = load_direct_commands(callable_path)
    if len(commands) != 1:
        raise RuntimeError(
            f"Direct command target '{callable_path}' must resolve to exactly one BaseCmd for background execution"
        )

    adapter_class = getattr(commands[0], "adapter_class", None)
    runner = getattr(adapter_class, "run_background_task", None)
    if not callable(runner):
        raise RuntimeError(
            f"Direct command target '{callable_path}' must define adapter_class with callable run_background_task()"
        )
    return runner


def _normalize_direct_commands(callable_path: str, target: Any) -> list[BaseCmd]:
    """Normalize one direct-command registration target into command instances.

    Args:
        callable_path: Manifest-defined import target used for error reporting.
        target: Loaded target object referenced by the manifest.

    Returns:
        list[BaseCmd]: Instantiated direct command objects.

    Raises:
        RuntimeError: If the target does not resolve to `BaseCmd` instances.
    """
    # Case 1: The target is a `BaseCmd` subclass, so instantiate it.
    if inspect.isclass(target) and issubclass(target, BaseCmd):
        return [target()]

    # Case 2: The target is a `BaseCmd` instance, so return it directly.
    if isinstance(target, BaseCmd):
        return [target]

    # Ensure that the target is callable.
    if not callable(target):
        raise RuntimeError(
            f"Direct command target '{callable_path}' must be a BaseCmd, BaseCmd subclass, or callable factory"
        )

    # Case 3: The target is a callable that returns one or more `BaseCmd` instances.
    provided_commands = target()
    if isinstance(provided_commands, BaseCmd):
        return [provided_commands]

    # Ensure that the callable returned a list or tuple of `BaseCmd` instances.
    if not isinstance(provided_commands, (list, tuple)):
        raise RuntimeError(
            f"Direct command target '{callable_path}' must return BaseCmd or a list/tuple of BaseCmd instances"
        )

    # Ensure that the callable returned at least one `BaseCmd` instance.
    commands = list(provided_commands)
    if not commands:
        raise RuntimeError(f"Direct command target '{callable_path}' returned no commands")

    # Ensure that all returned commands are `BaseCmd` instances.
    invalid_command = next((command for command in commands if not isinstance(command, BaseCmd)), None)
    if invalid_command is not None:
        raise RuntimeError(
            f"Direct command target '{callable_path}' returned {type(invalid_command).__name__} instead of BaseCmd"
        )

    return commands
