#!/usr/bin/env python3
"""Generate a readable Markdown report from an MCP tool-call benchmark fixture."""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mcp_tool_call_eval import (  # noqa: E402
    exception_messages,
    expected_call_from_test_case,
    load_json,
    normalize_prompts,
    prompt_style_id,
)


def default_output_path(cases_path: Path) -> Path:
    return cases_path.with_suffix(".md")


def fixture_title(cases_path: Path) -> str:
    return cases_path.stem


def escape_inline_markdown(value: str) -> str:
    replacements = {
        "\\": "\\\\",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "[": "\\[",
        "]": "\\]",
        "<": "\\<",
        ">": "\\>",
        "(": "\\(",
        ")": "\\)",
        "#": "\\#",
        "+": "\\+",
        "-": "\\-",
        ".": "\\.",
        "!": "\\!",
        "|": "\\|",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def heading_text(value: str) -> str:
    return value.replace("\n", " ").strip()


def heading(level: int, value: str) -> str:
    return f"{'#' * level} {heading_text(value)}"


def json_block(value: Any) -> str:
    return f"```json\n{json.dumps(value, indent=2, sort_keys=True)}\n```"


def text_block(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"~~~text\n{text}\n~~~"


def indent_block(block: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else "" for line in block.splitlines())


def compact_json(value: Any, max_length: int = 300) -> str:
    if value in (None, ""):
        return ""
    text = json.dumps(value, sort_keys=True)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def compact_text(value: str, max_length: int = 500) -> str:
    value = " ".join(value.split())
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def group_prompts_by_flavor(prompts: list[dict[str, str]]) -> list[tuple[str, list[dict[str, str]]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    order = []
    for prompt in prompts:
        flavor = prompt_style_id(prompt["id"])
        if flavor not in grouped:
            grouped[flavor] = []
            order.append(flavor)
        grouped[flavor].append(prompt)
    return [(flavor, grouped[flavor]) for flavor in order]


def used_servers_in_order(fixture: dict[str, Any]) -> list[str]:
    servers = []
    for test_case in fixture["tests"]:
        server = test_case["server"]
        if server not in servers:
            servers.append(server)
    return servers


def tests_for_server(fixture: dict[str, Any], server: str) -> list[dict[str, Any]]:
    return [test_case for test_case in fixture["tests"] if test_case["server"] == server]


def format_prompt_text(text: str) -> str:
    return text.replace("\n", "\n  ")


def render_test_case(test_case: dict[str, Any], heading_level: int = 3) -> list[str]:
    expected_call = expected_call_from_test_case(test_case)
    lines = [
        heading(heading_level, f"Test: {test_case['id']}"),
        "",
        f"- MCP server: `{test_case['server']}`",
        f"- Expected tool: `{expected_call.tool}`",
        f"- Match mode: `{expected_call.match_mode}`",
    ]
    if expected_call.match_profile is not None:
        lines.append(f"- Match profile: `{expected_call.match_profile}`")

    lines.extend(
        [
            "",
            heading(heading_level + 1, "Expected Arguments"),
            "",
            json_block(expected_call.arguments),
            "",
            heading(heading_level + 1, "Expected Call"),
            "",
            json_block(test_case["expected_call"]),
            "",
            heading(heading_level + 1, "Prompts"),
            "",
        ]
    )

    for flavor, prompts in group_prompts_by_flavor(normalize_prompts(test_case)):
        lines.extend([heading(heading_level + 2, f"Prompt Flavor: {flavor}"), ""])
        for prompt in prompts:
            prompt_id = escape_inline_markdown(prompt["id"])
            prompt_text = format_prompt_text(prompt["text"])
            lines.append(f"- **{prompt_id}**: {prompt_text}")
        lines.append("")

    return lines


def render_fixture_lines(
    fixture: dict[str, Any],
    cases_path: Path,
    *,
    title_level: int = 1,
    title_prefix: str = "",
) -> list[str]:
    used_servers = used_servers_in_order(fixture)
    lines = [
        heading(title_level, f"{title_prefix}{fixture_title(cases_path)}"),
        "",
        heading(title_level + 1, "Fixture Summary"),
        "",
        f"- Configured MCP servers: {len(fixture['mcp_servers'])}",
        f"- MCP servers used by tests: {len(used_servers)}",
        f"- Test cases: {len(fixture['tests'])}",
        "",
    ]

    for server in used_servers:
        server_tests = tests_for_server(fixture, server)
        lines.extend(
            [
                heading(title_level + 1, f"MCP Server: {server}"),
                "",
                f"- Test cases: {len(server_tests)}",
                "",
                heading(title_level + 2, "Server Config"),
                "",
                json_block(fixture["mcp_servers"][server]),
                "",
            ]
        )
        for test_case in server_tests:
            lines.extend(render_test_case(test_case, heading_level=title_level + 2))

    return lines


def render_report(fixture: dict[str, Any], cases_path: Path) -> str:
    lines = render_fixture_lines(fixture, cases_path)
    return "\n".join(lines).rstrip() + "\n"


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def bool_label(value: Any) -> str:
    return "yes" if bool(value) else "no"


def relative_link(path: Path, report_path: Path) -> str:
    try:
        return path.resolve().relative_to(report_path.parent.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_run_description_lines(
    *,
    run_config_path: Path,
    run_config: dict[str, Any],
    eval_args: Any,
    output_dir: Path,
    eval_status: int,
) -> list[str]:
    models = ", ".join(str(model) for model in eval_args.models)
    shard = f"{eval_args.shard_index + 1}/{eval_args.shard_count}"
    lines = [
        heading(2, "Run Description"),
        "",
        f"- Run config: `{run_config_path}`",
        f"- Cases: `{eval_args.cases}`",
        f"- Output directory: `{output_dir}`",
        f"- Models: {models}",
        f"- Samples per prompt: {eval_args.num_samples}",
        f"- Max concurrency: {eval_args.max_concurrency}",
        f"- Shard: {shard}",
        f"- Strict matching: {bool_label(eval_args.strict)}",
        f"- Eval status: {'passed' if eval_status == 0 else 'failed'} (`{eval_status}`)",
    ]
    if getattr(eval_args, "temperature", None) is not None:
        lines.append(f"- Temperature: {eval_args.temperature}")
    if getattr(eval_args, "request_timeout", None) is not None:
        lines.append(f"- Request timeout: {eval_args.request_timeout}s")
    if getattr(eval_args, "min_pass_rate", None) is not None:
        lines.append(f"- Minimum pass rate: {eval_args.min_pass_rate}")
    if getattr(eval_args, "base_url", None):
        lines.append(f"- API base URL: `{eval_args.base_url}`")
    if getattr(eval_args, "capture_raw_response", None):
        lines.append("- Captured raw responses: yes")
    if eval_args.prompt_ids:
        lines.append(f"- Included prompt IDs: {', '.join(eval_args.prompt_ids)}")
    if eval_args.prompt_styles:
        lines.append(f"- Included prompt styles: {', '.join(eval_args.prompt_styles)}")
    if eval_args.exclude_prompt_ids:
        lines.append(f"- Excluded prompt IDs: {', '.join(eval_args.exclude_prompt_ids)}")
    if eval_args.exclude_prompt_styles:
        lines.append(f"- Excluded prompt styles: {', '.join(eval_args.exclude_prompt_styles)}")
    if run_config.get("name"):
        lines.append(f"- Run name: `{run_config['name']}`")
    lines.append("")
    return lines


def render_plot_lines(plot_paths: list[Path], report_path: Path) -> list[str]:
    lines = [heading(2, "Output Plots"), ""]
    if not plot_paths:
        lines.extend(["No plots were generated.", ""])
        return lines

    for plot_path in plot_paths:
        label = plot_path.stem.replace("_", " ").title()
        link = relative_link(plot_path, report_path)
        lines.extend([f"![{label}]({link})", ""])
    return lines


def failure_signature(row: dict[str, Any]) -> tuple[str, str, str, str]:
    actual_arguments = row.get("actual_arguments")
    if actual_arguments is None:
        actual_arguments = row.get("actual_arguments_raw")
    return (
        str(row.get("error_type") or "unknown"),
        str(row.get("error") or ""),
        str(row.get("actual_tool") or ""),
        compact_json(actual_arguments),
    )


def render_failure_lines(detailed_rows: list[dict[str, Any]]) -> list[str]:
    lines = [heading(2, "Failures"), ""]
    if not detailed_rows:
        lines.extend(["No detailed result rows were available.", ""])
        return lines

    failed_rows = [row for row in detailed_rows if not row.get("passed")]
    if not failed_rows:
        lines.extend(["No failures found.", ""])
        return lines

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in detailed_rows:
        key = (
            str(row.get("model", "")),
            str(row.get("server", "")),
            str(row.get("case_id", "")),
            str(row.get("prompt_id", "")),
        )
        grouped.setdefault(key, []).append(row)

    for key in sorted(grouped):
        prompt_rows = grouped[key]
        prompt_failures = [row for row in prompt_rows if not row.get("passed")]
        if not prompt_failures:
            continue
        model, server, case_id, prompt_id = key
        passed = len(prompt_rows) - len(prompt_failures)
        total = len(prompt_rows)
        expected_call = prompt_failures[0].get("expected_call") or {}
        expected_tool = expected_call.get("tool") or prompt_failures[0].get("expected_tool") or ""
        expected_args = expected_call.get("arguments") or {}
        prompt_text = prompt_failures[0].get("prompt") or ""
        signatures = collections.Counter(failure_signature(row) for row in prompt_failures)

        lines.extend(
            [
                heading(3, f"{model} / {server} / {case_id} / {prompt_id}"),
                "",
                f"- Passed: {passed}/{total}",
                f"- Expected tool: `{expected_tool}`",
                "- Prompt:",
                "",
                text_block(prompt_text),
                "",
                "- Expected arguments:",
                "",
                text_block(compact_json(expected_args)),
                "",
                "- Common failure patterns:",
            ]
        )
        for (error_type, error, actual_tool, actual_args), count in signatures.most_common():
            actual_tool_label = actual_tool or "<none>"
            reason = compact_text(error) if error else "No evaluator error detail"
            lines.extend(
                [
                    f"  - {count}x `{error_type}`: got `{actual_tool_label}`.",
                    "    Reason:",
                    "",
                    indent_block(text_block(reason)),
                    "",
                ]
            )
            if actual_args:
                lines.extend(["    Returned arguments:", "", indent_block(text_block(actual_args)), ""])
        lines.append("")

    return lines


def render_run_report(
    *,
    fixture: dict[str, Any],
    cases_path: Path,
    run_config_path: Path,
    run_config: dict[str, Any],
    eval_args: Any,
    output_dir: Path,
    report_path: Path,
    eval_status: int,
    plot_paths: list[Path],
    detailed_rows: list[dict[str, Any]] | None,
) -> str:
    title = output_dir.name or fixture_title(cases_path)
    lines = [
        heading(1, f"Benchmark Run Report: {title}"),
        "",
        *render_run_description_lines(
            run_config_path=run_config_path,
            run_config=run_config,
            eval_args=eval_args,
            output_dir=output_dir,
            eval_status=eval_status,
        ),
        *render_plot_lines(plot_paths, report_path),
        *render_failure_lines(detailed_rows or []),
        *render_fixture_lines(fixture, cases_path, title_level=2, title_prefix="Benchmark Fixture: "),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_run_report(
    *,
    cases_path: Path,
    run_config_path: Path,
    run_config: dict[str, Any],
    eval_args: Any,
    output_dir: Path,
    report_path: Path,
    eval_status: int,
    plot_paths: list[Path],
    detailed_rows_path: Path | None,
) -> Path:
    fixture = load_json(cases_path)
    detailed_rows = None
    if detailed_rows_path is not None and detailed_rows_path.exists():
        loaded_rows = load_json_file(detailed_rows_path)
        if isinstance(loaded_rows, list):
            detailed_rows = loaded_rows
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_run_report(
            fixture=fixture,
            cases_path=cases_path,
            run_config_path=run_config_path,
            run_config=run_config,
            eval_args=eval_args,
            output_dir=output_dir,
            report_path=report_path,
            eval_status=eval_status,
            plot_paths=plot_paths,
            detailed_rows=detailed_rows,
        ),
        encoding="utf-8",
    )
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Markdown report from an MCP tool-call benchmark fixture.")
    parser.add_argument("--cases", required=True, type=Path, help="JSON fixture with mcp_servers and tests")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write Markdown report here (default: input fixture path with .md suffix)",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    fixture = load_json(args.cases)
    output_path = args.output or default_output_path(args.cases)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(fixture, args.cases), encoding="utf-8")
    print(f"Wrote benchmark fixture report to {output_path}")
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
