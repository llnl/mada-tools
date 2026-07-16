#!/usr/bin/env python3
"""Discover available LLM model IDs and update eval model list files."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from mada_tools.shared.config import get_config_value, load_json_object_config  # noqa: E402

DEFAULT_BASE_URL = "https://livai-api.llnl.gov/v1"
DEFAULT_TIMEOUT = 30.0
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ALL_OUTPUT = SCRIPT_DIR / "eval_models_all.tsv"
DEFAULT_ENABLED_OUTPUT = SCRIPT_DIR / "eval_models.tsv"
MODEL_LEVEL_HEADER = """# Shared eval model list that may be used in LLM testing.
# One model per line with corresponding run level.
# Set appropriate levels.
# Comment out any model you may want to omit entirely from eval runs.
# Level\tModel
"""


def resolve_api_settings(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve API key and base URL with the same precedence as the eval script."""

    config = load_json_object_config(args.config)
    base_url = args.base_url or get_config_value(config, "base_url") or os.getenv("API_BASE_URL", DEFAULT_BASE_URL)
    api_key = args.api_key or get_config_value(config, "api_key") or os.getenv("API_KEY")

    if not api_key:
        api_key = "dummy" if base_url.startswith(("http://localhost", "http://127.0.0.1")) else None
    if not api_key:
        raise ValueError("API key is required. Provide --api-key, --config, or set API_KEY.")

    return api_key, base_url


def extract_model_ids(payload: Any) -> list[str]:
    """Extract, dedupe, and sort model IDs from a /models response payload."""

    entries = payload
    if isinstance(payload, dict):
        entries = payload.get("data")

    if not isinstance(entries, list):
        raise ValueError("Models response must be a JSON object with a 'data' list or a list of model objects")

    model_ids = sorted(
        {
            str(entry["id"])
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]
        }
    )
    if not model_ids:
        raise ValueError("Models response did not contain any model IDs")
    return model_ids


def fetch_models_payload(base_url: str, api_key: str, timeout: float) -> Any:
    """Fetch the raw payload from an OpenAI-compatible /models endpoint."""

    models_url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(
        models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        message = f"HTTP {exc.code} from {models_url}"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {models_url}: {exc.reason}") from exc

    return payload


def load_existing_model_levels(path: Path) -> dict[str, int]:
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
            try:
                level = int(parts[0])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: level must be an integer") from exc
            if level < 0:
                raise ValueError(f"{path}:{line_number}: level must be at least 0")
            levels[parts[1]] = level
    return levels


def known_model_levels(all_output: Path, enabled_output: Path) -> dict[str, int]:
    """Prefer curated levels, then fall back to the existing discovery snapshot."""
    if enabled_output.exists():
        return load_existing_model_levels(enabled_output)
    return load_existing_model_levels(all_output)


def write_model_file(path: Path, model_ids: list[str], levels: dict[str, int] | None = None) -> None:
    """Write model IDs as level-aware TSV rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    known_levels = levels or {}
    rows = [MODEL_LEVEL_HEADER]
    rows.extend(f"{known_levels.get(model_id, 0)}\t{model_id}\n" for model_id in model_ids)
    path.write_text("".join(rows), encoding="utf-8")


def refresh_model_files(model_ids: list[str], all_output: Path, enabled_output: Path) -> bool:
    """Refresh the discovery snapshot and initialize the curated list if needed."""

    levels = known_model_levels(all_output, enabled_output)
    write_model_file(all_output, model_ids, levels)
    if enabled_output.exists():
        return False
    write_model_file(enabled_output, model_ids, levels)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate shared eval model list files from an OpenAI-compatible API.")
    parser.add_argument("--config", type=Path, help="Optional JSON config with model.api_key and model.base_url")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument(
        "--all-output",
        type=Path,
        default=DEFAULT_ALL_OUTPUT,
        help=f"Write discovered model snapshot to this file (default: {DEFAULT_ALL_OUTPUT})",
    )
    parser.add_argument(
        "--enabled-output",
        type=Path,
        default=DEFAULT_ENABLED_OUTPUT,
        help=f"Initialize curated enabled model list here if missing (default: {DEFAULT_ENABLED_OUTPUT})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds when querying /models (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        api_key, base_url = resolve_api_settings(args)
        payload = fetch_models_payload(base_url, api_key, args.timeout)
        model_ids = extract_model_ids(payload)
        initialized_enabled = refresh_model_files(model_ids, args.all_output, args.enabled_output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    # Uncomment for Raw printout of model dump
    # print("Raw /models response:")
    # print(json.dumps(payload, indent=2, sort_keys=True))
    print("Extracted model IDs:")
    for model_id in model_ids:
        print(model_id)
    print(f"Wrote {len(model_ids)} discovered models to {args.all_output}")
    if initialized_enabled:
        print(f"Initialized curated enabled model list at {args.enabled_output}")
    else:
        print(f"Left curated enabled model list unchanged at {args.enabled_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
