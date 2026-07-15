#!/usr/bin/env python3
"""Shared file helpers for benchmark evaluation scripts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def load_models_file(path: Path) -> list[str]:
    """Load model IDs from a text file, ignoring blank lines and comments."""
    models = []
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            models.append(line)
    if not models:
        raise ValueError(f"No enabled models found in {path}")
    return models


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list of row objects."""
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, list):
        raise ValueError(f"{path}: expected a JSON list of row objects")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(loaded, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} must be a JSON object")
        rows.append(row)
    return rows


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    """Load CSV rows as dictionaries."""
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: CSV input is missing a header row")
        return list(reader)


def load_csv_or_json_rows(path: Path, *, description: str = "Input") -> list[dict[str, Any]]:
    """Load row dictionaries from JSON when the suffix is .json, otherwise CSV."""
    if path.suffix.lower() == ".json":
        try:
            return load_json_rows(path)
        except ValueError as exc:
            if str(exc).startswith(f"{path}:"):
                raise
            raise ValueError(f"{description} JSON must contain a list of row objects") from exc
    return load_csv_rows(path)
