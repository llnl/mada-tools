# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

""" """

import sys

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.main import main


def test_main_version_flag_exits_successfully(monkeypatch: MonkeyPatch):
    """
    End-to-end test, verify the CLI version flag is handled by argument parsing
    and exits successfully before command execution.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "--version",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
