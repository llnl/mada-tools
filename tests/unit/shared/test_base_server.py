# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `shared/base_server.py` module.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

import mada_tools.shared.base_server as base_mod
from mada_tools.shared import BaseMCPServer
from mada_tools.shared.exceptions import ToolExecutionError


class FastMCPStub:
    """Test double for FastMCP that captures init args and run() calls."""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.run_calls = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


@pytest.fixture
def server() -> BaseMCPServer:
    """
    Provide a minimal `BaseMCPServer` instance for reuse across tests.

    Returns:
        An instance of `BaseMCPServer` for testing.
    """
    return BaseMCPServer("test-server")


class TestBaseMCPServerInit:
    """Unit tests for `BaseMCPServer` initialization behavior."""

    def test_init_sets_server_name(self):
        """It sets `server_name` to the value passed to the constructor."""
        s = BaseMCPServer("alpha")
        assert s.server_name == "alpha"

    def test_init_uses_default_description_when_none(self):
        """It uses the default description template when `description` is not provided."""
        s = BaseMCPServer("alpha")
        assert s.description == "MCP Server for alpha"

    def test_init_uses_provided_description(self):
        """It preserves a caller-provided `description` exactly."""
        s = BaseMCPServer("alpha", description="custom desc")
        assert s.description == "custom desc"

    def test_init_sets_mcp_none(self):
        """It initializes `mcp` to None (it is expected to be set later)."""
        s = BaseMCPServer("alpha")
        assert s.mcp is None


class TestParseArgs:
    """Unit tests for `BaseMCPServer.parse_args()`."""

    def test_parse_args_defaults_when_no_args(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It returns default values when no CLI args are provided.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr("sys.argv", ["prog"])
        args = server.parse_args()
        assert args.host is None
        assert args.port is None
        assert args.config is None
        assert args.transport == "streamable-http"

    def test_parse_args_parses_all_options(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It parses host, port, config, and transport options from argv.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--host",
                "0.0.0.0",
                "--port",
                "1234",
                "--config",
                "/tmp/cfg.json",
                "--transport",
                "stdio",
            ],
        )
        args = server.parse_args()
        assert args.host == "0.0.0.0"
        assert args.port == 1234
        assert args.config == "/tmp/cfg.json"
        assert args.transport == "stdio"

    def test_parse_args_rejects_invalid_transport(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It exits with `SystemExit` when an invalid transport value is provided.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr("sys.argv", ["prog", "--transport", "invalid"])
        with pytest.raises(SystemExit):
            server.parse_args()


class TestRunTool:
    """Unit tests for `BaseMCPServer.run_tool()`."""

    def test_run_tool_returns_payload_when_wrapped_function_succeeds(self, server: BaseMCPServer):
        """It returns the payload from a successful wrapped function."""

        def tool_impl(*args, **kwargs):
            assert args == ("alpha",)
            assert kwargs == {"count": 2}
            return True, "payload"

        assert server.run_tool(tool_impl, "alpha", count=2) == "payload"

    def test_run_tool_raises_tool_execution_error_when_wrapped_function_reports_failure(self, server: BaseMCPServer):
        """It raises `ToolExecutionError` when the wrapped function returns `success=False`."""

        def tool_impl():
            return False, "explicit failure"

        with pytest.raises(
            ToolExecutionError, match=r"Tool execution failed at .*base_server.py:\d+ in run_tool: explicit failure"
        ):
            server.run_tool(tool_impl)

    def test_run_tool_wraps_unexpected_exception_with_location(self, server: BaseMCPServer):
        """It wraps unexpected exceptions with source location details."""

        def tool_impl():
            raise RuntimeError("boom")

        with pytest.raises(
            ToolExecutionError, match=r"Tool execution failed at .*test_base_server.py:.* in tool_impl: boom"
        ):
            server.run_tool(tool_impl)


class TestLoadConfig:
    """Unit tests for BaseMCPServer.load_config()."""

    def test_load_config_returns_server_block_when_present(self, server: BaseMCPServer, shared_testing_dir: Path):
        """
        It returns the server-specific config dict when present under servers[server_key].

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            shared_testing_dir (Path):
                The path to the temporary testing directory for tests of files in the `shared` directory.
        """
        cfg = {"servers": {"my_server": {"a": 1, "b": "two"}}}
        p = shared_testing_dir / "test_load_config_returns_server_block_when_present" / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg), encoding="utf-8")

        result = server.load_config(str(p), "my_server")
        assert result == {"a": 1, "b": "two"}

    def test_load_config_returns_empty_dict_when_server_key_missing(
        self, server: BaseMCPServer, shared_testing_dir: Path
    ):
        """
        It returns an empty dict when the requested server key is not present.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            shared_testing_dir (Path):
                The path to the temporary testing directory for tests of files in the `shared` directory.
        """
        cfg = {"servers": {"other": {"x": 9}}}
        p = shared_testing_dir / "test_load_config_returns_empty_dict_when_server_key_missing" / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg), encoding="utf-8")

        result = server.load_config(str(p), "my_server")
        assert result == {}

    def test_load_config_returns_empty_dict_when_servers_block_missing(
        self, server: BaseMCPServer, shared_testing_dir: Path
    ):
        """
        It returns an empty dict when the config has no 'servers' key.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            shared_testing_dir (Path):
                The path to the temporary testing directory for tests of files in the `shared` directory.
        """
        cfg = {"not_servers": {"my_server": {"a": 1}}}
        p = shared_testing_dir / "test_load_config_returns_empty_dict_when_servers_block_missing" / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg), encoding="utf-8")

        result = server.load_config(str(p), "my_server")
        assert result == {}

    def test_load_config_returns_empty_dict_and_warns_on_missing_file(
        self, server: BaseMCPServer, capsys: LogCaptureFixture
    ):
        """
        It returns {} and prints a warning when the config file cannot be opened.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            capsys (LogCaptureFixture):
                Pytest capsys fixture.
        """
        result = server.load_config("/path/does/not/exist.json", "my_server")
        assert result == {}

        out = capsys.readouterr().out
        assert "Warning: Could not load config" in out

    def test_load_config_returns_empty_dict_and_warns_on_invalid_json(
        self, server: BaseMCPServer, shared_testing_dir: Path, capsys: LogCaptureFixture
    ):
        """
        It returns {} and prints a warning when the config file contains invalid JSON.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            shared_testing_dir (Path):
                The path to the temporary testing directory for tests of files in the `shared` directory.
            capsys (LogCaptureFixture):
                Pytest capsys fixture.
        """
        p = shared_testing_dir / "test_load_config_returns_empty_dict_and_warns_on_invalid_json" / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        result = server.load_config(str(p), "my_server")
        assert result == {}

        out = capsys.readouterr().out
        assert "Warning: Could not load config" in out


class TestExpandEnvVars:
    """Unit tests for `BaseMCPServer.expand_env_vars()`."""

    def test_expand_env_vars_replaces_simple_var_when_set(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It expands ${VAR} to the environment value when VAR is set.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MY_VAR", "hello")
        assert server.expand_env_vars("Value=${MY_VAR}") == "Value=hello"

    def test_expand_env_vars_leaves_unknown_var_unchanged(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It leaves ${VAR} unchanged when VAR is not set and no default is provided.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("MISSING", raising=False)
        assert server.expand_env_vars("Value=${MISSING}") == "Value=${MISSING}"

    def test_expand_env_vars_uses_default_when_missing(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It expands ${VAR:-default} to default when VAR is not set.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("MISSING", raising=False)
        assert server.expand_env_vars("Value=${MISSING:-fallback}") == "Value=fallback"

    def test_expand_env_vars_prefers_env_over_default(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It expands ${VAR:-default} to VAR when VAR is set, ignoring the default.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MY_VAR", "fromenv")
        assert server.expand_env_vars("Value=${MY_VAR:-fallback}") == "Value=fromenv"

    def test_expand_env_vars_multiple_occurrences(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It expands multiple variable references within the same string.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert server.expand_env_vars("a=${A}, b=${B}") == "a=1, b=2"

    def test_expand_env_vars_multiple_occurrences_mixed_missing_and_default(
        self, server: BaseMCPServer, monkeypatch: MonkeyPatch
    ):
        """
        It supports mixtures of set vars, missing vars, and defaults in one string.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("SET", "yes")
        monkeypatch.delenv("UNSET", raising=False)
        assert server.expand_env_vars("x=${SET}, y=${UNSET}, z=${UNSET:-d}") == "x=yes, y=${UNSET}, z=d"

    def test_expand_env_vars_default_allows_empty_string(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It allows an empty default in ${VAR:-} and expands to empty when missing.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("EMPTYDEF", raising=False)
        assert server.expand_env_vars("Value=${EMPTYDEF:-}") == "Value="

    def test_expand_env_vars_preserves_surrounding_text(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It only replaces the ${...} segment, preserving all other characters.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("X", "ABC")
        assert server.expand_env_vars("pre_${X}_post") == "pre_ABC_post"

    def test_expand_env_vars_no_placeholders_returns_original(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It returns the original string if no ${...} patterns are present.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("IRRELEVANT", "ignored")
        s = "nothing to expand here"
        assert server.expand_env_vars(s) == s

    def test_expand_env_vars_does_not_expand_dollar_without_braces(
        self, server: BaseMCPServer, monkeypatch: MonkeyPatch
    ):
        """
        It does not treat $VAR as a placeholder, only ${VAR} is supported.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("VAR", "x")
        assert server.expand_env_vars("Value=$VAR") == "Value=$VAR"

    def test_expand_env_vars_treats_colon_without_dash_as_var_name(
        self, server: BaseMCPServer, monkeypatch: MonkeyPatch
    ):
        """
        It only recognizes the ':-' default syntax, other colons are part of the var name.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("A:B", raising=False)
        assert server.expand_env_vars("Value=${A:B}") == "Value=${A:B}"

    def test_expand_env_vars_var_name_whitespace_is_not_stripped(self, server: BaseMCPServer, monkeypatch: MonkeyPatch):
        """
        It does not strip whitespace in var expressions, matching the implementation.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("SPACED", "ok")
        # Note the spaces inside braces cause lookup of " SPACED " which is unset, so it stays unchanged
        assert server.expand_env_vars("Value=${ SPACED }") == "Value=${ SPACED }"


class TestRunWithArgs:
    """Unit tests for `BaseMCPServer.run_with_args()`."""

    def test_run_with_args_stdio_initializes_fastmcp_without_host_port_and_runs(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
        capsys: LogCaptureFixture,
    ):
        """
        It initializes FastMCP with name only for stdio, registers tools, and runs with stdio transport.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            capsys (LogCaptureFixture):
                Pytest capsys fixture.
        """
        # fmcp = FastMCPStub()
        monkeypatch.setattr(base_mod, "FastMCP", lambda **kwargs: FastMCPStub(**kwargs))

        register_called = {"n": 0}
        server._register_tools = lambda: register_called.__setitem__("n", register_called["n"] + 1)

        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(host="ignored", port=1234, config=None, transport="stdio"),
        )

        server.run_with_args("any")

        assert isinstance(server.mcp, FastMCPStub)
        assert server.mcp.init_kwargs == {"name": "test-server"}
        assert register_called["n"] == 1
        assert server.mcp.run_calls == [{"transport": "stdio"}]

        out = capsys.readouterr().out
        assert "Starting test-server with stdio transport" in out

    def test_run_with_args_streamable_http_uses_args_host_port_and_runs(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
        capsys: LogCaptureFixture,
    ):
        """
        It initializes FastMCP with host/port from CLI args for streamable-http, then runs.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
            capsys (LogCaptureFixture):
                Pytest capsys fixture.
        """
        monkeypatch.setattr(base_mod, "FastMCP", lambda **kwargs: FastMCPStub(**kwargs))

        register_called = {"n": 0}
        server._register_tools = lambda: register_called.__setitem__("n", register_called["n"] + 1)

        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(host="0.0.0.0", port=9000, config=None, transport="streamable-http"),
        )

        server.run_with_args("any")

        assert server.mcp.init_kwargs == {
            "name": "test-server",
        }
        assert register_called["n"] == 1
        assert server.mcp.run_calls == [
            {
                "transport": "streamable-http",
                "host": "0.0.0.0",
                "port": 9000,
                "stateless_http": True,
            }
        ]

        out = capsys.readouterr().out
        assert "Starting test-server with streamable-http on 0.0.0.0:9000" in out

    def test_run_with_args_loads_config_sets_env_vars_with_expansion_without_overwriting(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        It loads config `env_vars`, expands string values, casts non-strings to str, and does
        not overwrite existing env.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(base_mod, "FastMCP", lambda **kwargs: FastMCPStub(**kwargs))

        register_called = {"n": 0}
        server._register_tools = lambda: register_called.__setitem__("n", register_called["n"] + 1)

        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(
                host="localhost",
                port=None,
                config="/tmp/cfg.json",
                transport="streamable-http",
            ),
        )

        monkeypatch.setattr(
            server,
            "load_config",
            lambda path, key: {
                "env_vars": {
                    "A": "${X:-fallback}",
                    "B": 123,
                    "C": "literal",
                },
                "host": "confighost",
                "port": 7777,
            },
        )

        # Expansion behavior
        monkeypatch.delenv("X", raising=False)
        monkeypatch.setattr(server, "expand_env_vars", lambda s: s.replace("${X:-fallback}", "expanded"))

        # Ensure setdefault will not overwrite an existing env var
        monkeypatch.setenv("C", "preexisting")

        # Ensure env is clean for keys we assert
        monkeypatch.delenv("A", raising=False)
        monkeypatch.delenv("B", raising=False)

        server.run_with_args("srv")

        assert os.environ["A"] == "expanded"
        assert os.environ["B"] == "123"
        assert os.environ["C"] == "preexisting"

    def test_run_with_args_prefers_args_transport_over_config_transport(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        It uses args.transport when provided, even if config specifies a different transport.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(base_mod, "FastMCP", lambda **kwargs: FastMCPStub(**kwargs))

        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(host="localhost", port=None, config="/tmp/cfg.json", transport="stdio"),
        )
        monkeypatch.setattr(server, "load_config", lambda path, key: {"transport": "streamable-http"})
        server._register_tools = lambda: None

        server.run_with_args("srv")

        assert server.mcp.init_kwargs == {"name": "test-server"}
        assert server.mcp.run_calls == [{"transport": "stdio"}]

    def test_run_with_args_uses_config_host_port_when_args_missing(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        It falls back to config host/port when args.port is None (and args.host is falsy).

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(base_mod, "FastMCP", lambda **kwargs: FastMCPStub(**kwargs))

        # Force args.host falsy so config host is used
        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(
                host=None,
                port=None,
                config="/tmp/cfg.json",
                transport="streamable-http",
            ),
        )
        monkeypatch.setattr(
            server,
            "load_config",
            lambda path, key: {"host": "confighost", "port": 7777},
        )
        server._register_tools = lambda: None

        server.run_with_args("srv")

        # In FastMCP v3, host and port are passed to run(), not __init__()
        assert server.mcp.init_kwargs == {"name": "test-server"}
        assert len(server.mcp.run_calls) == 1
        assert server.mcp.run_calls[0]["host"] == "confighost"
        assert server.mcp.run_calls[0]["port"] == 7777
        assert server.mcp.run_calls[0]["transport"] == "streamable-http"
        assert server.mcp.run_calls[0]["stateless_http"] is True

    def test_run_with_args_unsupported_transport_raises(
        self,
        server: BaseMCPServer,
        monkeypatch: MonkeyPatch,
    ):
        """
        It raises ValueError for a transport value other than stdio or streamable-http.

        Args:
            server (BaseMCPServer):
                An instance of `BaseMCPServer` for testing.
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(
            server,
            "parse_args",
            lambda: SimpleNamespace(host="localhost", port=None, config=None, transport="weird"),
        )
        server._register_tools = lambda: None

        with pytest.raises(ValueError, match=r"Unsupported transport: weird"):
            server.run_with_args("srv")
