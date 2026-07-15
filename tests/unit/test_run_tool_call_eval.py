import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "benchmark"
SCRIPT_PATH = BENCHMARK_DIR / "run_tool_call_eval.py"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

spec = importlib.util.spec_from_file_location("run_tool_call_eval", SCRIPT_PATH)
assert spec is not None
run_tool_call_eval = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = run_tool_call_eval
spec.loader.exec_module(run_tool_call_eval)


def cli_overrides(**overrides):
    defaults = {
        "models_file": None,
        "num_samples": None,
        "max_concurrency": None,
        "shard_count": None,
        "shard_index": None,
        "output_dir": None,
        "no_plots": False,
        "quiet": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_load_run_config_expands_env_vars(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODEL_ID", "gpt-test")
    config_path = tmp_path / "run.json"
    config_path.write_text(json.dumps({"models": ["${MODEL_ID}"]}), encoding="utf-8")

    assert run_tool_call_eval.load_run_config(config_path) == {"models": ["gpt-test"]}


def test_build_eval_args_resolves_paths_and_outputs(tmp_path: Path):
    models_file = tmp_path / "models.txt"
    models_file.write_text("# comment\nmodel-a\n\nmodel-b\n", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text("{}", encoding="utf-8")
    config = {
        "name": "flux",
        "cases": "cases.json",
        "models_file": "models.txt",
        "output": {
            "directory": "results",
            "prefix": "flux_tool_call",
            "timestamped": False,
            "capture_raw_response": True,
        },
        "eval": {
            "num_samples": 2,
            "max_concurrency": 3,
            "shard_count": 4,
            "shard_index": 1,
        },
    }

    args = cli_overrides()
    models = run_tool_call_eval.models_from_config(config, tmp_path, None)
    output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, None)
    eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, args, output_dir, models)

    assert models == ["model-a", "model-b"]
    assert output_dir == tmp_path / "results"
    assert eval_args.cases == cases.resolve()
    assert eval_args.results_csv == tmp_path / "results" / "flux_tool_call_rows.csv"
    assert eval_args.results_json == tmp_path / "results" / "flux_tool_call_rows.json"
    assert eval_args.summary_csv == tmp_path / "results" / "flux_tool_call_summary.csv"
    assert eval_args.summary_json == tmp_path / "results" / "flux_tool_call_summary.json"
    assert eval_args.num_samples == 2
    assert eval_args.max_concurrency == 3
    assert eval_args.shard_count == 4
    assert eval_args.shard_index == 1
    assert eval_args.capture_raw_response is True


def test_cli_overrides_replace_config_values(tmp_path: Path):
    config_models_file = tmp_path / "models.txt"
    config_models_file.write_text("model-a\n", encoding="utf-8")
    override_models_file = tmp_path / "small.txt"
    override_models_file.write_text("model-small\n", encoding="utf-8")
    config = {
        "cases": "cases.json",
        "models_file": "models.txt",
        "output": {"directory": "results", "timestamped": False},
        "eval": {"num_samples": 1, "max_concurrency": 1, "shard_count": 1, "shard_index": 0},
    }

    args = cli_overrides(
        models_file=override_models_file,
        num_samples=5,
        max_concurrency=6,
        shard_count=7,
        shard_index=2,
        output_dir=tmp_path / "override-results",
    )
    models = run_tool_call_eval.models_from_config(config, tmp_path, args.models_file)
    output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, args.output_dir)
    eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, args, output_dir, models)

    assert models == ["model-small"]
    assert output_dir == tmp_path / "override-results"
    assert eval_args.num_samples == 5
    assert eval_args.max_concurrency == 6
    assert eval_args.shard_count == 7
    assert eval_args.shard_index == 2
