#!/usr/bin/env python3
"""Merge sharded MCP tool-call eval row outputs and regenerate summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from eval_io import load_csv_rows, load_json_rows, load_models_file, write_csv, write_json
from run_tool_call_eval import (
    ROW_FIELDS,
    build_work_items,
    exception_messages,
    filter_fixture_prompts,
    load_json,
    parse_num_samples,
    parse_prompt_filter_list,
    print_rows,
    progress,
    summarize,
    summary_fields_for_fixture,
)

KEY_FIELDS = ("model", "server", "case_id", "prompt_id", "sample_index")
OPTIONAL_INT_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms")
OPTIONAL_FLOAT_FIELDS = (
    "input_token_price_usd",
    "output_token_price_usd",
    "input_cost_usd",
    "output_cost_usd",
    "total_cost_usd",
)
TRUE_VALUES = {"1", "true", "t", "yes", "y"}
FALSE_VALUES = {"0", "false", "f", "no", "n"}


def parse_optional_int(value: Any, field_name: str, source: Path) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{source}: field {field_name!r} must be an integer or empty, not boolean")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: field {field_name!r} must be an integer or empty") from exc


def parse_required_int(value: Any, field_name: str, source: Path) -> int:
    parsed = parse_optional_int(value, field_name, source)
    if parsed is None:
        raise ValueError(f"{source}: field {field_name!r} is required")
    return parsed


def parse_optional_float(value: Any, field_name: str, source: Path) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{source}: field {field_name!r} must be a number or empty, not boolean")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: field {field_name!r} must be a number or empty") from exc


def parse_passed(value: Any, source: Path) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
    raise ValueError(f"{source}: field 'passed' must be a boolean or boolean-like string")


def normalize_base_row(row: dict[str, Any], source: Path) -> dict[str, Any]:
    required_fields = [field for field in ROW_FIELDS if field not in OPTIONAL_FLOAT_FIELDS]
    missing_fields = [field for field in required_fields if field not in row]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"{source}: row is missing required fields: {missing}")

    normalized: dict[str, Any] = {
        "model": str(row["model"]),
        "server": str(row["server"]),
        "case_id": str(row["case_id"]),
        "prompt_id": str(row["prompt_id"]),
        "sample_index": parse_required_int(row["sample_index"], "sample_index", source),
        "passed": parse_passed(row["passed"], source),
        "error_type": "" if row["error_type"] is None else str(row["error_type"]),
        "error": "" if row["error"] is None else str(row["error"]),
        "expected_tool": "" if row["expected_tool"] is None else str(row["expected_tool"]),
        "actual_tool": "" if row["actual_tool"] is None else str(row["actual_tool"]),
    }
    for field in OPTIONAL_INT_FIELDS:
        normalized[field] = parse_optional_int(row[field], field, source)
    for field in OPTIONAL_FLOAT_FIELDS:
        normalized[field] = parse_optional_float(row.get(field), field, source)
    return normalized


def row_key(row: dict[str, Any]) -> tuple[str, str, str, str, int]:
    return (
        str(row["model"]),
        str(row["server"]),
        str(row["case_id"]),
        str(row["prompt_id"]),
        int(row["sample_index"]),
    )


def format_key(key: tuple[str, str, str, str, int]) -> str:
    return f"({key[0]!r}, {key[1]!r}, {key[2]!r}, {key[3]!r}, {key[4]!r})"


def expected_key_for_work_item(work_item: Any) -> tuple[str, str, str, str, int]:
    return (
        work_item.model,
        work_item.test_case["server"],
        work_item.test_case["id"],
        work_item.prompt["id"],
        work_item.sample_index,
    )


def canonical_order(
    fixture: dict[str, Any], models: list[str], num_samples: int
) -> tuple[list[tuple[str, str, str, str, int]], dict[tuple[str, str, str, str, int], int]]:
    work_items = build_work_items(fixture, models, num_samples, 1, 0)
    ordered_keys = [expected_key_for_work_item(work_item) for work_item in work_items]
    return ordered_keys, {key: index for index, key in enumerate(ordered_keys)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge sharded MCP tool-call eval rows and regenerate summaries.")
    parser.add_argument("--cases", required=True, type=Path, help="JSON fixture with mcp_servers and tests")
    model_group = parser.add_mutually_exclusive_group(required=True)
    model_group.add_argument("--models", nargs="+", help="Model names used to build the canonical eval matrix")
    model_group.add_argument("--models-file", type=Path, help="File containing model names, one per line")
    parser.add_argument(
        "--num-samples",
        "-n",
        type=parse_num_samples,
        required=True,
        help="Number of tool-call samples collected per prompt flavor",
    )
    row_group = parser.add_mutually_exclusive_group(required=True)
    row_group.add_argument("--rows-json", nargs="+", type=Path, help="Shard JSON row files from --results-json")
    row_group.add_argument("--rows-csv", nargs="+", type=Path, help="Shard CSV row files from --results-csv")
    parser.add_argument("--merged-results-csv", type=Path, help="Write merged per-prompt CSV results")
    parser.add_argument("--merged-results-json", type=Path, help="Write merged detailed JSON results")
    parser.add_argument("--merged-summary-csv", type=Path, help="Write merged per-case summary CSV")
    parser.add_argument("--merged-summary-json", type=Path, help="Write merged per-case summary JSON")
    parser.add_argument(
        "--prompt-ids",
        type=parse_prompt_filter_list,
        help="Comma-separated exact prompt IDs to include",
    )
    parser.add_argument(
        "--prompt-styles",
        type=parse_prompt_filter_list,
        help="Comma-separated root prompt styles to include",
    )
    parser.add_argument(
        "--exclude-prompt-ids",
        type=parse_prompt_filter_list,
        help="Comma-separated exact prompt IDs to exclude",
    )
    parser.add_argument(
        "--exclude-prompt-styles",
        type=parse_prompt_filter_list,
        help="Comma-separated root prompt styles to exclude",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    parser.add_argument("--no-final-table", action="store_true", help="Skip final console result tables")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not any(
        (
            args.merged_results_csv,
            args.merged_results_json,
            args.merged_summary_csv,
            args.merged_summary_json,
        )
    ):
        raise ValueError(
            "At least one output path is required: --merged-results-csv, --merged-results-json, "
            "--merged-summary-csv, or --merged-summary-json"
        )
    if args.rows_csv and args.merged_results_json:
        raise ValueError("--merged-results-json can only be used with --rows-json inputs")


def collect_rows(
    input_paths: list[Path],
    input_mode: str,
    key_to_ordinal: dict[tuple[str, str, str, str, int], int],
) -> tuple[dict[tuple[str, str, str, str, int], dict[str, Any]], dict[tuple[str, str, str, str, int], dict[str, Any]]]:
    base_rows_by_key: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    detailed_rows_by_key: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    key_sources: dict[tuple[str, str, str, str, int], Path] = {}
    duplicate_messages: list[str] = []
    unknown_messages: list[str] = []

    for path in input_paths:
        raw_rows = load_json_rows(path) if input_mode == "json" else load_csv_rows(path)
        for row in raw_rows:
            base_row = normalize_base_row(row, path)
            key = row_key(base_row)
            if key not in key_to_ordinal:
                if len(unknown_messages) < 10:
                    unknown_messages.append(f"{path}: unexpected row key {format_key(key)}")
                continue
            if key in base_rows_by_key:
                if len(duplicate_messages) < 10:
                    duplicate_messages.append(
                        f"duplicate row key {format_key(key)} found in {key_sources[key]} and {path}"
                    )
                continue

            base_rows_by_key[key] = base_row
            key_sources[key] = path
            if input_mode == "json":
                detailed_rows_by_key[key] = row

    errors = []
    if duplicate_messages:
        errors.extend(duplicate_messages)
    if unknown_messages:
        errors.extend(unknown_messages)
    if errors:
        raise ValueError("\n".join(errors))

    return base_rows_by_key, detailed_rows_by_key


def ensure_complete(
    ordered_keys: list[tuple[str, str, str, str, int]],
    base_rows_by_key: dict[tuple[str, str, str, str, int], dict[str, Any]],
) -> None:
    missing = [key for key in ordered_keys if key not in base_rows_by_key]
    if not missing:
        return

    preview = "\n".join(f"missing row key {format_key(key)}" for key in missing[:10])
    suffix = ""
    if len(missing) > 10:
        suffix = f"\n... and {len(missing) - 10} more missing rows"
    raise ValueError(preview + suffix)


def run(args: argparse.Namespace) -> int:
    validate_args(args)
    fixture = load_json(args.cases)
    fixture = filter_fixture_prompts(
        fixture,
        include_prompt_ids=getattr(args, "prompt_ids", None),
        include_prompt_styles=getattr(args, "prompt_styles", None),
        exclude_prompt_ids=getattr(args, "exclude_prompt_ids", None),
        exclude_prompt_styles=getattr(args, "exclude_prompt_styles", None),
    )
    models = args.models if args.models is not None else load_models_file(args.models_file)
    input_paths = args.rows_json if args.rows_json is not None else args.rows_csv
    input_mode = "json" if args.rows_json is not None else "csv"

    ordered_keys, key_to_ordinal = canonical_order(fixture, models, args.num_samples)
    progress(
        f"Merging {len(input_paths)} shard file(s) in {input_mode.upper()} mode for {len(ordered_keys)} expected rows.",
        args.quiet,
    )
    base_rows_by_key, detailed_rows_by_key = collect_rows(input_paths, input_mode, key_to_ordinal)
    ensure_complete(ordered_keys, base_rows_by_key)

    base_rows = [base_rows_by_key[key] for key in ordered_keys]
    summary_rows = summarize(fixture, base_rows, args.num_samples)
    detailed_rows = [detailed_rows_by_key[key] for key in ordered_keys] if input_mode == "json" else []

    if not args.no_final_table:
        print_rows(base_rows, summary_rows)

    output_paths: list[Path] = []
    if args.merged_results_csv:
        write_csv(args.merged_results_csv, base_rows, ROW_FIELDS)
        output_paths.append(args.merged_results_csv)
    if args.merged_results_json:
        write_json(args.merged_results_json, detailed_rows)
        output_paths.append(args.merged_results_json)
    if args.merged_summary_csv:
        write_csv(args.merged_summary_csv, summary_rows, summary_fields_for_fixture(fixture))
        output_paths.append(args.merged_summary_csv)
    if args.merged_summary_json:
        write_json(args.merged_summary_json, summary_rows)
        output_paths.append(args.merged_summary_json)

    detail_message = (
        "preserved detailed JSON rows" if input_mode == "json" else "CSV inputs only; no detailed JSON rows"
    )
    progress(f"Merged {len(base_rows)} rows successfully; {detail_message}.", args.quiet)
    for output_path in output_paths:
        progress(f"Wrote {output_path}", args.quiet)
    return 0


def main() -> int:
    try:
        return run(parse_args())
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
