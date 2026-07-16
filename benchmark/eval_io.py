#!/usr/bin/env python3
"""Shared file helpers for benchmark evaluation scripts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

MODEL_LEVEL_HEADER = """# Shared eval model list that may be used in LLM testing.
# One model per line with corresponding run level.
# Set appropriate levels.
# Comment out any model you may want to omit entirely from eval runs.
# Level\tModel
"""


def parse_model_level(value: str, option_name: str = "--level") -> int:
    """Parse a non-negative model selection level."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{option_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{option_name} must be at least 0")
    return parsed


def load_models_file(path: Path, level: int = 0) -> list[str]:
    """Load model IDs from a file, optionally filtering .tsv rows by level."""
    parse_model_level(str(level), "level")
    if path.suffix.lower() == ".tsv":
        return load_model_levels_file(path, level)
    return load_plain_models_file(path)


def load_plain_models_file(path: Path) -> list[str]:
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


def load_model_levels_file(path: Path, level: int = 0) -> list[str]:
    """Load models from a whitespace-delimited level/model file."""
    selected_level = parse_model_level(str(level), "level")
    model_levels = load_model_levels(path)
    models = [model for model, model_level in model_levels.items() if model_level <= selected_level]
    if not models:
        raise ValueError(f"No enabled models found in {path} at level {selected_level}")
    return models


def load_model_levels(path: Path) -> dict[str, int]:
    """Load enabled model levels from an existing level-aware TSV file."""
    if not path.exists():
        return {}

    levels: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{path}:{line_number}: expected '<level> <model>'")
            levels[parts[1]] = parse_model_level(parts[0], f"{path}:{line_number}: level")
    return levels


def write_model_level_file(path: Path, model_ids: list[str], levels: dict[str, int] | None = None) -> None:
    """Write model IDs as level-aware TSV rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    known_levels = levels or {}
    rows = [MODEL_LEVEL_HEADER]
    rows.extend(f"{known_levels.get(model_id, 0)}\t{model_id}\n" for model_id in model_ids)
    path.write_text("".join(rows), encoding="utf-8")


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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    """Write row dictionaries to CSV using a stable field order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            write_csv_row(writer, row, fields)


def write_csv_row(writer: csv.DictWriter, row: dict[str, Any], fields: list[str]) -> None:
    """Write one row using empty strings for missing fields."""
    writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write row dictionaries as pretty JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")
