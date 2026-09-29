# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for direct CLI loading helpers."""

from argparse import ArgumentParser, Namespace

import pytest

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.shared.direct_cli import load_direct_background_runner, load_direct_commands


class DummyCmd(BaseCmd):
    """Small concrete command used to validate direct-command loading."""

    def add_parser(self, subparsers: ArgumentParser):
        """Register a no-op parser for tests.

        Args:
            subparsers: Parent subparser collection.
        """
        pass

    def process_command(self, args: Namespace):
        """Execute a no-op command for tests.

        Args:
            args: Parsed CLI arguments.
        """
        pass


class DummyAdapter:
    """Small adapter stub used to validate background-runner resolution."""

    @classmethod
    def run_background_task(cls, **kwargs):
        """Return a recognizable payload for tests.

        Args:
            **kwargs: Background task inputs.

        Returns:
            dict: Echo payload for test assertions.
        """
        return kwargs


class DummyBackgroundCmd(BaseCmd):
    """Concrete command that advertises a background-capable adapter."""

    adapter_class = DummyAdapter

    def add_parser(self, subparsers: ArgumentParser):
        """Register a no-op parser for tests.

        Args:
            subparsers: Parent subparser collection.
        """
        pass

    def process_command(self, args: Namespace):
        """Execute a no-op command for tests.

        Args:
            args: Parsed CLI arguments.
        """
        pass


def test_load_direct_commands_accepts_base_cmd_subclass(monkeypatch):
    """Verify direct-command registrations can point directly at a `BaseCmd` subclass."""

    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"DirectCmd": DummyCmd})(),
    )

    commands = load_direct_commands("provider.direct:DirectCmd")

    assert len(commands) == 1
    assert isinstance(commands[0], DummyCmd)


def test_load_direct_commands_accepts_single_base_cmd_from_factory(monkeypatch):
    """Verify one direct-command factory can return a single `BaseCmd` instance."""

    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"register": staticmethod(lambda: DummyCmd())})(),
    )

    commands = load_direct_commands("provider.direct:register")

    assert len(commands) == 1
    assert isinstance(commands[0], DummyCmd)


def test_load_direct_commands_accepts_base_cmd_instance(monkeypatch):
    """Verify direct-command registrations can point directly at a `BaseCmd` instance."""

    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"direct_cmd": DummyCmd()})(),
    )

    commands = load_direct_commands("provider.direct:direct_cmd")

    assert len(commands) == 1
    assert isinstance(commands[0], DummyCmd)


def test_load_direct_background_runner_resolves_through_command_adapter_class(monkeypatch):
    """Verify background runners are resolved through the direct command's adapter class."""

    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"DirectCmd": DummyBackgroundCmd})(),
    )

    runner = load_direct_background_runner("provider.direct:DirectCmd")

    assert runner(task_id="task-1") == {"task_id": "task-1"}


def test_load_direct_commands_rejects_non_base_cmd_results(monkeypatch):
    """Verify direct-command factories must return `BaseCmd` instances."""

    monkeypatch.setattr(
        "mada_tools.shared.direct_cli.import_module",
        lambda module_path: type("Module", (), {"register": staticmethod(lambda: [object()])})(),
    )

    with pytest.raises(RuntimeError, match="returned object instead of BaseCmd"):
        load_direct_commands("provider.direct:register")
