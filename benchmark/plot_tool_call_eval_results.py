#!/usr/bin/env python3
"""Create stacked horizontal bar charts from MCP tool-call eval summaries."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mada_tools_matplotlib")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

DEFAULT_COLORS = [
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#B279A2",
    "#FF9DA6",
    "#9D755D",
    "#BAB0AC",
    "#5F9ED1",
]

FLAVOR_OUTLINE_COLORS = [
    "#1f1f1f",
    "#1b6ca8",
    "#a23b1e",
    "#2f7d32",
    "#8a3fb0",
    "#8c564b",
]

AGGREGATE_SUMMARY_FIELDS = {
    "prompts_passed",
    "prompts_total",
    "pass_rate",
    "score_passed",
    "score_total",
    "score_rate",
}


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise ValueError("Summary JSON must contain a list of row objects")
        return rows

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def case_label(case_id: str) -> str:
    return case_id.replace("_", " ")


def ordered_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    values = []
    for row in rows:
        value = str(row[field])
        if value not in values:
            values.append(value)
    return values


def matrix_for(
    rows: list[dict[str, Any]], value_field: str
) -> tuple[list[str], list[str], dict[tuple[str, str], float], dict[tuple[str, str], dict[str, Any]]]:
    models = ordered_values(rows, "model")
    cases = ordered_values(rows, "case_id")
    values = {}
    row_map = {}
    for row in rows:
        key = (str(row["model"]), str(row["case_id"]))
        values[key] = as_float(row.get(value_field))
        row_map[key] = row
    return models, cases, values, row_map


def flavor_ids_for_row(row: dict[str, Any]) -> list[str]:
    flavor_order = row.get("flavor_order")
    if isinstance(flavor_order, str) and flavor_order:
        try:
            parsed = json.loads(flavor_order)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return parsed

    flavor_ids = []
    for field_name, value in row.items():
        if not field_name.endswith("_total") or field_name in AGGREGATE_SUMMARY_FIELDS or value in (None, ""):
            continue
        prompt_id = field_name[: -len("_total")]
        if f"{prompt_id}_passed" in row:
            flavor_ids.append(prompt_id)
    return flavor_ids


def shared_flavor_order(rows: list[dict[str, Any]]) -> tuple[str, list[str]] | None:
    flavor_orders = [flavor_ids_for_row(row) for row in rows]
    flavor_orders = [order for order in flavor_orders if order]
    if not flavor_orders:
        return None
    first_order = flavor_orders[0]
    if all(order == first_order for order in flavor_orders[1:]):
        return "Flavor order", first_order
    return "Flavor order (summary row 1)", first_order


def add_flavor_order_box(ax: Any, rows: list[dict[str, Any]]) -> None:
    flavor_order_info = shared_flavor_order(rows)
    if flavor_order_info is None:
        return

    label, flavor_order = flavor_order_info
    lines = [label]
    for index, flavor_id in enumerate(flavor_order, start=1):
        color = FLAVOR_OUTLINE_COLORS[(index - 1) % len(FLAVOR_OUTLINE_COLORS)]
        lines.append(f"{index}. {flavor_id} [{color}]")
    ax.text(
        0.985,
        0.985,
        "\n".join(lines),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "#cccccc",
            "alpha": 0.92,
        },
    )


def draw_flavor_outlines(
    ax: Any,
    row: dict[str, Any],
    segment_left: float,
    y_center: float,
    bar_height: float,
    total_value: float,
    axis_span: float,
) -> None:
    cumulative = 0.0
    marker_width = max(axis_span * 0.004, 0.06)
    y_bottom = y_center - (bar_height / 2)
    for flavor_index, prompt_id in enumerate(flavor_ids_for_row(row)):
        outline_color = FLAVOR_OUTLINE_COLORS[flavor_index % len(FLAVOR_OUTLINE_COLORS)]
        flavor_value = as_float(row.get(f"{prompt_id}_passed"))
        flavor_left = segment_left + cumulative
        if flavor_value > 0:
            ax.add_patch(
                Rectangle(
                    (flavor_left, y_bottom),
                    flavor_value,
                    bar_height,
                    fill=False,
                    edgecolor=outline_color,
                    linewidth=1.1,
                    zorder=4,
                )
            )
        else:
            ax.add_patch(
                Rectangle(
                    (flavor_left - (marker_width / 2), y_bottom),
                    marker_width,
                    bar_height,
                    fill=False,
                    edgecolor=outline_color,
                    linewidth=1.1,
                    zorder=4,
                )
            )
        cumulative += flavor_value
        if cumulative > total_value:
            break


def plot_stacked(
    rows: list[dict[str, Any]],
    value_field: str,
    output_path: Path,
    title: str,
    xlabel: str,
    value_format: str,
    legend_title: str,
    draw_flavor_boundaries: bool = False,
    show_flavor_order_box: bool = False,
) -> None:
    models, cases, values, row_map = matrix_for(rows, value_field)
    if not models or not cases:
        raise ValueError("No rows available to plot")

    fig_height = max(3.0, 0.55 * len(models) + 1.9)
    fig_width = max(10.0, 1.5 * len(cases) + 5.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    y_positions = list(range(len(models)))
    max_case_value = max(values.values(), default=0.0)
    axis_span = max(1.0, max_case_value * max(1, len(cases)))
    left = [0.0 for _ in models]
    bar_height = 0.8
    for case_index, case_id in enumerate(cases):
        case_values = [values.get((model, case_id), 0.0) for model in models]
        color = DEFAULT_COLORS[case_index % len(DEFAULT_COLORS)]
        total = sum(case_values)
        nonzero = sum(1 for value in case_values if value > 0)
        label = f"{case_label(case_id)} ({value_format.format(total / nonzero) if nonzero else value_format.format(0)})"
        ax.barh(
            y_positions,
            case_values,
            left=left,
            height=bar_height,
            color=color,
            edgecolor="white",
            linewidth=0.7,
            label=label,
        )
        if draw_flavor_boundaries:
            for model_index, model in enumerate(models):
                row = row_map.get((model, case_id))
                if row is None:
                    continue
                draw_flavor_outlines(
                    ax=ax,
                    row=row,
                    segment_left=left[model_index],
                    y_center=y_positions[model_index],
                    bar_height=bar_height,
                    total_value=case_values[model_index],
                    axis_span=axis_span,
                )
        left = [base + value for base, value in zip(left, case_values)]

    ax.set_yticks(y_positions)
    ax.set_yticklabels(models)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(title, loc="left", fontweight="bold", pad=22)
    ax.grid(axis="x", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    if show_flavor_order_box:
        add_flavor_order_box(ax, rows)

    legend = ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.08),
        ncol=min(3, len(cases)),
        frameon=False,
        title=legend_title,
    )
    legend._legend_box.align = "left"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot MCP tool-call eval summary results.")
    parser.add_argument(
        "--summary",
        required=True,
        type=Path,
        help="Input summary CSV or JSON from mcp_tool_call_eval.py",
    )
    parser.add_argument(
        "--score-output",
        required=True,
        type=Path,
        help="Output image path for score/pass-rate stacked bar chart",
    )
    parser.add_argument(
        "--tokens-output",
        required=True,
        type=Path,
        help="Output image path for token stacked bar chart",
    )
    parser.add_argument(
        "--score-field",
        default="score_passed",
        help="Summary field to plot for score blocks (default: score_passed)",
    )
    parser.add_argument(
        "--token-field",
        default="avg_total_tokens",
        help="Summary field to plot for token blocks (default: avg_total_tokens)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_rows(args.summary)
    score_value_format = "{:.2f}" if args.score_field.endswith("_rate") or args.score_field == "pass_rate" else "{:.0f}"
    score_xlabel = (
        "Stacked score rate across test cases"
        if args.score_field.endswith("_rate") or args.score_field == "pass_rate"
        else "Stacked total score across test cases"
    )

    plot_stacked(
        rows=rows,
        value_field=args.score_field,
        output_path=args.score_output,
        title="MCP Tool-Call Evaluation Score By Model",
        xlabel=score_xlabel,
        value_format=score_value_format,
        legend_title="Test case (mean block score)",
        draw_flavor_boundaries=True,
        show_flavor_order_box=True,
    )
    plot_stacked(
        rows=rows,
        value_field=args.token_field,
        output_path=args.tokens_output,
        title="MCP Tool-Call Evaluation Token Use By Model",
        xlabel="Stacked average total tokens across test cases",
        value_format="{:.0f}",
        legend_title="Test case (mean block value)",
    )

    print(f"Wrote {args.score_output}")
    print(f"Wrote {args.tokens_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
