#!/usr/bin/env python3
"""Create stacked horizontal bar charts from MCP tool-call eval summaries."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mada_mcp_matplotlib")

import matplotlib.pyplot as plt  # noqa: E402

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
) -> tuple[list[str], list[str], dict[tuple[str, str], float]]:
    models = ordered_values(rows, "model")
    cases = ordered_values(rows, "case_id")
    values = {}
    for row in rows:
        values[(str(row["model"]), str(row["case_id"]))] = as_float(row.get(value_field))
    return models, cases, values


def plot_stacked(
    rows: list[dict[str, Any]],
    value_field: str,
    output_path: Path,
    title: str,
    xlabel: str,
    value_format: str,
) -> None:
    models, cases, values = matrix_for(rows, value_field)
    if not models or not cases:
        raise ValueError("No rows available to plot")

    fig_height = max(3.0, 0.55 * len(models) + 1.9)
    fig_width = max(10.0, 1.5 * len(cases) + 5.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    y_positions = list(range(len(models)))
    left = [0.0 for _ in models]
    for case_index, case_id in enumerate(cases):
        case_values = [values.get((model, case_id), 0.0) for model in models]
        color = DEFAULT_COLORS[case_index % len(DEFAULT_COLORS)]
        total = sum(case_values)
        nonzero = sum(1 for value in case_values if value > 0)
        label = f"{case_label(case_id)} ({value_format.format(total / nonzero) if nonzero else value_format.format(0)})"
        ax.barh(y_positions, case_values, left=left, color=color, edgecolor="white", linewidth=0.7, label=label)
        left = [base + value for base, value in zip(left, case_values)]

    ax.set_yticks(y_positions)
    ax.set_yticklabels(models)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="x", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    legend = ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=min(3, len(cases)),
        frameon=False,
        title="Test case (mean block value)",
    )
    legend._legend_box.align = "left"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
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
        default="pass_rate",
        help="Summary field to plot for score blocks (default: pass_rate)",
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

    plot_stacked(
        rows=rows,
        value_field=args.score_field,
        output_path=args.score_output,
        title="MCP Tool-Call Evaluation Score By Model",
        xlabel="Stacked pass rate across test cases",
        value_format="{:.2f}",
    )
    plot_stacked(
        rows=rows,
        value_field=args.token_field,
        output_path=args.tokens_output,
        title="MCP Tool-Call Evaluation Token Use By Model",
        xlabel="Stacked average total tokens across test cases",
        value_format="{:.0f}",
    )

    print(f"Wrote {args.score_output}")
    print(f"Wrote {args.tokens_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
