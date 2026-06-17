# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

# tests/unit/server_management/test_server_types.py

"""
Tests for the `server_info.py` module.
"""

from pathlib import Path

from mada_tools.server_management.server_info import ServerInfo, ServerStatus


def test_server_status_enum_values():
    """
    Ensure ServerStatus values are stable, since they are persisted as strings.
    """
    assert ServerStatus.STOPPED.value == "stopped"
    assert ServerStatus.STARTING.value == "starting"
    assert ServerStatus.RUNNING.value == "running"
    assert ServerStatus.UNHEALTHY.value == "unhealthy"
    assert ServerStatus.FAILED.value == "failed"


def test_server_info_to_dict_basic():
    """
    Verify basic fields are included and status is serialized as a string.
    """
    info = ServerInfo(
        name="test-server",
        package="my-package",
        module_path="my.package.server",
        status=ServerStatus.RUNNING,
        host="127.0.0.1",
        port=8000,
    )

    data = info.to_dict()

    assert data["name"] == "test-server"
    assert data["package"] == "my-package"
    assert data["module_path"] == "my.package.server"
    assert data["status"] == "running"  # enum converted to value
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8000


def test_server_info_to_dict_converts_path_and_status():
    """
    Verify that log_file becomes a string path and status becomes its value.
    """
    log_path = Path("/tmp/server.log")
    info = ServerInfo(
        name="with-log",
        package="my-package",
        module_path="my.package.server",
        log_file=log_path,
        status=ServerStatus.UNHEALTHY,
    )

    data = info.to_dict()

    assert data["log_file"] == str(log_path)
    assert isinstance(data["log_file"], str)
    assert data["status"] == "unhealthy"


def test_server_info_from_dict_round_trip():
    """
    Round trip: ServerInfo -> dict -> ServerInfo should preserve data types.
    """
    original = ServerInfo(
        name="round-trip",
        package="my-package",
        module_path="my.package.server",
        log_file=Path("/var/log/server.log"),
        env_vars={"FOO": "bar"},
        status=ServerStatus.STARTING,
        url="http://localhost:9000",
        pid=1234,
        host="localhost",
        port=9000,
        started_at="2024-01-01T12:00:00Z",
        last_checked="2024-01-01T12:05:00Z",
    )

    data = original.to_dict()
    restored = ServerInfo.from_dict(dict(data))  # pass a copy so method can modify

    assert restored.name == original.name
    assert restored.package == original.package
    assert restored.module_path == original.module_path
    assert restored.env_vars == original.env_vars
    assert restored.status == original.status
    assert restored.url == original.url
    assert restored.pid == original.pid
    assert restored.host == original.host
    assert restored.port == original.port
    assert restored.started_at == original.started_at
    assert restored.last_checked == original.last_checked

    # types
    assert isinstance(restored.log_file, Path)
    assert restored.log_file == original.log_file
    assert isinstance(restored.status, ServerStatus)


def test_server_info_from_dict_handles_missing_optional_fields():
    """
    Ensure from_dict works when optional fields are absent.
    """
    data = {
        "name": "minimal",
        "package": "my-package",
        "module_path": "my.package.server",
        # no log_file, env_vars, url, pid, port, timestamps
        "status": "stopped",
        "host": "localhost",
    }

    info = ServerInfo.from_dict(dict(data))

    assert info.name == "minimal"
    assert info.package == "my-package"
    assert info.module_path == "my.package.server"
    assert info.status == ServerStatus.STOPPED
    assert info.host == "localhost"
    assert info.log_file is None
    assert info.env_vars is None
    assert info.url is None
    assert info.pid is None
    assert info.port is None
    assert info.started_at is None
    assert info.last_checked is None
