# MCP Tool Call Evaluation

The `benchmark/mcp_tool_call_eval.py` script evaluates whether an LLM can select
an MCP tool and generate the expected JSON arguments for that tool. It is
useful for comparing models, prompts, and OpenAI-compatible backends without
executing the MCP tool itself.

The script is generic. This guide uses a `generate_parameter_runs` style fixture
to explain the fixture format and the checked-in Flux fixture for runnable
benchmark examples.

## What It Tests

For each configured model, test case, and prompt variant, the runner:

- connects to the MCP server named by the test case
- discovers that server's tools
- sends one prompt to the selected LLM with those tools available
- records the first tool call returned by the model
- compares the tool name and arguments against the expected JSON
- writes per-prompt and per-case results

The runner does not call the MCP tool. This keeps the evaluation focused on
tool selection and argument generation, and avoids side effects such as
creating simulation run directories.

Use `--num-samples` or `-n` to repeat each prompt flavor multiple times. For
example, a case with `direct`, `natural`, and `terse` prompts and `-n 3` has a
maximum raw score of `9`.

## Fixture Format

Fixtures are JSON files with two top-level keys:

- `mcp_servers`: named MCP server connection definitions
- `tests`: test cases that select a server and define expected tool-call behavior

Example:
```json
{
  "mcp_servers": {
    "flux": {
      "url": "http://localhost:8101/mcp"
    }
  },
  "tests": [
    {
      "id": "submit_command_simple_ad_hoc",
      "server": "flux",
      "prompts": [
        {
          "id": "direct",
          "text": "Use the Flux server submit_command tool for one single ad hoc command. Set command to \"python -V\", nodes=1, tasks=1, time_limit=15m, job_name=python_version, and working_directory=/tmp/mada_flux_eval/single_command. Do not use submit_jobs or any generated run manifest."
        },
        {
          "id": "natural",
          "text": "Please submit one ad hoc Flux command, not a generated run manifest. Run python -V from /tmp/mada_flux_eval/single_command with one node, one total task, a 15 minute time limit, and job name python_version."
        },
        {
          "id": "terse",
          "text": "Flux submit_command single command: command=\"python -V\", nodes=1, tasks=1, time_limit=15m, job_name=python_version, working_directory=/tmp/mada_flux_eval/single_command."
        }
      ],
      "expected_call": {
        "tool": "submit_command",
        "arguments": {
          "command": "python -V",
          "nodes": 1,
          "tasks": 1,
          "time_limit": "15m",
          "job_name": "python_version",
          "working_directory": "/tmp/mada_flux_eval/single_command"
        },
        "match": {
          "mode": "subset"
        }
      }
    }
  ]
}
```

`expected_call` is required:

- `expected_call.tool`: exact MCP tool name the model should call
- `expected_call.arguments`: expected JSON arguments; use `{}` for no-argument tools
- `expected_call.match`: optional matching settings

`expected_call.match.mode` defaults to `subset`. Supported modes are:

- `subset`: every expected argument must be present with the same value; extra model arguments are allowed
- `exact`: the actual arguments must exactly equal the expected arguments

`expected_call.match.profile` is optional. Supported profiles are:

- `parameter_runs`: enables equivalence rules for `generate_parameter_runs`-style simulation tools

For arbitrary MCP tools, omit `profile` unless a profile is explicitly
documented for that tool shape.

Example for a non-simulation tool:

```json
{
  "id": "monitor_read_logs",
  "server": "monitor",
  "expected_call": {
    "tool": "read_logs",
    "arguments": {
      "run_location": "/tmp/run1",
      "stdout_file": "run.out",
      "stderr_file": "run.err"
    }
  },
  "prompts": [
    "Read stdout and stderr logs for /tmp/run1 using run.out and run.err."
  ]
}
```

Prompt entries can also be strings. In that case the runner assigns IDs like
`prompt_1`, `prompt_2`, and so on.

## Running The Evaluation

### Choose Models

The repository includes a shared curated model list with benchmark levels:

```text
benchmark/eval_models.tsv
```

Use `benchmark/populate_eval_models.py` to query the OpenAI-compatible `/models`
endpoint and refresh the discovered snapshot:

```bash
python benchmark/populate_eval_models.py
```

This writes the full discovered model list to:

```text
benchmark/eval_models_all.tsv
```

If `benchmark/eval_models.tsv` does not exist yet, the helper initializes it
from the discovered list. If it already exists, the helper leaves it unchanged
so you can manually curate levels and commented-out models. When refreshing the
discovery snapshot, known levels from the curated TSV are reused and newly
discovered models default to level `0`.

The level-aware file allows blank lines and `#` comments. Each enabled row is
`level model`, separated by whitespace. Level `0` is the default benchmark set.
Higher levels include all lower levels, so `--level 2` selects models marked
`0`, `1`, or `2`.

Example `eval_models.tsv`:

```text
# Level Model
0 gpt-5-mini
0 gpt-5.5
1 gpt-4.1-mini
```

The JSON runner's `--models-file` option can point at another model file. Plain
`.txt` files are still interpreted as one model per non-comment line. The
`eval_models_all.tsv` file is only a discovery snapshot and is not used directly
for eval runs.

Start the target MCP server before running the evaluator. For the checked-in
Flux eval fixture:

```bash
mada-mcp-flux --transport streamable-http --host localhost --port 8101
```

Then run the configured Flux benchmark from the repository root:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json
```

For the checked-in Slurm eval fixture, start Slurm on port `8102` and use the
Slurm run config:

```bash
mada-mcp-slurm --transport streamable-http --host localhost --port 8102

python benchmark/run_tool_call_eval.py \
  --run-config benchmark/slurm_tool_call_eval_run.json
```

The run config supplies the fixture, model source, eval options, output artifact
types, timestamped output directory behavior, and plot generation settings. The
runner resolves relative paths from the JSON config file's directory, so the
checked-in configs can refer to files such as `flux_tool_call_eval_cases.json`,
`slurm_tool_call_eval_cases.json`, `eval_models.tsv`, and `results`
without repeating the `benchmark/` prefix.

Use CLI overrides for common run-time changes:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/slurm_tool_call_eval_run.json \
  --level 1 \
  --num-samples 3 \
  --max-concurrency 4
```

The runner also supports `--models-file`, `--shard-count`, `--shard-index`,
`--output-dir`, `--no-plots`, and `--quiet` overrides.

### Run Config Shape

The checked-in `benchmark/flux_tool_call_eval_run.json` and
`benchmark/slurm_tool_call_eval_run.json` files are complete examples. The Flux
and Slurm run configs use similar shapes:

```json
{
  "name": "flux",
  "cases": "flux_tool_call_eval_cases.json",
  "models_file": "eval_models.tsv",
  "level": 0,
  "model_prices": "model_prices_and_context_window.json",
  "output": {
    "directory": "results",
    "prefix": "flux_tool_call",
    "timestamped": true,
    "results_csv": true,
    "results_json": true,
    "summary_csv": true,
    "summary_json": true,
    "plots": true,
    "capture_raw_response": true
  },
  "eval": {
    "num_samples": 3,
    "max_concurrency": 36,
    "shard_count": 1,
    "shard_index": 0,
    "strict": false
  }
}
```

```json
{
  "name": "slurm",
  "cases": "slurm_tool_call_eval_cases.json",
  "models_file": "eval_models.tsv",
  "level": 0,
  "model_prices": "model_prices_and_context_window.json",
  "output": {
    "directory": "results",
    "prefix": "slurm_tool_call",
    "timestamped": true,
    "results_csv": true,
    "results_json": true,
    "summary_csv": true,
    "summary_json": true,
    "plots": true,
    "capture_raw_response": true
  },
  "eval": {
    "num_samples": 3,
    "max_concurrency": 36,
    "shard_count": 1,
    "shard_index": 0,
    "strict": false
  }
}
```

String values may use `${VAR}` and `${VAR:-default}` environment expansion.
Missing variables without defaults are errors. API settings can be supplied in
the run config under `model_api`, or left to the lower-level evaluator's normal
`API_KEY` / `API_BASE_URL` resolution.

### Direct Evaluator Usage

The lower-level evaluator remains available when you want to provide all paths
explicitly:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --level 1 \
  --num-samples 3 \
  --max-concurrency 4 \
  --results-csv benchmark/results/flux_tool_call_rows.csv \
  --results-json benchmark/results/flux_tool_call_rows.json \
  --summary-csv benchmark/results/flux_tool_call_summary.csv \
  --summary-json benchmark/results/flux_tool_call_summary.json
```

When `--models` is omitted, the evaluator reads `benchmark/eval_models.tsv` and
selects models at `--level 0` by default. Pass `--level N` to include models at
levels `0..N`, or pass `--models-file` to use another list. The `--models`
argument still accepts one or more explicit model names and bypasses level
filtering. Each prompt variant is evaluated independently for each model.
`--num-samples` repeats each prompt flavor and adds a 1-based `sample_index`
field to the detailed outputs. `--max-concurrency` overlaps multiple API
requests inside one process while preserving deterministic output row order.

By default, token costs are computed from
`benchmark/model_prices_and_context_window.json` (which must be downloaded from
[https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) )
when the model has exact
`input_cost_per_token` and `output_cost_per_token` entries and the backend
returns prompt/completion token usage. Use `--model-prices` to point at a
different pricing JSON file. Missing pricing or missing token usage leaves cost
fields empty for that attempt.

During a run, the evaluator prints live progress by default. It reports MCP
server connection status, the current prompt counter, model, server, case ID,
prompt ID, result, latency, token usage, and error details.

Example progress lines:

```text
Evaluating 162 logical tool-call attempts across 3 models, 6 test cases, 1 configured MCP servers, and 3 sample(s) per prompt flavor.
Executing 162 attempt(s) with max_concurrency=4.
Connecting to MCP server 'flux' at http://localhost:8101/mcp ...
Connected to 'flux' with 5 tools in 142ms.
[12/162] START model=gpt-5-mini server=flux case=submit_command_full_options prompt=natural sample=2
[12/162] FAIL sample=2 latency_ms=19320 tokens=2114 error_type=arg_mismatch error=missing $.time_limit
```

Use `--quiet` to suppress live progress output:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini \
  --quiet
```

Use `--no-final-table` when CSV or JSON artifacts are enough:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini \
  --results-csv benchmark/results/flux_tool_call_rows.csv \
  --no-final-table
```

## Parallel and Batch Runs

The evaluator already uses async I/O for the model API. With
`--max-concurrency > 1`, it issues multiple tool-call attempts concurrently
while buffering completions and writing rows back in the original logical order.

For batch systems, the better scaling pattern is usually multiple evaluator
processes, not a single high-concurrency process. Use sharding to divide the
full eval matrix across allocated tasks or cores:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5.5 gpt-5-mini \
  --num-samples 3 \
  --max-concurrency 2 \
  --shard-count 4 \
  --shard-index 0 \
  --results-csv shard0_rows.csv \
  --results-json shard0_rows.json
```

Shards are assigned by deterministic logical attempt index modulo
`--shard-count`, so shard outputs are disjoint and reproducible. Shard-local
summary outputs and `--min-pass-rate` evaluate only that shard's subset of
attempts. If you need full-run summaries, merge per-row outputs from all shards
and summarize after collection.

### Merging Shards

Use `benchmark/merge_tool_call_eval_results.py` after all shard jobs finish to
restore canonical row order and regenerate full-run summaries:

```bash
python benchmark/merge_tool_call_eval_results.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5.5 gpt-5-mini \
  --num-samples 3 \
  --rows-json shard0_rows.json shard1_rows.json shard2_rows.json shard3_rows.json \
  --merged-results-json merged_rows.json \
  --merged-summary-csv merged_summary.csv \
  --merged-summary-json merged_summary.json
```

JSON shard inputs are preferred because the merged JSON output preserves the
full debugging payload from each row, including fields such as `prompt`,
`expected_call`, `actual_arguments`, `raw_tool_calls`, and optional
`raw_response`.

CSV shard inputs can still be merged for base-row consolidation and summary
regeneration, but they cannot reconstruct the detailed JSON-only debugging
fields.

The detailed JSON output includes the prompt, expected call, parsed actual
arguments, raw tool argument string, assistant text, raw assistant message, and
raw tool-call objects. This is the best artifact for inspecting why a model
failed.

Use `--capture-raw-response` to also include the full OpenAI-compatible API
response object in `--results-json`:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini \
  --results-json benchmark/results/flux_tool_call_rows.json \
  --capture-raw-response
```

## Configured Run Example

The configured runner creates a timestamped output directory, runs the
evaluation, writes requested CSV/JSON artifacts, generates plots from the
summary CSV, and preserves the evaluator's exit status if prompt cases fail:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json \
  --num-samples 3
```

The Slurm suite covers ad hoc `submit_command`, queued and blocking
`submit_jobs`, local `job_set_id` status, real `slurm_job_id` status, bounded
continuous status polling, queue listing, and cluster information.

## Example Output

The example outputs below are from a benchmark test of the flux mcp server:

```text
benchmark/results/flux_2026-07-16-12-24-28/
```

That directory contains:

```text
flux_2026-07-16-12-24-28/
├── flux_tool_call_cost.png
├── flux_tool_call_rows.csv
├── flux_tool_call_rows.json
├── flux_tool_call_score.png
├── flux_tool_call_summary.csv
├── flux_tool_call_summary.json
└── flux_tool_call_tokens.png
```

Excerpt from `flux_tool_call_summary.csv`:

```csv
model,server,case_id,num_flavors,num_samples,flavor_order,score_passed,score_total,score_rate,prompts_passed,prompts_total,pass_rate,all_passed,any_passed,direct_passed,direct_total,direct_rate,direct_avg_prompt_tokens,direct_avg_completion_tokens,direct_avg_total_tokens,direct_avg_latency_ms,natural_passed,natural_total,natural_rate,natural_avg_prompt_tokens,natural_avg_completion_tokens,natural_avg_total_tokens,natural_avg_latency_ms,terse_passed,terse_total,terse_rate,terse_avg_prompt_tokens,terse_avg_completion_tokens,terse_avg_total_tokens,terse_avg_latency_ms,total_prompt_tokens,total_completion_tokens,total_tokens,input_cost_usd,output_cost_usd,total_cost_usd,avg_prompt_tokens,avg_completion_tokens,avg_total_tokens,avg_latency_ms
...
gpt-4.1,flux,check_job_status_all_jobs,3,3,"[""direct"", ""natural"", ""terse""]",9,9,1.0,9,9,1.0,True,True,3,3,1.0,1006.0,12.0,1018.0,1281.0,3,3,1.0,1022.0,12.0,1034.0,1046.333,3,3,1.0,1005.0,12.0,1017.0,1123.0,9099,108,9207,0.018198,0.000864,0.019062,1011.0,12.0,1023.0,1150.111
gpt-4.1,flux,check_job_status_specific,3,3,"[""direct"", ""natural"", ""terse""]",9,9,1.0,9,9,1.0,True,True,3,3,1.0,1015.0,20.0,1035.0,1511.667,3,3,1.0,1019.0,20.0,1039.0,1515.667,3,3,1.0,999.0,20.0,1019.0,1482.667,9099,180,9279,0.018198,0.00144,0.019638,1011.0,20.0,1031.0,1503.333
```

Score plot example:

![flux tool-call score plot](../assets/images/flux_tool_call_score.png)

Token plot example:

![flux tool-call token plot](../assets/images/flux_tool_call_tokens.png)

Cost plot example:

![flux tool-call cost plot](../assets/images/flux_tool_call_cost.png)

## API Configuration

The script can read API settings from CLI arguments, a config file, or
environment variables.

Precedence is:

1. CLI arguments: `--api-key`, `--base-url`
2. Config file values from `--config`
3. Environment variables: `API_KEY`, `API_BASE_URL`
4. Default base URL: `https://livai-api.llnl.gov/v1`

The config file can use the same model section shape as the example agent
configs (see example configs in the `../examples/` directory):

```json
{
  "model": {
    "api_key": "${API_KEY}",
    "base_url": "${API_BASE_URL:-https://livai-api.llnl.gov/v1}"
  }
}
```

For a local OpenAI-compatible server that does not require authentication, the
evaluator uses `dummy` as the API key when the base URL starts with
`http://localhost` or `http://127.0.0.1`.

Example with a local backend:

```bash
python benchmark/mcp_tool_call_eval.py \
  --base-url http://localhost:8000/v1 \
  --api-key dummy \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gemma4-12b
```

## Matching Behavior

By default, argument comparison is recursive subset matching. Every field in
`expected_call.arguments` must be present in the model's actual tool arguments
with the same value, but the model may include additional optional fields.

Subset mode by itself is generic and does not apply simulation-specific
normalization. Add `"profile": "parameter_runs"` to `expected_call.match` to
accept a small set of contract-equivalent forms that commonly occur in
`generate_parameter_runs` tool calls:

- executable parameter aliases: if the expected parameter is an `["exe", ...]` parameter, another actual parameter key with the same `["exe", ...]` value is accepted
- deck file path splitting: `input_deck_path=/path/to/deck/input.deck` is accepted as equivalent to `input_deck_path=/path/to/deck` plus `input_deck_entrypoint=input.deck`
- dependency path splitting: absolute dependency paths under `input_deck_path` are accepted as equivalent to expected relative dependencies
- CLI parameter grouping: fixed discrete `["cli", ...]` parameters can be matched by renamed or combined actual CLI parameters when the argv token sequence is present
- zip group identifiers: `zip` parameters can use different group id labels when the same expected parameters remain grouped together and independent groups do not collapse
- numeric string values for discrete `def` parameters: expected numeric values such as `[1]` can match actual string values such as `["1"]`
- JSON-encoded list strings: expected values such as `["Aluminum", "Steel"]` can match actual values such as `"[\"Aluminum\", \"Steel\"]"` when the decoded JSON is the same list

Use `--strict` to require exact argument equality for every test, overriding
fixture match modes and profiles:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini \
  --strict
```

The default subset behavior is usually better for prompt/model evaluation
because MCP schemas often include optional arguments with defaults.

## Results

The console output includes:

- one row per `model x server x case_id x prompt_id`
- a summary table grouped by `model x server x case_id`

When `--results-csv` is provided, the per-prompt CSV is written incrementally.
The header is written before the evaluation loop, and each completed prompt row
is flushed immediately. This makes partial results available if a long run is
interrupted.

JSON outputs and summary outputs are written at the end of the run.

Per-prompt CSV fields:

```text
model,server,case_id,prompt_id,sample_index,passed,error_type,error,expected_tool,actual_tool,prompt_tokens,completion_tokens,total_tokens,input_token_price_usd,output_token_price_usd,input_cost_usd,output_cost_usd,total_cost_usd,latency_ms
```

Per-case summary CSV fields:

```text
model,server,case_id,num_flavors,num_samples,flavor_order,score_passed,score_total,score_rate,prompts_passed,prompts_total,pass_rate,all_passed,any_passed,<flavor>_passed,<flavor>_total,<flavor>_rate,<flavor>_avg_prompt_tokens,<flavor>_avg_completion_tokens,<flavor>_avg_total_tokens,<flavor>_avg_latency_ms,total_prompt_tokens,total_completion_tokens,total_tokens,input_cost_usd,output_cost_usd,total_cost_usd,avg_prompt_tokens,avg_completion_tokens,avg_total_tokens,avg_latency_ms
```

`score_passed` and `score_total` are raw counts across all prompt-sample
attempts. `pass_rate` is retained as a compatibility alias for the aggregate
normalized score. `flavor_order` stores the prompt-id order for the row, and
the per-flavor columns follow that order for example `direct_passed`,
`natural_passed`, and `terse_passed`. Per-flavor token and latency averages are
also emitted so token plots can draw flavor partitions by observed token share
instead of only by prompt/sample count.
`input_cost_usd`, `output_cost_usd`, and `total_cost_usd` are summed from the
actual per-attempt token counts and model prices; they are empty when pricing
or token usage is unavailable.

Use `--min-pass-rate` to set the process exit criteria from the per-case
summary. For example, this requires every prompt-sample attempt in each case to
pass:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini \
  --min-pass-rate 1.0
```

For exploratory model comparison, a lower threshold can be useful:

```bash
python benchmark/mcp_tool_call_eval.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --models gpt-5-mini gemma4-12b \
  --min-pass-rate 0.8
```

## Interpreting Failures

Common `error_type` values:

- `api_error`: the OpenAI-compatible API request failed
- `no_tool_call`: the model returned text instead of a tool call
- `bad_json`: the model returned tool arguments that were not valid JSON
- `wrong_tool`: the selected tool name did not match the expected tool
- `arg_mismatch`: the tool name matched, but expected arguments were missing or different

For local or non-OpenAI models, the most common issues are missing tool-call
support, malformed arguments, and missing token usage data. When token usage is
not provided by the backend, the runner reports token fields as empty in CSV
and `null` in JSON.
