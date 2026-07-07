"""Unit tests for `shared.env` module."""

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.shared.env import get_env_var


class TestGetEnvVar:
    """Unit tests for `shared.env.get_env_var()`."""

    def test_get_env_var_returns_value_when_set(self, monkeypatch: MonkeyPatch):
        """
        It returns the environment variable value when the variable is present.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("FOO", "bar")
        assert get_env_var("FOO") == "bar"

    def test_get_env_var_returns_default_when_not_set(self, monkeypatch: MonkeyPatch):
        """
        It returns the supplied default when the environment variable is absent.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("FOO", raising=False)
        assert get_env_var("FOO", default="zzz") == "zzz"

    def test_get_env_var_returns_none_when_not_set_and_no_default(self, monkeypatch: MonkeyPatch):
        """
        It returns None when the variable is absent and no default is provided.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("FOO", raising=False)
        assert get_env_var("FOO") is None

    def test_get_env_var_required_true_raises_when_missing_and_no_default(self, monkeypatch: MonkeyPatch):
        """
        It raises ValueError when `required=True` and the variable is missing and has no default.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("REQ", raising=False)
        with pytest.raises(ValueError, match=r"Required environment variable REQ is not set"):
            get_env_var("REQ", required=True)

    def test_get_env_var_required_true_does_not_raise_when_set(self, monkeypatch: MonkeyPatch):
        """
        It does not raise when `required=True` and the variable is present.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("REQ", "present")
        assert get_env_var("REQ", required=True) == "present"

    def test_get_env_var_required_true_does_not_raise_when_default_provided(self, monkeypatch: MonkeyPatch):
        """
        It does not raise when `required=True` but a non-None default is provided.

        Args:
            monkeypatch (MonkeyPatch):
                Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("REQ", raising=False)
        assert get_env_var("REQ", default="fallback", required=True) == "fallback"
