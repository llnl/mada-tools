import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "benchmark"
SCRIPT_PATH = BENCHMARK_DIR / "mcp_tool_call_eval.py"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

spec = importlib.util.spec_from_file_location("mcp_tool_call_eval_for_fixtures", SCRIPT_PATH)
assert spec is not None
mcp_tool_call_eval = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mcp_tool_call_eval
spec.loader.exec_module(mcp_tool_call_eval)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "flux_tool_call_eval_cases.json",
        "slurm_tool_call_eval_cases.json",
    ],
)
def test_tool_call_eval_fixture_schema(fixture_name: str):
    fixture = mcp_tool_call_eval.load_json(BENCHMARK_DIR / fixture_name)

    assert fixture["mcp_servers"]
    assert fixture["tests"]
