#!/usr/bin/env python3
"""Run MCP tool-call evaluations from a JSON run configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from eval_io import load_models_file  # noqa: E402
from mcp_tool_call_eval import (  # noqa: E402
    DEFAULT_SYSTEM_PROMPT,
    exception_messages,
    parse_max_concurrency,
    parse_num_samples,
    parse_shard_count,
    parse_shard_index,
)
from mcp_tool_call_eval import (  # noqa: E402
    run as run_evaluator,
)
from plot_tool_call_eval_results import (  # noqa: E402
    axis_label_with_case_count,
    format_usd,
    has_numeric_value,
    load_rows,
    plot_stacked,
    score_axis_label,
    sum_numeric_values,
)

from mada_tools.shared.env import expand_env_vars  # noqa: E402

DEFAULT_SCORE_FIELD = "score_passed"
DEFAULT_TOKEN_FIELD = "avg_total_tokens"
DEFAULT_COST_FIELD = "total_cost_usd"
DEFAULT_MODEL_PRICES_PATH = Path(__file__).resolve().with_name("model_prices_and_context_window.json")


def expand_config_env(value: Any) -> Any:
    """Recursively expand environment placeholders in JSON config values."""
    if isinstance(value, str):
        return expand_env_vars(value, missing="error")
    if isinstance(value, list):
        return [expand_config_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_config_env(item) for key, item in value.items()}
    return value


def load_run_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("Run config must be a JSON object")
    return expand_config_env(loaded)


def path_from_config(config_dir: Path, value: Any, field_name: str, required: bool = False) -> Path | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"Run config field {field_name!r} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"Run config field {field_name!r} must be a string path")

    path = Path(value)
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def bool_config(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Expected boolean config value, got {type(value).__name__}")


def int_config(value: Any, default: int, parser: Any) -> int:
    if value is None:
        return default
    return parser(str(value))


def float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def optional_string(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Run config field {field_name!r} must be a string")
    return value


def models_from_config(config: dict[str, Any], config_dir: Path, models_file_override: Path | None) -> list[str]:
    if models_file_override is not None:
        return load_models_file(models_file_override)

    if "models" in config:
        models = config["models"]
        if not isinstance(models, list) or not all(isinstance(model, str) and model for model in models):
            raise ValueError("Run config field 'models' must be a non-empty list of model strings")
        if not models:
            raise ValueError("Run config field 'models' must not be empty")
        return models

    models_file = path_from_config(config_dir, config.get("models_file"), "models_file", required=True)
    assert models_file is not None
    return load_models_file(models_file)


def output_path(output_dir: Path, prefix: str, suffix: str, enabled: bool) -> Path | None:
    if not enabled:
        return None
    return output_dir / f"{prefix}_{suffix}"


def build_output_dir(config: dict[str, Any], config_dir: Path, output_dir_override: Path | None) -> Path:
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")

    base_dir = output_dir_override or path_from_config(config_dir, output_config.get("directory", "results"),
                                                        "output.directory")
    assert base_dir is not None

    timestamped = bool_config(output_config.get("timestamped"), True)
    run_name = str(config.get("name") or "tool_call_eval")
    if timestamped:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return base_dir / f"{run_name}_{timestamp}"
    return base_dir


def build_eval_args(
    config: dict[str, Any],
    config_dir: Path,
    cli_args: argparse.Namespace,
    output_dir: Path,
    models: list[str],
) -> argparse.Namespace:
    eval_config = config.get("eval", {})
    output_config = config.get("output", {})
    model_api_config = config.get("model_api", {})
    if not isinstance(eval_config, dict):
        raise ValueError("Run config field 'eval' must be an object when provided")
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")
    if not isinstance(model_api_config, dict):
        raise ValueError("Run config field 'model_api' must be an object when provided")

    prefix = str(output_config.get("prefix") or "tool_call")
    cases = path_from_config(config_dir, config.get("cases"), "cases", required=True)
    api_config = path_from_config(config_dir, model_api_config.get("config"), "model_api.config")
    model_prices = path_from_config(
        config_dir,
        config.get("model_prices", str(DEFAULT_MODEL_PRICES_PATH)),
        "model_prices",
    )

    return argparse.Namespace(
        cases=cases,
        config=api_config,
        models=models,
        base_url=optional_string(model_api_config.get("base_url"), "model_api.base_url"),
        api_key=optional_string(model_api_config.get("api_key"), "model_api.api_key"),
        system_prompt=optional_string(config.get("system_prompt"), "system_prompt") or DEFAULT_SYSTEM_PROMPT,
        temperature=float_or_none(eval_config.get("temperature")),
        request_timeout=float(eval_config.get("request_timeout", 120.0)),
        max_concurrency=cli_args.max_concurrency
        if cli_args.max_concurrency is not None
        else int_config(eval_config.get("max_concurrency"), 1, parse_max_concurrency),
        num_samples=cli_args.num_samples
        if cli_args.num_samples is not None
        else int_config(eval_config.get("num_samples"), 1, parse_num_samples),
        shard_count=cli_args.shard_count
        if cli_args.shard_count is not None
        else int_config(eval_config.get("shard_count"), 1, parse_shard_count),
        shard_index=cli_args.shard_index
        if cli_args.shard_index is not None
        else int_config(eval_config.get("shard_index"), 0, parse_shard_index),
        strict=bool_config(eval_config.get("strict"), False),
        min_pass_rate=float_or_none(eval_config.get("min_pass_rate")),
        results_csv=output_path(output_dir, prefix, "rows.csv",
                                 bool_config(output_config.get("results_csv"), True)),
        results_json=output_path(output_dir, prefix, "rows.json",
                                  bool_config(output_config.get("results_json"), True)),
        summary_csv=output_path(output_dir, prefix, "summary.csv",
                                 bool_config(output_config.get("summary_csv"), True)),
        summary_json=output_path(output_dir, prefix, "summary.json",
                                  bool_config(output_config.get("summary_json"), True)),
        model_prices=model_prices,
        quiet=cli_args.quiet or bool_config(output_config.get("quiet"), False),
        no_final_table=bool_config(output_config.get("no_final_table"), False),
        capture_raw_response=bool_config(output_config.get("capture_raw_response"), False),
    )


def plots_enabled(config: dict[str, Any], cli_args: argparse.Namespace) -> bool:
    if cli_args.no_plots:
        return False
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")
    return bool_config(output_config.get("plots"), True)


def generate_plots(config: dict[str, Any], output_dir: Path, summary_csv: Path, quiet: bool) -> None:
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")

    prefix = str(output_config.get("prefix") or "tool_call")
    score_field = str(output_config.get("score_field") or DEFAULT_SCORE_FIELD)
    token_field = str(output_config.get("token_field") or DEFAULT_TOKEN_FIELD)
    cost_field = str(output_config.get("cost_field") or DEFAULT_COST_FIELD)
    score_output = output_dir / f"{prefix}_score.png"
    tokens_output = output_dir / f"{prefix}_tokens.png"
    cost_output = output_dir / f"{prefix}_cost.png"

    rows = load_rows(summary_csv)
    score_value_format = "{:.2f}" if score_field.endswith("_rate") or score_field == "pass_rate" else "{:.0f}"
    score_xlabel = (
        "Stacked score rate across test cases"
        if score_field.endswith("_rate") or score_field == "pass_rate"
        else "Stacked total score across test cases"
    )

    plot_stacked(
        rows=rows,
        value_field=score_field,
        output_path=score_output,
        title="MCP Tool-Call Evaluation Score By Model",
        xlabel=score_axis_label(rows, score_field, score_xlabel),
        value_format=score_value_format,
        legend_title="Test case (mean block score)",
        draw_flavor_boundaries=True,
        show_flavor_order_box=True,
    )
    plot_stacked(
        rows=rows,
        value_field=token_field,
        output_path=tokens_output,
        title="MCP Tool-Call Evaluation Token Use By Model",
        xlabel=axis_label_with_case_count(rows, "Stacked average total tokens across test cases"),
        value_format="{:.0f}",
        legend_title="Test case (mean block value)",
        draw_flavor_boundaries=True,
        show_flavor_order_box=True,
    )
    wrote_cost_plot = False
    if has_numeric_value(rows, cost_field):
        total_cost = sum_numeric_values(rows, cost_field)
        plot_stacked(
            rows=rows,
            value_field=cost_field,
            output_path=cost_output,
            title=f"MCP Tool-Call Evaluation Cost By Model (Total: {format_usd(total_cost)})",
            xlabel=axis_label_with_case_count(rows, "Stacked actual cost across test cases (USD)"),
            value_format="{:.6f}",
            legend_title="Test case",
            show_legend_values=False,
        )
        wrote_cost_plot = True

    if not quiet:
        print(f"Wrote {score_output}")
        print(f"Wrote {tokens_output}")
        if wrote_cost_plot:
            print(f"Wrote {cost_output}")
        else:
            print(f"Skipping cost plot because {cost_field!r} has no numeric values.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MCP tool-call evaluation from a JSON run config.")
    parser.add_argument("--run-config", required=True, type=Path, help="JSON run configuration")
    parser.add_argument("--models-file", type=Path, help="Override run config model file")
    parser.add_argument("--num-samples", "-n", type=parse_num_samples, help="Override number of samples")
    parser.add_argument("--max-concurrency", "-c", type=parse_max_concurrency, help="Override max concurrency")
    parser.add_argument("--shard-count", type=parse_shard_count, help="Override shard count")
    parser.add_argument("--shard-index", type=parse_shard_index, help="Override shard index")
    parser.add_argument("--output-dir", type=Path, help="Override base output directory")
    parser.add_argument("--no-plots", action="store_true", help="Disable plot generation")
    parser.add_argument("--quiet", action="store_true", help="Suppress live progress output")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config_path = args.run_config.resolve()
    config = load_run_config(config_path)
    config_dir = config_path.parent

    models_file_override = args.models_file.resolve() if args.models_file is not None else None
    output_dir_override = args.output_dir.resolve() if args.output_dir is not None else None
    models = models_from_config(config, config_dir, models_file_override)
    output_dir = build_output_dir(config, config_dir, output_dir_override)
    eval_args = build_eval_args(config, config_dir, args, output_dir, models)

    eval_status = await run_evaluator(eval_args)
    if plots_enabled(config, args):
        if eval_args.summary_csv is not None and eval_args.summary_csv.exists():
            generate_plots(config, output_dir, eval_args.summary_csv, eval_args.quiet)
        elif not eval_args.quiet:
            print(f"Skipping plot generation because {eval_args.summary_csv} was not created.", file=sys.stderr)

    if not eval_args.quiet:
        print(f"Wrote eval results to {output_dir}")
    return eval_status


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print("Error:", file=sys.stderr)
        for message in exception_messages(exc):
            for line in str(message).splitlines():
                print(f"  - {line}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
