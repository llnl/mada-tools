# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Fixtures for end-to-end tests.
"""

from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.server_management import ServerInfo, ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager


@pytest.fixture
def patch_cli_dependencies(monkeypatch: MonkeyPatch):
    """
    Patch nonessential external boundaries so CLI end-to-end tests remain
    deterministic while still exercising the real command and manager stack.

    Args:
        monkeypatch (MonkeyPatch): Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        "mada_tools.main.setup_logging",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.time.sleep",
        lambda _: None,
    )


@pytest.fixture
def capture_rich_prints(monkeypatch: MonkeyPatch) -> List[Tuple[Any, ...]]:
    """
    Capture Rich Console.print calls so tests can inspect printed objects.

    Args:
        monkeypatch (MonkeyPatch): Pytest monkeypatch fixture.

    Returns:
        list: Captured positional argument tuples from Console.print calls.
    """
    captured = []

    def fake_print(self, *args, **kwargs):
        captured.append(args)

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.Console.print",
        fake_print,
    )
    return captured


@pytest.fixture
def extract_tables():
    """
    A fixture for extracting printed Rich table objects from captured Console.print calls.

    Args:
        captured_prints: Captured Console.print argument tuples.

    Returns:
        A callable function for extracting Rich table outputs from Console.print calls.
    """

    def _extract_tables(captured_prints: List[Tuple[Any, ...]]) -> List[Any]:
        """
        Extract printed Rich Table objects from captured Console.print calls.

        Args:
            captured_prints: Captured Console.print argument tuples.

        Returns:
            list: Printed objects whose class name is Table.
        """
        tables = []
        for args in captured_prints:
            for obj in args:
                if obj.__class__.__name__ == "Table":
                    tables.append(obj)
        return tables

    return _extract_tables


@pytest.fixture
def register_server() -> Callable:
    """
    A fixture for registering servers in a real state file.

    Args:
        state_file: Path to the state file.
        name: Server name.
        pid: Optional process ID.
        status: Server status to persist.
        package: Package name.
        module_path: Python module path.
        host: Host value.
        port: Optional port value.

    Returns:
        A callable function for registering servers.
    """

    def _register_server(
        state_file: Path,
        name: str,
        pid: int | None,
        status: ServerStatus,
        package: str = "fake_pkg",
        module_path: str = "fake_pkg.alpha.server",
        host: str = "127.0.0.1",
        port: int | None = None,
    ):
        """
        Register a server entry in the real state file for status tests.

        Args:
            state_file: Path to the state file.
            name: Server name.
            pid: Optional process ID.
            status: Server status to persist.
            package: Package name.
            module_path: Python module path.
            host: Host value.
            port: Optional port value.
        """
        state_manager = ServerStateManager(state_file=state_file)
        state_manager.register_server(
            ServerInfo(
                name=name,
                package=package,
                module_path=module_path,
                pid=pid,
                host=host,
                port=port,
                status=status,
            ),
            {},
        )
        state_manager.update_server_status(name, status)

    return _register_server
