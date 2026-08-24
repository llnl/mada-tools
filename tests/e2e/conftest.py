# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Fixtures and helpers shared by repository end-to-end tests.

This layer keeps the pytest-facing convenience fixtures used by end-to-end
tests while delegating the reusable implementation to `mada_tools.testing`.
That split lets extension packages consume the same runner without importing
from the repository's private `tests/` package.
"""

from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest
import pytest_asyncio
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.server_management import ServerInfo, ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager
from mada_tools.testing import AgentTestRunner
from tests.conftest import REPO_DIR


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
    Return a helper that extracts Rich table objects from captured print calls.

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
    Return a helper that registers synthetic servers in a real state file.

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


@pytest_asyncio.fixture
def agent_test_runner():
    """Create repository-relative `AgentTestRunner` instances for e2e tests.

    The packaged runner itself is path-based and reusable by extension packages.
    This fixture keeps only the repository-specific convenience of resolving
    config file names relative to the local `configs/` and `examples/`
    directories.
    """

    async def _create(
        servers_config_file: str,
        agent_config_file: str,
    ):
        """
        Create an async factory for constructing AgentTestRunner instances
        from repository-relative config file names.

        Args:
            servers_config_file: File name under the repository `configs/`
                directory.
            agent_config_file: File name under the repository `examples/`
                directory.

        Returns:
            AgentTestRunner: Configured runner ready to be used as an async
            context manager.
        """
        servers_config_path = REPO_DIR / "configs" / servers_config_file
        agent_config_path = REPO_DIR / "examples" / agent_config_file

        return AgentTestRunner(
            servers_config_path=servers_config_path,
            agent_config_path=agent_config_path,
        )

    return _create
