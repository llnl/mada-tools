# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""JSON configuration helpers shared by scripts and servers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mada_tools.shared.env import expand_env_vars


def load_json_object_config(path: Path | str | None) -> dict[str, Any]:
    """Load a JSON config file that must contain an object at the top level."""
    if path is None:
        return {}

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("Config file must be a JSON object")
    return loaded


def get_config_value(
    config: dict[str, Any],
    key: str,
    section: str | None = "model",
    *,
    expand_env: bool = True,
    missing_env: str = "error",
) -> str | None:
    """Return a string config value from a section first, then the top level."""

    value = None
    if section is not None:
        section_config = config.get(section, {})
        if isinstance(section_config, dict) and isinstance(section_config.get(key), str):
            value = section_config[key]

    if value is None and isinstance(config.get(key), str):
        value = config[key]

    if value is None:
        return None
    if expand_env:
        return expand_env_vars(value, missing=missing_env)
    return value
