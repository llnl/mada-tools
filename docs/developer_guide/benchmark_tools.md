# Benchmark Tools

The `benchmark/` directory contains a small toolchain for evaluating MCP tool
calling:

- `gen_benchmark_fixture.py`: generates prompt variants for expected tool calls.
- `gen_benchmark_report.py`: writes Markdown fixture and run reports.
- `run_tool_call_eval.py`: runs evaluation from a JSON run config, can start MCP servers, plots results, and writes a run report.
- `merge_tool_call_eval_results.py`: merges sharded evaluator row outputs.
- `plot_tool_call_eval_results.py`: plots summary CSV/JSON files.
- `populate_eval_models.py`: refreshes model-list files from an OpenAI-compatible `/models` endpoint.

The tools are designed around OpenAI-compatible model APIs and live MCP servers.
The evaluator connects to each configured MCP server, lists tools, asks the
model to choose a tool for each prompt, and compares the first returned tool
call against an expected structured call. The evaluator does not execute the
selected MCP tool.

## Fixture Format

Benchmark fixtures are JSON objects with:

- `mcp_servers`: named MCP server connection definitions. Required only when the run config does not manage servers.
- `tests`: benchmark cases.
- `prompt_generation`: optional settings used by `gen_benchmark_fixture.py`.

Minimal evaluator fixture:

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
          "text": "Use the Flux submit_command tool to run python -V with nodes=1, tasks=1, time_limit=15m, job_name=python_version, and working_directory=/tmp/mada_flux_eval/single_command."
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

`expected_call` fields:

- `tool`: exact MCP tool name the model should call.
- `arguments`: expected JSON arguments; use `{}` for no-argument calls.
- `match.mode`: optional, `subset` by default; supported values are `subset` and `exact`.
- `match.profile`: optional profile-specific equivalence logic; currently `parameter_runs`.

`subset` mode requires every expected argument to be present with the same
value, while allowing extra actual arguments. `exact` requires exact argument
equality. The `parameter_runs` profile enables equivalence rules for
`generate_parameter_runs` style simulation tools, such as deck path splitting,
CLI parameter grouping, zip group label variation, numeric-string matching, and
JSON-encoded list-string matching.

Prompt entries may be objects with `id` and `text`, or plain strings. Plain
strings are assigned IDs like `prompt_1`.

## Prompt Generation

Use `benchmark/gen_benchmark_fixture.py` to generate prompts from existing
`expected_call` entries. This is useful when adding many cases: write the
expected MCP call first, describe the desired prompt styles, then let a model
draft prompt variants.

Example:

```bash
python benchmark/gen_benchmark_fixture.py \
  --cases benchmark/flux_tool_call_eval_cases.input.json \
  --output benchmark/flux_tool_call_eval_cases.generated.json \
  --num-prompts 5
```

By default, `--num-prompts 5` means five prompts per selected style for each
test case. If the styles are `natural`, `terse`, `noobie`, `lazy`, and
`direct`, each case receives 25 generated prompts:

```text
natural, terse, noobie, lazy, direct,
natural_2, terse_2, noobie_2, lazy_2, direct_2,
...
natural_5, terse_5, noobie_5, lazy_5, direct_5
```

### Prompt Generation Config

Styles are specified in the input fixture under top-level `prompt_generation`.
The generator also accepts CLI overrides.

Excerpt from `benchmark/flux_tool_call_eval_cases.input.json`:

```json
{
  "prompt_generation": {
    "model": "gpt-5.4-mini",
    "num_prompts": 5,
    "prompt_source": "generated",
    "augment_prompts": false,
    "augment_source": "both",
    "argument_policies": [
      {
        "server": "flux",
        "tool": "submit_command",
        "arguments": {
          "command": {
            "mode": "verbatim",
            "guidance": "Repeat the command exactly as written."
          },
          "nodes": {
            "mode": "semantic",
            "guidance": "Express the node count clearly enough to recover the expected numeric value."
          },
          "time_limit": {
            "mode": "semantic",
            "guidance": "Express the time limit clearly enough to recover the expected value."
          },
          "working_directory": {
            "mode": "verbatim",
            "guidance": "Working directories are paths; preserve the expected value exactly."
          }
        },
        "guidance": [
          "Flux scheduler/resource arguments such as nodes, tasks, time_limit, job_name, and working_directory are separate tool arguments."
        ]
      }
    ],
    "styles": [
      {
        "id": "natural",
        "description": "A normal conversational request from a capable user."
      },
      {
        "id": "terse",
        "description": "A short command-like request with minimal extra wording."
      },
      {
        "id": "noobie",
        "description": "A beginner-style request that uses informal wording and may over-explain."
      },
      {
        "id": "lazy",
        "description": "An underspecified casual request, but still containing enough information to imply the expected tool call."
      },
      {
        "id": "direct",
        "description": "An explicit instruction naming the intended server, tool, and key arguments."
      }
    ]
  }
}
```

Prompt source options:

- `generated`: generate prompts from `expected_call`; this is the default.
- `existing`: use prompts already present in the fixture and skip LLM generation.
- `both`: keep existing prompts and append generated prompts.

`augment_prompts` enables a future NLPA augmentation pass. Today this hook is
a no-op stub: prompts are passed through the augmentation functions and returned
unchanged. `augment_source` controls whether augmentation is applied to
`generated`, `existing`, or `both` prompt sources.

`argument_policies` is optional. It lets fixture inputs define server/tool
specific generation constraints without hard-coding those rules in
`gen_benchmark_fixture.py`. Each policy must specify `server` and `tool`, and
can optionally specify `test_id` for a single case. Matching policies are merged
in order.

- `arguments`: map of argument name to a rule.
- `mode`: `verbatim` means the string value must appear exactly in every
  generated prompt; `semantic` means the prompt may express the value naturally
  as long as the expected argument can be recovered in context.
- `guidance`: extra instructions included only for matching cases or arguments.

When no policy matches a case, generated prompts are not required to quote any
string argument verbatim. This keeps server-specific semantics, such as Flux
command handling, in the fixture input that owns the expected calls. Generated
prompts should still naturally imply the expected MCP server, tool, and
arguments.

A seed case can include existing prompts or omit them. The generator validates
`expected_call`, applies any matching prompt-generation policies, then writes a
new output fixture with generated `prompts`.

Input excerpt:

```json
{
  "id": "submit_command_simple_ad_hoc",
  "server": "flux",
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
```

Generated output excerpt:

```json
{
  "id": "submit_command_simple_ad_hoc",
  "server": "flux",
  "prompts": [
    {
      "id": "natural",
      "text": "Can you run `python -V` on Flux for me? Please name the job `python_version`, use `/tmp/mada_flux_eval/single_command` as the working directory, and give it 15 minutes."
    },
    {
      "id": "terse",
      "text": "Run `python -V` on Flux in /tmp/mada_flux_eval/single_command as job python_version, 1 node, 1 task, 15m."
    },
    {
      "id": "direct_5",
      "text": "Please schedule one simple Flux command: run `python -V` with job name `python_version`, 1 node, 1 task, a 15m time limit, and working directory `/tmp/mada_flux_eval/single_command`."
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
```

Use existing prompts only:

```bash
python benchmark/gen_benchmark_fixture.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --output benchmark/flux_tool_call_eval_cases.existing_augmented.json \
  --prompt-source existing \
  --augment-prompts
```

This does not require `--model`, API credentials, a live MCP server, or static
tool-schema discovery. It currently writes the same prompt text because NLPA
augmentation is stubbed.

Combine existing prompts with generated prompts:

```bash
python benchmark/gen_benchmark_fixture.py \
  --cases benchmark/flux_tool_call_eval_cases.json \
  --output benchmark/flux_tool_call_eval_cases.combined.json \
  --prompt-source both \
  --num-prompts 2
```

If generated prompt IDs conflict with existing prompt IDs, generated IDs are
prefixed with `generated_` so curated existing IDs remain stable.

### Server Knowledge For Generation

The generator needs tool names, descriptions, and argument schemas. With
`--server-source auto` it first tries live MCP discovery using
`mcp_servers.<name>.url`. If that fails, it falls back to parsing local
`server.py` docstrings and function signatures.

Fallback path resolution order:

1. `mcp_servers.<name>.server_py`
2. `mcp_servers.<name>.module`
3. built-in known paths for repo servers such as `flux`, `slurm`, `vertex_cfd`, `professor`, `job_monitor`, and `maestro_command_executor`

Example for an explicit fallback path:

```json
{
  "mcp_servers": {
    "custom": {
      "url": "http://localhost:8123/mcp",
      "server_py": "src/mada_tools/custom/server.py"
    }
  }
}
```

## Running Benchmarks

Start the target MCP server before evaluating. For Flux:

```bash
mada-mcp-flux --transport streamable-http --host localhost --port 8101
```

Run the configured benchmark:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json
```

The configured runner resolves relative paths from the run config file's
directory, optionally starts MCP servers from a server config, runs the
evaluator, writes requested artifacts, generates plots, and generates a
Markdown run report. It returns the evaluator's success or failure status.

Run config shape:

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
    "report": true,
    "report_path": "flux_tool_call_report.md",
    "plot_prompt_details": false,
    "capture_raw_response": true
  },
  "eval": {
    "num_samples": 3,
    "max_concurrency": 36,
    "shard_count": 1,
    "shard_index": 0,
    "prompt_styles": ["direct", "natural"],
    "exclude_prompt_ids": ["direct_5"],
    "strict": false,
    "min_pass_rate": 0.8
  },
  "model_api": {
    "config": "api_config.json",
    "base_url": "https://example.invalid/v1",
    "api_key": "${API_KEY}"
  },
  "server_management": {
    "enabled": true,
    "config": "../configs/flux_servers.json",
    "randomize_ports": true,
    "stop_on_exit": true
  }
}
```

Common run config fields:

- `name`: run name used for timestamped output directory names.
- `cases`: fixture path.
- `models`: inline list of model IDs, or `models_file` for a model-list file.
- `level`: maximum model level when using a level-aware TSV model file.
- `model_prices`: pricing metadata JSON used for cost calculation. (download from https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
- `system_prompt`: optional evaluator system prompt override.
- `output.directory`: base output directory.
- `output.prefix`: output filename prefix.
- `output.timestamped`: create `directory/name_timestamp`.
- `output.results_csv`, `results_json`, `summary_csv`, `summary_json`: enable artifacts.
- `output.plots`: enable plot generation.
- `output.report`: enable Markdown run report generation; defaults to `true`.
- `output.report_path`: optional report path. Relative paths are written under the run output directory.
- `output.plot_prompt_details`: show every prompt ID separately in plot flavor
  partitions; default grouped by root style.
- `output.capture_raw_response`: include raw OpenAI-compatible responses in detailed JSON.
- `eval.num_samples`: repetitions per prompt flavor.
- `eval.max_concurrency`: concurrent model requests in one process.
- `eval.shard_count`, `eval.shard_index`: deterministic sharding.
- `eval.prompt_ids`: exact prompt IDs to include.
- `eval.prompt_styles`: root prompt styles to include, such as `direct`.
- `eval.exclude_prompt_ids`: exact prompt IDs to exclude after includes.
- `eval.exclude_prompt_styles`: root prompt styles to exclude after includes.
- `eval.strict`: exact argument matching.
- `eval.min_pass_rate`: required per-case pass rate for success.
- `eval.temperature`, `request_timeout`: model request settings.
- `model_api.config`, `base_url`, `api_key`: API settings for the evaluator.
- `server_management.enabled`: start required MCP servers before evaluation.
- `server_management.config`: server config JSON, usually from `configs/`.
- `server_management.randomize_ports`: assign fresh ports and write an effective fixture with matching URLs.
- `server_management.stop_on_exit`: stop managed servers after evaluation, including failures.

String config values support `${VAR}` and `${VAR:-default}` expansion.

### Prompt Filtering

Prompt filters let you evaluate a subset of prompt flavors without editing the
fixture. Exact prompt IDs match only that prompt, while root styles match the
base name before a numeric suffix. For example, style `direct` matches
`direct`, `direct_2`, and `direct_3`.

Include filters are applied first. Exclude filters are applied after includes.
The evaluator raises an error if filtering removes all prompts from any case.

Examples:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json \
  --prompt-styles direct,natural
```

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json \
  --prompt-ids direct,direct_2,natural \
  --exclude-prompt-ids direct_2
```

The same filters are available on `run_tool_call_eval.py` and
`merge_tool_call_eval_results.py`. Use the same filters when merging sharded
outputs that were produced from a filtered run, so the merge tool rebuilds the
same canonical prompt matrix.

## Benchmark Reports

`gen_benchmark_report.py` creates Markdown reports for benchmark fixtures and
completed benchmark runs.

`run_tool_call_eval.py` calls the report generator automatically after the
evaluator finishes and after plots are generated. The default report path is:

```text
<output_dir>/<output.prefix>_report.md
```

The run report includes:

- Run settings such as config path, fixture path, models, sample count, shard,
  matching mode, and selected prompt filters.
- Output plot images embedded with relative Markdown links.
- A compact failure section grouped by model, MCP server, test case, and prompt
  ID. Each group includes the actual prompt, expected tool and arguments, common
  failure patterns, evaluator reason text, and returned arguments.
- The fixture-only report content: MCP server chapters, expected calls, and
  prompts grouped by root flavor.

Disable automatic run reports when needed:

```json
{
  "output": {
    "report": false
  }
}
```

Use a custom report filename or path under the output directory:

```json
{
  "output": {
    "report_path": "reports/flux_report.md"
  }
}
```

The same tool can create a fixture-only report without running an evaluation:

```bash
python benchmark/gen_benchmark_report.py \
  --cases benchmark/flux_tool_call_eval_cases.generated.json \
  --output benchmark/flux_tool_call_eval_cases.generated.md
```

Fixture-only reports are useful for reviewing MCP servers, expected tools,
expected arguments, and generated prompt flavors before spending model calls on
an evaluation.

You can also regenerate a run report from an existing output directory:

```bash
python benchmark/gen_benchmark_report.py \
  --cases benchmark/flux_tool_call_eval_cases.generated.json \
  --run-output benchmark/results/flux_2026-07-17_09-37-38
```

In run-report mode, the tool infers the detailed rows file from the single
`*_rows.json` file in `--run-output`, embeds all `*.png` plots in that
directory, and writes `<prefix>_report.md` beside the run artifacts. Use
`--rows-json`, `--plots`, `--run-config`, `--eval-status`, and `--output` when
you need to override those inferred values.

## Models And API Configuration

`populate_eval_models.py` queries an OpenAI-compatible `/models` endpoint and
updates model-list files:

```bash
python benchmark/populate_eval_models.py \
  --config api_config.json
```

It writes a full discovery snapshot to `benchmark/eval_models_all.tsv` and
initializes `benchmark/eval_models.tsv` only if the curated file does not
already exist. Existing curated levels are reused when refreshing discovery.

Level-aware model files use whitespace-separated `level model` rows. Blank
lines and `#` comments are ignored. Level `0` is the default set; `--level 2`
selects models at levels `0`, `1`, and `2`.

Example:

```text
# Level Model
0 gpt-5-mini
0 gpt-5.5
1 gpt-4.1-mini
```

API settings are resolved from CLI arguments, JSON config, then environment:

1. `--api-key`, `--base-url`
2. config file values from `model.api_key` and `model.base_url`, or top-level `api_key` and `base_url`
3. `API_KEY`, `API_BASE_URL`
4. default base URL where applicable

Example API config:

```json
{
  "model": {
    "api_key": "${API_KEY}",
    "base_url": "${API_BASE_URL:-https://livai-api.llnl.gov/v1}"
  }
}
```

For localhost OpenAI-compatible servers, the tools use `dummy` as the API key
when no key is provided.

## Results And Plots

Per-prompt CSV fields:

```text
model,server,case_id,prompt_id,sample_index,passed,error_type,error,expected_tool,actual_tool,prompt_tokens,completion_tokens,total_tokens,input_token_price_usd,output_token_price_usd,input_cost_usd,output_cost_usd,total_cost_usd,latency_ms
```

Per-case summary CSV fields:

```text
model,server,case_id,num_flavors,num_samples,flavor_order,score_passed,score_total,score_rate,prompts_passed,prompts_total,pass_rate,all_passed,any_passed,<flavor>_passed,<flavor>_total,<flavor>_rate,<flavor>_avg_prompt_tokens,<flavor>_avg_completion_tokens,<flavor>_avg_total_tokens,<flavor>_avg_latency_ms,total_prompt_tokens,total_completion_tokens,total_tokens,input_cost_usd,output_cost_usd,total_cost_usd,avg_prompt_tokens,avg_completion_tokens,avg_total_tokens,avg_latency_ms
```

`score_passed` and `score_total` are raw counts across all prompt-sample
attempts. `flavor_order` stores the prompt IDs in fixture order. Per-flavor
token and latency averages let token plots draw prompt partitions by observed
token share.

Plot generation:

```bash
python benchmark/plot_tool_call_eval_results.py \
  --summary benchmark/results/flux_tool_call_summary.csv \
  --score-output benchmark/results/flux_tool_call_score.png \
  --tokens-output benchmark/results/flux_tool_call_tokens.png \
  --cost-output benchmark/results/flux_tool_call_cost.png
```

Score and token plots group numbered prompt variants by root style by default:
`direct`, `direct_2`, and `direct_3` are plotted as one `direct` partition.
Use `--plot-prompt-details`, or set `"plot_prompt_details": true` in a run
config, to show each prompt ID separately.

Cost plots are written only when the selected cost field has numeric values.
Missing pricing is annotated on the cost plot when every row for a model lacks
numeric cost data.

Common failure `error_type` values:

- `api_error`: model API request failed.
- `no_tool_call`: model returned text instead of a tool call.
- `bad_json`: tool arguments were not valid JSON.
- `wrong_tool`: selected tool name did not match.
- `arg_mismatch`: tool matched but arguments differed.

## Sharding And Merging

Use sharding for batch systems or large model matrices:

```bash
python benchmark/run_tool_call_eval.py \
  --run-config benchmark/flux_tool_call_eval_run.json \
  --shard-count 4 \
  --shard-index 0
```

Shards are assigned by deterministic logical attempt index modulo
`--shard-count`, so shard outputs are disjoint and reproducible.

Merge after all shards finish:

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

JSON shard inputs are preferred because merged JSON preserves detailed
debugging fields such as `prompt`, `expected_call`, `actual_arguments`,
`raw_tool_calls`, and optional `raw_response`. CSV shards can be merged for
base-row consolidation and summary regeneration, but cannot reconstruct
JSON-only details.

## Command Reference

### `gen_benchmark_fixture.py`

| Option | Description |
| --- | --- |
| `--cases PATH` | Required input fixture with `mcp_servers` and `tests`. |
| `--output PATH` | Required output fixture path. The input file is not modified. |
| `--config PATH` | Optional JSON config with model API settings. |
| `--model MODEL` | Generation model name. Overrides `prompt_generation.model`. |
| `--base-url URL` | OpenAI-compatible API base URL. |
| `--api-key KEY` | OpenAI-compatible API key. |
| `--num-prompts`, `-n` | Prompts per selected style for each test case. |
| `--styles IDS` | Comma-separated style IDs from `prompt_generation.styles`. |
| `--prompt-source generated\|existing\|both` | Choose generated prompts, existing fixture prompts, or both. |
| `--augment-prompts` | Pass selected prompts through the no-op NLPA augmentation hook. |
| `--augment-source generated\|existing\|both` | Source to augment when augmentation is enabled. |
| `--temperature FLOAT` | Optional generation temperature. |
| `--request-timeout SECONDS` | LLM request timeout. |
| `--server-source auto\|live\|static` | Tool-schema source. `auto` tries live MCP then static `server.py`. |
| `--quiet` | Suppress progress output. |

### `gen_benchmark_report.py`

| Option | Description |
| --- | --- |
| `--cases PATH` | Required fixture with `mcp_servers` and `tests`. |
| `--run-output PATH` | Completed benchmark output directory. Enables run-report mode. |
| `--rows-json PATH` | Detailed rows JSON. Defaults to the single `*_rows.json` file in `--run-output`. |
| `--plots PATH...` | Plot image paths for run-report mode. Defaults to all `*.png` files in `--run-output`. |
| `--run-config PATH` | Optional run config JSON used to describe the completed run. |
| `--eval-status N` | Optional evaluator exit status. Defaults to inferred pass/fail status from detailed rows. |
| `--output PATH` | Optional Markdown report path. Defaults by report mode. |

### `run_tool_call_eval.py`

| Option | Description |
| --- | --- |
| `--run-config PATH` | Required JSON run configuration. |
| `--models MODEL...` | Override run config model selection with explicit model IDs. |
| `--models-file PATH` | Override run config model file. |
| `--level N` | Override maximum model level from a level-aware model file. |
| `--num-samples`, `-n` | Override repetitions per prompt flavor. |
| `--max-concurrency`, `-c` | Override concurrent model request limit. |
| `--shard-count N` | Override shard count. |
| `--shard-index N` | Override 0-based shard index. |
| `--min-pass-rate RATE` | Override `eval.min_pass_rate`; must be between 0 and 1. |
| `--prompt-ids IDS` | Comma-separated exact prompt IDs to include. |
| `--prompt-styles STYLES` | Comma-separated root prompt styles to include. |
| `--exclude-prompt-ids IDS` | Comma-separated exact prompt IDs to exclude after include filters. |
| `--exclude-prompt-styles STYLES` | Comma-separated root prompt styles to exclude after include filters. |
| `--output-dir PATH` | Override base output directory. |
| `--no-plots` | Disable plot generation. |
| `--no-manage-servers` | Do not start MCP servers even when `server_management.enabled` is true. |
| `--quiet` | Suppress live progress output. |

### `merge_tool_call_eval_results.py`

| Option | Description |
| --- | --- |
| `--cases PATH` | Required fixture used to rebuild canonical ordering and summaries. |
| `--models MODEL...` | Models used to build the canonical eval matrix. |
| `--models-file PATH` | File containing model names; mutually exclusive with `--models`. |
| `--num-samples`, `-n` | Samples collected per prompt flavor. |
| `--rows-json PATH...` | Shard JSON row files; mutually exclusive with `--rows-csv`. |
| `--rows-csv PATH...` | Shard CSV row files; mutually exclusive with `--rows-json`. |
| `--merged-results-csv PATH` | Write merged per-prompt CSV rows. |
| `--merged-results-json PATH` | Write merged detailed JSON rows. |
| `--merged-summary-csv PATH` | Write merged per-case summary CSV. |
| `--merged-summary-json PATH` | Write merged per-case summary JSON. |
| `--prompt-ids IDS` | Comma-separated exact prompt IDs to include in the canonical merge matrix. |
| `--prompt-styles STYLES` | Comma-separated root prompt styles to include in the canonical merge matrix. |
| `--exclude-prompt-ids IDS` | Comma-separated exact prompt IDs to exclude after include filters. |
| `--exclude-prompt-styles STYLES` | Comma-separated root prompt styles to exclude after include filters. |
| `--quiet` | Suppress progress output. |
| `--no-final-table` | Skip final console tables. |

### `plot_tool_call_eval_results.py`

| Option | Description |
| --- | --- |
| `--summary PATH` | Required summary CSV or JSON from the evaluator. |
| `--score-output PATH` | Required score/pass-rate plot output path. |
| `--tokens-output PATH` | Required token plot output path. |
| `--cost-output PATH` | Optional cost plot output path. |
| `--score-field FIELD` | Summary field for score plot; default `score_passed`. |
| `--token-field FIELD` | Summary field for token plot; default `avg_total_tokens`. |
| `--cost-field FIELD` | Summary field for cost plot; default `total_cost_usd`. |
| `--plot-prompt-details` | Plot every prompt ID separately instead of grouping numeric variants by root style. |
| `--min-pass-rate RATE` | Optional threshold line for score plots; must be between 0 and 1. |

Raw score plots show dashed reference lines for the maximum possible score and,
when configured, the aggregate score implied by `min_pass_rate`. Run success
still uses the per-case `pass_rate` rule from `eval.min_pass_rate`.

### `populate_eval_models.py`

| Option | Description |
| --- | --- |
| `--config PATH` | Optional JSON config with model API settings. |
| `--api-key KEY` | OpenAI-compatible API key. |
| `--base-url URL` | OpenAI-compatible API base URL. |
| `--all-output PATH` | Full discovered model snapshot output; default `benchmark/eval_models_all.tsv`. |
| `--enabled-output PATH` | Curated enabled model list initialized if missing; default `benchmark/eval_models.tsv`. |
| `--timeout SECONDS` | HTTP timeout for `/models`; default `30.0`. |
