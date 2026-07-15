#!/usr/bin/env python3
"""Create stacked horizontal bar charts from MCP tool-call eval summaries."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mada_tools_matplotlib")

import matplotlib.pyplot as plt  # noqa: E402
from eval_io import load_csv_or_json_rows  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

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
    return load_csv_or_json_rows(path, description="Summary")


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


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


def ordered_flavor_ids(rows: list[dict[str, Any]]) -> list[str]:
    flavor_ids = []
    for row in rows:
        for flavor_id in flavor_ids_for_row(row):
            if flavor_id not in flavor_ids:
                flavor_ids.append(flavor_id)
    return flavor_ids


def flavor_color_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {
        flavor_id: FLAVOR_OUTLINE_COLORS[index % len(FLAVOR_OUTLINE_COLORS)]
        for index, flavor_id in enumerate(ordered_flavor_ids(rows))
    }


def flavor_legend_handles(color_by_flavor: dict[str, str]) -> tuple[str, list[Any]] | None:
    if not color_by_flavor:
        return None

    handles = []
    for flavor_id, color in color_by_flavor.items():
        handles.append(
            Line2D(
                [0],
                [0],
                color=color,
                linewidth=2.2,
                label=flavor_id,
            )
        )
    return "Prompt flavors", handles


def score_axis_label(rows: list[dict[str, Any]], value_field: str, xlabel: str) -> str:
    if value_field.endswith("_rate") or value_field == "pass_rate":
        return xlabel

    total_field = None
    if value_field.startswith("score_"):
        total_field = "score_total"
    elif value_field.startswith("prompts_"):
        total_field = "prompts_total"
    if total_field is None:
        return xlabel

    notes = []
    sample_counts = sorted(
        {
            int(as_float(row["num_samples"]))
            for row in rows
            if row.get("num_samples") not in (None, "")
        }
    )
    if len(sample_counts) == 1:
        suffix = "repetition" if sample_counts[0] == 1 else "repetitions"
        notes.append(f"{sample_counts[0]} {suffix}")
    elif len(sample_counts) > 1:
        notes.append(f"{sample_counts[0]}-{sample_counts[-1]} repetitions")

    totals_by_model: dict[str, float] = {}
    for row in rows:
        model = str(row["model"])
        totals_by_model[model] = totals_by_model.get(model, 0.0) + as_float(row.get(total_field))
    possible_totals = sorted(set(totals_by_model.values()))
    if len(possible_totals) == 1:
        notes.append(f"total possible {format_number(possible_totals[0])}")
    elif len(possible_totals) > 1:
        notes.append(
            f"total possible {format_number(possible_totals[0])}-{format_number(possible_totals[-1])}"
        )

    if not notes:
        return xlabel
    return f"{xlabel} ({', '.join(notes)})"


def draw_flavor_outlines(
    ax: Any,
    row: dict[str, Any],
    segment_left: float,
    y_center: float,
    bar_height: float,
    total_value: float,
    axis_span: float,
    color_by_flavor: dict[str, str],
) -> None:
    cumulative = 0.0
    marker_width = max(axis_span * 0.004, 0.06)
    y_bottom = y_center - (bar_height / 2)
    for prompt_id in flavor_ids_for_row(row):
        outline_color = color_by_flavor.get(prompt_id, FLAVOR_OUTLINE_COLORS[0])
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

    case_legend_columns = min(3, len(cases))
    case_legend_rows = (len(cases) + case_legend_columns - 1) // case_legend_columns
    color_by_flavor = flavor_color_map(rows) if show_flavor_order_box else {}
    flavor_legend = flavor_legend_handles(color_by_flavor) if show_flavor_order_box else None

    fig_height = max(3.0, 0.55 * len(models) + 1.9 + (0.2 * case_legend_rows))
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
                    color_by_flavor=color_by_flavor,
                )
        left = [base + value for base, value in zip(left, case_values)]

    ax.set_yticks(y_positions)
    ax.set_yticklabels(models)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle(title, x=0.08, y=0.96, ha="left", fontweight="bold")
    handles, labels = ax.get_legend_handles_labels()
    case_legend = fig.legend(
        handles=handles,
        labels=labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.9),
        ncol=case_legend_columns,
        frameon=False,
        title=legend_title,
    )
    case_legend._legend_box.align = "left"

    axes_top = max(0.3, 0.82 - (0.08 * case_legend_rows))
    if flavor_legend is not None:
        flavor_title, flavor_handles = flavor_legend
        legend_columns = min(3, len(flavor_handles))
        flavor_order_legend = fig.legend(
            handles=flavor_handles,
            loc="upper right",
            bbox_to_anchor=(0.985, 0.985),
            ncol=legend_columns,
            frameon=False,
            title=flavor_title,
            handlelength=1.8,
            columnspacing=0.9,
            fontsize=9,
            title_fontsize=9,
        )
        flavor_order_legend._legend_box.align = "left"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, axes_top))
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
        xlabel=score_axis_label(rows, args.score_field, score_xlabel),
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
