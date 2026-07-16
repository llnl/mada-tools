import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "benchmark"
SCRIPT_PATH = BENCHMARK_DIR / "merge_tool_call_eval_results.py"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

spec = importlib.util.spec_from_file_location("merge_tool_call_eval_results", SCRIPT_PATH)
assert spec is not None
merge_tool_call_eval_results = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = merge_tool_call_eval_results
spec.loader.exec_module(merge_tool_call_eval_results)


def test_normalize_base_row_accepts_legacy_rows_without_cost_fields(tmp_path: Path):
    row = {
        "model": "gpt-test",
        "server": "server",
        "case_id": "case",
        "prompt_id": "direct",
        "sample_index": "1",
        "passed": "true",
        "error_type": "",
        "error": "",
        "expected_tool": "submit_job",
        "actual_tool": "submit_job",
        "prompt_tokens": "100",
        "completion_tokens": "20",
        "total_tokens": "120",
        "latency_ms": "10",
    }

    normalized = merge_tool_call_eval_results.normalize_base_row(row, tmp_path / "rows.csv")

    assert normalized["sample_index"] == 1
    assert normalized["passed"] is True
    assert normalized["input_cost_usd"] is None
    assert normalized["output_cost_usd"] is None
    assert normalized["total_cost_usd"] is None


def test_normalize_base_row_parses_cost_fields(tmp_path: Path):
    row = {
        "model": "gpt-test",
        "server": "server",
        "case_id": "case",
        "prompt_id": "direct",
        "sample_index": "1",
        "passed": "true",
        "error_type": "",
        "error": "",
        "expected_tool": "submit_job",
        "actual_tool": "submit_job",
        "prompt_tokens": "100",
        "completion_tokens": "20",
        "total_tokens": "120",
        "input_token_price_usd": "0.001",
        "output_token_price_usd": "0.002",
        "input_cost_usd": "0.1",
        "output_cost_usd": "0.04",
        "total_cost_usd": "0.14",
        "latency_ms": "10",
    }

    normalized = merge_tool_call_eval_results.normalize_base_row(row, tmp_path / "rows.csv")

    assert normalized["input_token_price_usd"] == 0.001
    assert normalized["output_token_price_usd"] == 0.002
    assert normalized["input_cost_usd"] == 0.1
    assert normalized["output_cost_usd"] == 0.04
    assert normalized["total_cost_usd"] == 0.14
