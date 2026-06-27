#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  echo "Usage: ./testflux.sh [--modelfile PATH] [-n NUM_SAMPLES|--num-samples NUM_SAMPLES]"
  echo "Model file precedence: --modelfile > MCP_EVAL_MODELS_FILE > eval_models.txt"
}

cli_models_file=""
num_samples=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --modelfile)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --modelfile" >&2
        usage >&2
        exit 1
      fi
      cli_models_file="$2"
      shift 2
      ;;
    --modelfile=*)
      cli_models_file="${1#--modelfile=}"
      if [[ -z "$cli_models_file" ]]; then
        echo "Missing value for --modelfile" >&2
        usage >&2
        exit 1
      fi
      shift
      ;;
    -n|--num-samples)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        usage >&2
        exit 1
      fi
      num_samples="$2"
      shift 2
      ;;
    --num-samples=*)
      num_samples="${1#--num-samples=}"
      if [[ -z "$num_samples" ]]; then
        echo "Missing value for --num-samples" >&2
        usage >&2
        exit 1
      fi
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

models_file="${cli_models_file:-${MCP_EVAL_MODELS_FILE:-eval_models.txt}}"
if [[ ! -f "$models_file" ]]; then
  echo "Model list file not found: $models_file" >&2
  exit 1
fi

models=()
while IFS= read -r line; do
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  if [[ -z "$line" || "${line:0:1}" == "#" ]]; then
    continue
  fi
  models+=("$line")
done < "$models_file"

if [[ "${#models[@]}" -eq 0 ]]; then
  echo "No enabled models found in $models_file" >&2
  exit 1
fi

timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
output_dir="results/flux_${timestamp}"
mkdir -p "$output_dir"

eval_status=0
python mcp_tool_call_eval.py \
  --cases flux_tool_call_eval_cases.json \
  --models "${models[@]}" \
  --num-samples "$num_samples" \
  --results-csv "$output_dir/flux_tool_call_rows.csv" \
  --results-json "$output_dir/flux_tool_call_rows.json" \
  --summary-csv "$output_dir/flux_tool_call_summary.csv" \
  --summary-json "$output_dir/flux_tool_call_summary.json" \
  --capture-raw-response || eval_status=$?

if [[ -f "$output_dir/flux_tool_call_summary.csv" ]]; then
  python plot_tool_call_eval_results.py \
    --summary "$output_dir/flux_tool_call_summary.csv" \
    --score-output "$output_dir/flux_tool_call_score.png" \
    --tokens-output "$output_dir/flux_tool_call_tokens.png"
else
  echo "Skipping plot generation because $output_dir/flux_tool_call_summary.csv was not created." >&2
fi

echo "Wrote Flux eval results and plots to $output_dir"
exit "$eval_status"
