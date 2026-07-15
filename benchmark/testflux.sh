#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "benchmark/testflux.sh is deprecated; use:" >&2
echo "  python benchmark/run_tool_call_eval.py --run-config benchmark/flux_tool_call_eval_run.json" >&2

args=(--run-config flux_tool_call_eval_run.json)
has_models_file=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --modelfile)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --modelfile" >&2
        exit 1
      fi
      args+=(--models-file "$2")
      has_models_file=1
      shift 2
      ;;
    --modelfile=*)
      value="${1#--modelfile=}"
      if [[ -z "$value" ]]; then
        echo "Missing value for --modelfile" >&2
        exit 1
      fi
      args+=(--models-file "$value")
      has_models_file=1
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if [[ "$has_models_file" -eq 0 && -n "${MCP_EVAL_MODELS_FILE:-}" ]]; then
  args+=(--models-file "$MCP_EVAL_MODELS_FILE")
fi

exec "${PYTHON:-python3}" run_tool_call_eval.py "${args[@]}"
