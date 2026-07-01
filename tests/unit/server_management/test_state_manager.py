# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `state_manager.py` module.
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

import mada_tools.server_management.state_manager as sm
from mada_tools.server_management.server_info import ServerInfo, ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager

# ---------------------------------------
# ---------- Constructor tests ----------
# ---------------------------------------


def test_init_uses_default_state_file_and_creates_parent_dir(
    monkeypatch: MonkeyPatch,
    server_management_testing_dir: Path,
):
    """
    It should default to ~/.mada/server_statuses.json when no state_file is provided,
    and it should create the parent directory if it does not exist.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    fake_home = server_management_testing_dir / "home"
    fake_home.mkdir(parents=True, exist_ok=True)

    # Make Path.home() deterministic
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    mgr = ServerStateManager()

    expected = fake_home / ".mada" / "server_statuses.json"
    assert mgr.state_file == expected
    assert expected.parent.exists()
    assert expected.parent.is_dir()


def test_init_uses_provided_state_file_and_creates_parent_dir(
    server_management_testing_dir: Path,
):
    """
    It should use the provided state_file path verbatim and create its parent
    directory recursively.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    custom_state_file = server_management_testing_dir / "custom_root" / "state" / "servers.json"
    assert not custom_state_file.parent.exists()

    mgr = ServerStateManager(state_file=custom_state_file)

    assert mgr.state_file == custom_state_file
    assert custom_state_file.parent.exists()
    assert custom_state_file.parent.is_dir()


def test_init_accepts_pathlike_and_stores_path_object(
    server_management_testing_dir: Path,
):
    """
    It should store the state_file as a Path instance (this is naturally true
    when passing a Path, and documents the expected type of the attribute).

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    # If you only want to support Path inputs, remove this test.
    # As written, your __init__ type hints Path, so this test enforces Path usage.
    custom_state_file = server_management_testing_dir / "x" / "servers.json"

    mgr = ServerStateManager(state_file=custom_state_file)

    assert isinstance(mgr.state_file, Path)
    assert mgr.state_file.name == "servers.json"


def test_init_idempotent_directory_creation(server_management_testing_dir: Path):
    """
    It should be safe to initialize multiple times using the same state_file,
    even if the directory already exists.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    # Ensure that calling init twice does not error and does not remove the directory
    custom_state_file = server_management_testing_dir / "a" / "b" / "state.json"
    custom_state_file.parent.mkdir(parents=True, exist_ok=True)

    mgr1 = ServerStateManager(state_file=custom_state_file)
    mgr2 = ServerStateManager(state_file=custom_state_file)

    assert mgr1.state_file == custom_state_file
    assert mgr2.state_file == custom_state_file
    assert custom_state_file.parent.exists()


# ---------------------------------------
# ---------- _lock_state tests ----------
# ---------------------------------------


def test_lock_state_acquires_and_releases_lock(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    _lock_state should:
      - open a lock file next to the state file with suffix ".lock"
      - acquire an exclusive lock before yielding
      - release the lock after the context exits

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_lock_state_acquires_and_releases_lock" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    calls = []

    monkeypatch.setattr(
        ServerStateManager,
        "_acquire_file_lock",
        staticmethod(lambda handle: calls.append(("acquire", handle.fileno()))),
    )
    monkeypatch.setattr(
        ServerStateManager,
        "_release_file_lock",
        staticmethod(lambda handle: calls.append(("release", handle.fileno()))),
    )

    lock_path = state_file.with_suffix(".lock")
    assert not lock_path.exists()

    with mgr._lock_state():
        assert lock_path.exists()
        assert lock_path.is_file()

    assert [call[0] for call in calls] == ["acquire", "release"]


def test_lock_state_releases_lock_on_exception(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    _lock_state should always release the lock in a finally block,
    even if an exception occurs inside the context manager.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_lock_state_releases_lock_on_exception" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    calls = []

    monkeypatch.setattr(
        ServerStateManager,
        "_acquire_file_lock",
        staticmethod(lambda handle: calls.append("acquire")),
    )
    monkeypatch.setattr(
        ServerStateManager,
        "_release_file_lock",
        staticmethod(lambda handle: calls.append("release")),
    )

    with pytest.raises(RuntimeError):
        with mgr._lock_state():
            raise RuntimeError("boom")

    assert calls == ["acquire", "release"]


def test_acquire_file_lock_uses_fcntl_when_available(monkeypatch: MonkeyPatch, tmp_path: Path):
    """_acquire_file_lock should use fcntl on Unix-like platforms."""
    calls = []
    fake_fcntl = SimpleNamespace(
        LOCK_EX="lock-ex",
        LOCK_UN="lock-un",
        flock=lambda fd, op: calls.append((fd, op)),
    )

    monkeypatch.setattr(sm, "fcntl", fake_fcntl)
    monkeypatch.setattr(sm, "msvcrt", None)

    lock_path = tmp_path / "fcntl.lock"
    with open(lock_path, "a+b") as handle:
        ServerStateManager._acquire_file_lock(handle)

    assert calls == [(calls[0][0], "lock-ex")]


def test_acquire_file_lock_uses_msvcrt_when_fcntl_missing(monkeypatch: MonkeyPatch, tmp_path: Path):
    """_acquire_file_lock should fall back to msvcrt on Windows."""
    calls = []
    fake_msvcrt = SimpleNamespace(
        LK_LOCK="lock",
        LK_UNLCK="unlock",
        locking=lambda fd, op, size: calls.append((fd, op, size)),
    )

    monkeypatch.setattr(sm, "fcntl", None)
    monkeypatch.setattr(sm, "msvcrt", fake_msvcrt)

    lock_path = tmp_path / "msvcrt.lock"
    with open(lock_path, "a+b") as handle:
        ServerStateManager._acquire_file_lock(handle)

    assert lock_path.read_bytes() == b"\0"
    assert calls == [(calls[0][0], "lock", 1)]


def test_release_file_lock_uses_msvcrt_when_fcntl_missing(monkeypatch: MonkeyPatch, tmp_path: Path):
    """_release_file_lock should release Windows byte-range locks with msvcrt."""
    calls = []
    fake_msvcrt = SimpleNamespace(
        LK_LOCK="lock",
        LK_UNLCK="unlock",
        locking=lambda fd, op, size: calls.append((fd, op, size)),
    )

    monkeypatch.setattr(sm, "fcntl", None)
    monkeypatch.setattr(sm, "msvcrt", fake_msvcrt)

    lock_path = tmp_path / "msvcrt-release.lock"
    lock_path.write_bytes(b"\0")
    with open(lock_path, "a+b") as handle:
        ServerStateManager._release_file_lock(handle)

    assert calls == [(calls[0][0], "unlock", 1)]


# ---------------------------------------
# ---------- _load_state tests ----------
# ---------------------------------------


def test_load_state_returns_empty_when_state_file_missing(
    server_management_testing_dir: Path,
):
    """
    _load_state should return an empty dict when the state file does not exist.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_load_state_returns_empty_when_state_file_missing" / "missing.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    assert not state_file.exists()
    assert mgr._load_state() == {}


def test_load_state_parses_servers_and_calls_from_dict(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    _load_state should:
      - read JSON from the state file
      - iterate data["servers"]
      - call ServerInfo.from_dict for each server entry
      - return mapping of name -> ServerInfo

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_load_state_parses_servers_and_calls_from_dict" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    state_file.write_text(
        json.dumps(
            {
                "servers": {
                    "alpha": {"pid": 111, "host": "127.0.0.1", "port": 8001},
                    "bravo": {"pid": 222, "host": "127.0.0.1", "port": 8002},
                }
            }
        )
    )

    created = {}

    def fake_from_dict(d):
        obj = SimpleNamespace(**d)
        created[d["pid"]] = obj
        return obj

    monkeypatch.setattr(ServerInfo, "from_dict", staticmethod(fake_from_dict))

    servers = mgr._load_state()

    assert set(servers.keys()) == {"alpha", "bravo"}
    assert servers["alpha"].pid == 111
    assert servers["bravo"].pid == 222


def test_load_state_skips_bad_entries_and_logs_warning(
    monkeypatch: MonkeyPatch,
    server_management_testing_dir: Path,
    caplog: LogCaptureFixture,
):
    """
    _load_state should:
      - continue loading other servers when ServerInfo.from_dict raises
      - log a warning mentioning the failing server name

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_load_state_skips_bad_entries_and_logs_warning" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    state_file.write_text(
        json.dumps(
            {
                "servers": {
                    "good": {"pid": 1},
                    "bad": {"pid": "not-an-int"},
                    "good2": {"pid": 2},
                }
            }
        )
    )

    def fake_from_dict(d):
        if d.get("pid") == "not-an-int":
            raise ValueError("invalid pid")
        return SimpleNamespace(**d)

    monkeypatch.setattr(ServerInfo, "from_dict", staticmethod(fake_from_dict))

    caplog.set_level(logging.WARNING)

    servers = mgr._load_state()

    assert set(servers.keys()) == {"good", "good2"}
    assert "Failed to load server 'bad'" in caplog.text


def test_load_state_handles_missing_servers_key(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    _load_state should return an empty dict if the JSON does not contain
    a "servers" key (or it is empty), rather than failing.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_load_state_handles_missing_servers_key" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    state_file.write_text(json.dumps({"not_servers": {"x": 1}}))

    # Ensure we do not accidentally call from_dict
    monkeypatch.setattr(ServerInfo, "from_dict", staticmethod(lambda d: pytest.fail("from_dict called")))

    assert mgr._load_state() == {}


# ---------------------------------------
# ---------- _save_state tests ----------
# ---------------------------------------


def test_save_state_writes_expected_json_and_renames_atomically(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    _save_state should:
      - serialize servers via server.to_dict()
      - write JSON (indent=2) to a .tmp file next to the state_file
      - replace the final state_file with the tmp file atomically

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_save_state" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    alpha = SimpleNamespace(to_dict=lambda: {"pid": 1, "host": "127.0.0.1"})
    bravo = SimpleNamespace(to_dict=lambda: {"pid": 2, "host": "localhost"})
    servers = {"alpha": alpha, "bravo": bravo}

    tmp_path = state_file.with_suffix(".tmp")

    write_calls = []
    replace_calls = []

    def fake_write_text(self: Path, text: str, encoding: str | None = None) -> int:
        write_calls.append((self, text, encoding))
        return len(text)

    def fake_replace(self: Path, target: Path) -> Path:
        replace_calls.append((self, target))
        return target

    monkeypatch.setattr(Path, "write_text", fake_write_text, raising=True)
    monkeypatch.setattr(Path, "replace", fake_replace, raising=True)

    mgr._save_state(servers)

    assert write_calls, "Expected tmp.write_text to be called"
    assert write_calls[0][0] == tmp_path
    assert write_calls[0][2] == "utf-8"

    written_json = write_calls[0][1]
    parsed = json.loads(written_json)
    assert parsed == {
        "servers": {
            "alpha": {"pid": 1, "host": "127.0.0.1"},
            "bravo": {"pid": 2, "host": "localhost"},
        }
    }

    # json.dumps(..., indent=2) should include newlines and two-space indentation
    assert "\n" in written_json
    assert '  "servers"' in written_json

    assert replace_calls == [(tmp_path, state_file)]


def test_save_state_creates_real_state_file_contents(
    server_management_testing_dir: Path,
):
    """
    _save_state should produce a valid JSON file on disk at state_file,
    containing the serialized server mapping.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_save_state_real_io" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    alpha = SimpleNamespace(to_dict=lambda: {"pid": 10})
    servers = {"alpha": alpha}

    mgr._save_state(servers)

    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data == {"servers": {"alpha": {"pid": 10}}}

    # Implementation detail, tmp should not remain after rename in typical FS behavior
    assert not state_file.with_suffix(".tmp").exists()


# -----------------------------------------------
# ---------- _is_process_running tests ----------
# -----------------------------------------------


def test_is_process_running_returns_true_when_psutil_reports_running(
    monkeypatch: MonkeyPatch,
    server_management_testing_dir: Path,
):
    """
    _is_process_running should return True when psutil.Process(pid).is_running()
    returns True.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_is_process_running_returns_true_when_psutil_reports_running"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    class FakeProc:
        def __init__(self, pid: int):
            self.pid = pid

        def is_running(self) -> bool:
            return True

    monkeypatch.setattr(sm.psutil, "Process", lambda pid: FakeProc(pid))

    assert mgr._is_process_running(12345) is True


@pytest.mark.parametrize(
    "exc",
    [
        sm.psutil.NoSuchProcess,  # type: ignore[attr-defined]
        sm.psutil.AccessDenied,  # type: ignore[attr-defined]
        ProcessLookupError,
    ],
)
def test_is_process_running_returns_false_on_expected_exceptions(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path, exc
):
    """
    _is_process_running should return False when psutil raises NoSuchProcess,
    AccessDenied, or ProcessLookupError.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
        exc:
            The exception to raise for this test.
    """
    state_file = (
        server_management_testing_dir / "test_is_process_running_returns_false_on_expected_exceptions" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    def fake_process(pid: int):
        raise exc(pid) if exc is not ProcessLookupError else ProcessLookupError()

    monkeypatch.setattr(sm.psutil, "Process", fake_process)

    assert mgr._is_process_running(99999) is False


def test_is_process_running_propagates_unexpected_exceptions(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    _is_process_running should not swallow unexpected exceptions from psutil.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_is_process_running_propagates_unexpected_exceptions" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    class Unexpected(Exception):
        pass

    def fake_process(pid: int):
        raise Unexpected("boom")

    monkeypatch.setattr(sm.psutil, "Process", fake_process)

    with pytest.raises(Unexpected):
        mgr._is_process_running(1)


# -------------------------------------------
# ---------- _is_port_in_use tests ----------
# -------------------------------------------


def test_is_port_in_use_returns_true_when_connect_ex_returns_zero(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    `_is_port_in_use` should return True when socket.connect_ex returns 0.
    It should also set the provided timeout on the socket.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_is_port_in_use_returns_true_when_connect_ex_returns_zero" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    created = {}

    class FakeSocket:
        def __init__(self, af, socktype):
            created["af"] = af
            created["socktype"] = socktype
            self.timeout = None
            self.connect_args = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect_ex(self, addr):
            self.connect_args = addr
            return 0

    monkeypatch.setattr(sm.socket, "socket", lambda af, socktype: FakeSocket(af, socktype))

    ok = mgr._is_port_in_use("127.0.0.1", 9999, timeout=7)

    assert ok is True
    assert created["af"] == sm.socket.AF_INET
    assert created["socktype"] == sm.socket.SOCK_STREAM


def test_is_port_in_use_returns_false_when_connect_ex_nonzero(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    `_is_port_in_use` should return False when socket.connect_ex returns non-zero.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_is_port_in_use_returns_false_when_connect_ex_nonzero" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            pass

        def connect_ex(self, addr):
            return 111  # any non-zero failure code

    monkeypatch.setattr(sm.socket, "socket", lambda af, socktype: FakeSocket())

    assert mgr._is_port_in_use("localhost", 1234) is False


def test_is_port_in_use_returns_false_on_oserror(
    monkeypatch: MonkeyPatch,
    server_management_testing_dir: Path,
):
    """
    `_is_port_in_use` should return False if socket operations raise OSError.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_is_port_in_use_returns_false_on_oserror" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    class FakeSocket:
        def __enter__(self):
            raise OSError("nope")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(sm.socket, "socket", lambda af, socktype: FakeSocket())

    assert mgr._is_port_in_use("localhost", 1234) is False


# -------------------------------------------
# ---------- register_server tests ----------
# -------------------------------------------


def test_register_server_locks_loads_sets_fields_saves(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    register_server should:
      - acquire _lock_state()
      - load current state
      - set server_info.started_at to an isoformat timestamp
      - set server_info.status to ServerStatus.STARTING
      - insert/overwrite the entry by server_info.name
      - save the updated state

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_register_server_locks_loads_sets_fields_saves" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    events = []

    @contextmanager
    def fake_lock_state():
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")

    existing = {"already": SimpleNamespace(name="already")}

    def fake_load_state():
        events.append("load")
        return dict(existing)

    saved = {}

    def fake_save_state(servers):
        events.append("save")
        saved["servers"] = servers

    fixed_dt = datetime(2030, 1, 2, 3, 4, 5)

    class FixedDateTime:
        @staticmethod
        def now():
            return fixed_dt

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: fake_load_state())
    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: fake_save_state(servers),
    )
    monkeypatch.setattr(sm, "datetime", FixedDateTime)

    server_info = SimpleNamespace(name="new_server", started_at=None, status=None)

    mgr.register_server(server_info=server_info, config={"ignored": True})

    assert events == ["lock-enter", "load", "save", "lock-exit"]

    assert server_info.status == ServerStatus.STARTING
    assert server_info.started_at == fixed_dt.isoformat()

    assert "servers" in saved
    assert set(saved["servers"].keys()) == {"already", "new_server"}
    assert saved["servers"]["new_server"] is server_info


def test_register_server_overwrites_existing_name(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    register_server should overwrite an existing entry with the same name.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_register_server_overwrites_existing_name" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    old = SimpleNamespace(name="dup", started_at="old", status="OLD")
    new = SimpleNamespace(name="dup", started_at=None, status=None)

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: {"dup": old})

    captured = {}

    def fake_save_state(servers):
        captured["servers"] = servers

    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: fake_save_state(servers),
    )

    class FixedDateTime:
        @staticmethod
        def now():
            return datetime(2031, 5, 6, 7, 8, 9)

    monkeypatch.setattr(sm, "datetime", FixedDateTime)

    mgr.register_server(server_info=new, config={})

    assert captured["servers"]["dup"] is new
    assert new.status == ServerStatus.STARTING
    assert new.started_at == datetime(2031, 5, 6, 7, 8, 9).isoformat()


# ------------------------------------------------
# ---------- update_server_status tests ----------
# ------------------------------------------------


def test_update_server_status_updates_status_and_last_checked_and_saves(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    update_server_status should:
      - take the lock
      - load servers
      - if name exists, set .status and .last_checked
      - save updated mapping

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_update_server_status_updates_status_and_last_checked_and_saves"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    events = []

    @contextmanager
    def fake_lock_state():
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")

    target = SimpleNamespace(name="alpha", status=None, last_checked=None)
    other = SimpleNamespace(name="bravo", status="unchanged", last_checked="old")

    def fake_load_state():
        events.append("load")
        return {"alpha": target, "bravo": other}

    captured = {}

    def fake_save_state(servers):
        events.append("save")
        captured["servers"] = servers

    fixed_dt = datetime(2032, 2, 3, 4, 5, 6)

    class FixedDateTime:
        @staticmethod
        def now():
            return fixed_dt

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: fake_load_state())
    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: fake_save_state(servers),
    )
    monkeypatch.setattr(sm, "datetime", FixedDateTime)

    mgr.update_server_status("alpha", ServerStatus.RUNNING)

    assert events == ["lock-enter", "load", "save", "lock-exit"]
    assert target.status == ServerStatus.RUNNING
    assert target.last_checked == fixed_dt.isoformat()

    assert "servers" in captured
    assert captured["servers"]["alpha"] is target
    assert captured["servers"]["bravo"] is other


def test_update_server_status_does_nothing_if_name_missing(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    update_server_status should not call _save_state if the server name is not found.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_update_server_status_does_nothing_if_name_missing" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    save_calls = []

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(
        ServerStateManager,
        "_load_state",
        lambda self: {"bravo": SimpleNamespace(name="bravo")},
    )
    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: save_calls.append(servers),
    )

    mgr.update_server_status("missing", ServerStatus.RUNNING)

    assert save_calls == []


# -----------------------------------------
# ---------- remove_server tests ----------
# -----------------------------------------


def test_remove_server_removes_existing_and_saves_and_returns_true(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    remove_server should delete the entry, save the new mapping, and return True when found.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_remove_server_removes_existing_and_saves_and_returns_true" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    events = []

    @contextmanager
    def fake_lock_state():
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")

    a = SimpleNamespace(name="a")
    b = SimpleNamespace(name="b")

    captured = {}

    def fake_save_state(servers):
        events.append("save")
        captured["servers"] = servers

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: {"a": a, "b": b})
    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: fake_save_state(servers),
    )

    ok = mgr.remove_server("a")

    assert ok is True
    assert events == ["lock-enter", "save", "lock-exit"]
    assert set(captured["servers"].keys()) == {"b"}
    assert captured["servers"]["b"] is b


def test_remove_server_returns_false_and_does_not_save_when_missing(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    remove_server should return False and not call _save_state when name is not found.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_remove_server_returns_false_and_does_not_save_when_missing" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    save_calls = []

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: {"x": SimpleNamespace(name="x")})
    monkeypatch.setattr(
        ServerStateManager,
        "_save_state",
        lambda self, servers: save_calls.append(servers),
    )

    ok = mgr.remove_server("missing")

    assert ok is False
    assert save_calls == []


# --------------------------------------
# ---------- get_server tests ----------
# --------------------------------------


def test_get_server_returns_server_when_present(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """
    get_server should return the ServerInfo when name exists, otherwise None.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_get_server_returns_server_when_present" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    target = SimpleNamespace(name="alpha")
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: {"alpha": target})

    assert mgr.get_server("alpha") is target
    assert mgr.get_server("missing") is None


# ---------------------------------------
# ---------- get_servers tests ----------
# ---------------------------------------


def test_get_servers_validate_false_returns_loaded_mapping_without_checks(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    get_servers(validate=False) should:
      - lock
      - load state
      - return the mapping as-is
      - not call validation helpers or save

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_get_servers_validate_false_returns_loaded_mapping_without_checks"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    servers = {"alpha": SimpleNamespace(name="alpha", pid=1, port=1234, host="127.0.0.1", status="X")}

    load_calls = []
    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(
        ServerStateManager,
        "_load_state",
        lambda self: load_calls.append(True) or servers,
    )

    is_running_calls = []
    port_in_use_calls = []
    save_calls = []

    monkeypatch.setattr(
        ServerStateManager,
        "_is_process_running",
        lambda self, pid: is_running_calls.append(pid) or True,
    )
    monkeypatch.setattr(
        ServerStateManager,
        "_is_port_in_use",
        lambda self, host, port, timeout=2: port_in_use_calls.append((host, port, timeout)) or True,
    )
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=False)

    assert out is servers
    assert len(load_calls) == 1
    assert is_running_calls == []
    assert port_in_use_calls == []
    assert save_calls == []


def test_get_servers_sets_running_when_pid_running_and_port_healthy_and_saves_when_changed(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    When validate=True and PID is running and port health is OK:
      - status should become RUNNING if not already
      - _save_state should be called if any status changed

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_get_servers_sets_running_when_pid_running_and_port_healthy_and_saves_when_changed"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    s1 = SimpleNamespace(name="s1", pid=123, port=8000, host="127.0.0.1", status=ServerStatus.STARTING)
    servers = {"s1": s1}

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: servers)

    monkeypatch.setattr(ServerStateManager, "_is_process_running", lambda self, pid: True)

    health_calls = []
    monkeypatch.setattr(
        ServerStateManager,
        "_is_port_in_use",
        lambda self, host, port, timeout=2: health_calls.append((host, port, timeout)) or True,
    )

    save_calls = []
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=True)

    assert out is servers
    assert s1.status == ServerStatus.RUNNING
    assert health_calls == [("127.0.0.1", 8000, 2)]
    assert save_calls == [servers]


def test_get_servers_sets_unhealthy_when_pid_running_but_port_unhealthy(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    When validate=True and PID is running but port check fails:
      - status should become UNHEALTHY if not already
      - should save when changed

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_get_servers_sets_unhealthy_when_pid_running_but_port_unhealthy"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    s1 = SimpleNamespace(name="s1", pid=123, port=8001, host="localhost", status=ServerStatus.RUNNING)
    servers = {"s1": s1}

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: servers)
    monkeypatch.setattr(ServerStateManager, "_is_process_running", lambda self, pid: True)
    monkeypatch.setattr(ServerStateManager, "_is_port_in_use", lambda self, host, port, timeout=2: False)

    save_calls = []
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=True)

    assert out is servers
    assert s1.status == ServerStatus.UNHEALTHY
    assert save_calls == [servers]


def test_get_servers_sets_running_when_pid_running_and_no_port(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    When validate=True and PID is running and port is falsy:
      - should not call _is_port_in_use
      - status should become RUNNING if not already
      - should save if changed

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_get_servers_sets_running_when_pid_running_and_no_port" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    s1 = SimpleNamespace(name="s1", pid=123, port=None, host="127.0.0.1", status=ServerStatus.STARTING)
    servers = {"s1": s1}

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: servers)
    monkeypatch.setattr(ServerStateManager, "_is_process_running", lambda self, pid: True)

    health_calls = []
    monkeypatch.setattr(
        ServerStateManager,
        "_is_port_in_use",
        lambda self, host, port, timeout=2: health_calls.append((host, port, timeout)) or True,
    )

    save_calls = []
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=True)

    assert out is servers
    assert s1.status == ServerStatus.RUNNING
    assert health_calls == []
    assert save_calls == [servers]


def test_get_servers_sets_stopped_and_clears_pid_when_process_not_running(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    When validate=True and PID is not running (or pid is falsy):
      - status should become STOPPED if not already
      - pid should be set to None
      - should save if changed

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_get_servers_sets_stopped_and_clears_pid_when_process_not_running"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    s1 = SimpleNamespace(name="s1", pid=999, port=8000, host="127.0.0.1", status=ServerStatus.RUNNING)
    servers = {"s1": s1}

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: servers)
    monkeypatch.setattr(ServerStateManager, "_is_process_running", lambda self, pid: False)

    save_calls = []
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=True)

    assert out is servers
    assert s1.status == ServerStatus.STOPPED
    assert s1.pid is None
    assert save_calls == [servers]


def test_get_servers_does_not_save_when_no_status_changes(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    get_servers(validate=True) should not call _save_state if no server status or pid changes occur.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = server_management_testing_dir / "test_get_servers_does_not_save_when_no_status_changes" / "state.json"
    mgr = ServerStateManager(state_file=state_file)

    @contextmanager
    def fake_lock_state():
        yield

    s1 = SimpleNamespace(name="s1", pid=111, port=8000, host="127.0.0.1", status=ServerStatus.RUNNING)
    s2 = SimpleNamespace(name="s2", pid=None, port=None, host="127.0.0.1", status=ServerStatus.STOPPED)
    servers = {"s1": s1, "s2": s2}

    monkeypatch.setattr(ServerStateManager, "_lock_state", lambda self: fake_lock_state())
    monkeypatch.setattr(ServerStateManager, "_load_state", lambda self: servers)
    monkeypatch.setattr(ServerStateManager, "_is_process_running", lambda self, pid: True)
    monkeypatch.setattr(ServerStateManager, "_is_port_in_use", lambda self, host, port, timeout=2: True)

    save_calls = []
    monkeypatch.setattr(ServerStateManager, "_save_state", lambda self, s: save_calls.append(s))

    out = mgr.get_servers(validate=True)

    assert out is servers
    assert s1.status == ServerStatus.RUNNING
    assert s2.status == ServerStatus.STOPPED
    assert save_calls == []


# -----------------------------------------------
# ---------- get_running_servers tests ----------
# -----------------------------------------------


def test_get_running_servers_filters_only_active_pid_and_allowed_statuses(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    get_running_servers should:
      - call get_servers(validate=validate)
      - return only entries where:
          - server_info.pid is truthy
          - server_info.status is in {RUNNING, UNHEALTHY, STARTING}

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir
        / "test_get_running_servers_filters_only_active_pid_and_allowed_statuses"
        / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    s_running = SimpleNamespace(name="running", pid=1, status=ServerStatus.RUNNING)
    s_unhealthy = SimpleNamespace(name="unhealthy", pid=2, status=ServerStatus.UNHEALTHY)
    s_starting = SimpleNamespace(name="starting", pid=3, status=ServerStatus.STARTING)

    s_stopped = SimpleNamespace(name="stopped", pid=None, status=ServerStatus.STOPPED)
    s_has_pid_but_stopped = SimpleNamespace(name="pid_but_stopped", pid=4, status=ServerStatus.STOPPED)
    s_running_but_pid_none = SimpleNamespace(name="running_pid_none", pid=None, status=ServerStatus.RUNNING)

    all_servers = {
        "running": s_running,
        "unhealthy": s_unhealthy,
        "starting": s_starting,
        "stopped": s_stopped,
        "pid_but_stopped": s_has_pid_but_stopped,
        "running_pid_none": s_running_but_pid_none,
    }

    calls = []

    def fake_get_servers(validate: bool = True):
        calls.append(validate)
        return all_servers

    monkeypatch.setattr(
        ServerStateManager,
        "get_servers",
        lambda self, validate=True: fake_get_servers(validate),
    )

    out = mgr.get_running_servers(validate=False)

    assert calls == [False]
    assert set(out.keys()) == {"running", "unhealthy", "starting"}
    assert out["running"] is s_running
    assert out["unhealthy"] is s_unhealthy
    assert out["starting"] is s_starting


def test_get_running_servers_passes_validate_true_by_default(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    get_running_servers(validate default) should call get_servers(validate=True).

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_get_running_servers_passes_validate_true_by_default" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    calls = []

    monkeypatch.setattr(
        ServerStateManager,
        "get_servers",
        lambda self, validate=True: calls.append(validate) or {},
    )

    out = mgr.get_running_servers()

    assert out == {}
    assert calls == [True]


# -----------------------------------------
# ---------- cleanup_stale tests ----------
# -----------------------------------------


def test_cleanup_stale_calls_get_running_servers_with_validate_true(
    monkeypatch: MonkeyPatch, server_management_testing_dir: Path
):
    """
    cleanup_stale should call get_running_servers(validate=True).

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the
            `server_management` directory.
    """
    state_file = (
        server_management_testing_dir / "test_cleanup_stale_calls_get_running_servers_with_validate_true" / "state.json"
    )
    mgr = ServerStateManager(state_file=state_file)

    calls = []

    monkeypatch.setattr(
        ServerStateManager,
        "get_running_servers",
        lambda self, validate=True: calls.append(validate) or {},
    )

    mgr.cleanup_stale()

    assert calls == [True]
