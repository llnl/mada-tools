import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "benchmark" / "mcp_tool_call_eval.py"

spec = importlib.util.spec_from_file_location("mcp_tool_call_eval", SCRIPT_PATH)
assert spec is not None
mcp_tool_call_eval = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mcp_tool_call_eval
spec.loader.exec_module(mcp_tool_call_eval)


def tool_result(arguments: dict[str, Any], tool_name: str = "generate_parameter_runs"):
    return mcp_tool_call_eval.ToolCallResult(
        tool_name=tool_name,
        tool_arguments=arguments,
        tool_arguments_raw=None,
        assistant_text=None,
        raw_message=None,
        raw_tool_calls=[],
        raw_response=None,
        usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        latency_ms=1,
    )


def make_test_case(
    arguments: dict[str, Any],
    tool: str = "generate_parameter_runs",
    mode: str = "subset",
    profile: str | None = "parameter_runs",
) -> dict[str, Any]:
    match: dict[str, Any] = {"mode": mode}
    if profile is not None:
        match["profile"] = profile
    return {
        "id": "case",
        "server": "server",
        "expected_call": {
            "tool": tool,
            "arguments": arguments,
            "match": match,
        },
        "prompts": [{"id": "direct", "text": "test"}],
    }


def fixture_with(test: dict[str, Any]) -> dict[str, Any]:
    return {"mcp_servers": {"server": {"url": "http://localhost:8000/mcp"}}, "tests": [test]}


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda case: case.pop("expected_call"), "expected_call object"),
        (lambda case: case["expected_call"].pop("tool"), "expected_call.tool"),
        (lambda case: case["expected_call"].pop("arguments"), "expected_call.arguments"),
        (lambda case: case["expected_call"]["match"].update({"mode": "loose"}), "match.mode"),
        (lambda case: case["expected_call"]["match"].update({"profile": "unknown"}), "match.profile"),
    ],
)
def test_validate_fixture_rejects_invalid_expected_call(mutator, message):
    case = make_test_case({})
    mutator(case)

    with pytest.raises(ValueError, match=message):
        mcp_tool_call_eval.validate_fixture(fixture_with(case))


def test_load_json_rejects_legacy_expected_tool_schema(tmp_path: Path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "mcp_servers": {"server": {"url": "http://localhost:8000/mcp"}},
                "tests": [
                    {
                        "id": "legacy",
                        "server": "server",
                        "expected_tool": "generate_parameter_runs",
                        "expected_arguments": {},
                        "prompts": ["prompt"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_call object"):
        mcp_tool_call_eval.load_json(path)


def test_exception_messages_formats_plain_exception():
    assert mcp_tool_call_eval.exception_messages(ValueError("bad value")) == ["ValueError: bad value"]


def test_exception_messages_flattens_exception_group_shape():
    class FakeExceptionGroup(Exception):
        def __init__(self, exceptions: tuple[BaseException, ...]):
            super().__init__("group")
            self.exceptions = exceptions

    error = FakeExceptionGroup(
        (
            ValueError("bad value"),
            FakeExceptionGroup((RuntimeError("runtime failed"),)),
        )
    )

    assert mcp_tool_call_eval.exception_messages(error) == [
        "ValueError: bad value",
        "RuntimeError: runtime failed",
    ]


def test_evaluate_result_accepts_generic_subset_extra_arguments():
    case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
    result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_generic_exact_extra_arguments():
    case = make_test_case({"command": "hostname"}, tool="submit_job", mode="exact", profile=None)
    result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_strict_overrides_subset_mode():
    case = make_test_case({"command": "hostname"}, tool="submit_job", mode="subset", profile=None)
    result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=True)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_accepts_no_argument_tool():
    case = make_test_case({}, tool="clear_model", profile=None)
    result = tool_result({}, tool_name="clear_model")

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_wrong_tool():
    case = make_test_case({}, tool="clear_model", profile=None)
    result = tool_result({}, tool_name="start_cubit")

    passed, error_type, error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "wrong_tool"
    assert "clear_model" in error


def test_evaluate_result_accepts_executable_parameter_alias_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "executable": ["exe", "discrete", ["skeleton_cpu"]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "skeleton_executable": ["exe", "discrete", ["skeleton_cpu"]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_zip_group_identifier_aliases_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], 1],
                "source_scale": ["def", "zip", [1.0, 0.8], 1],
                "right_source": ["def", "zip", ["right_a", "right_b"], 2],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], "source_group"],
                "source_scale": ["def", "zip", [1.0, 0.8], "source_group"],
                "right_source": ["def", "zip", ["right_a", "right_b"], "right_group"],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_collapsed_zip_groups_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "left_source": ["def", "zip", ["left_a", "left_b"], 1],
                "right_source": ["def", "zip", ["right_a", "right_b"], 2],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "left_source": ["def", "zip", ["left_a", "left_b"], "same_group"],
                "right_source": ["def", "zip", ["right_a", "right_b"], "same_group"],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_accepts_executable_zip_alias_with_group_identifier_alias():
    case = make_test_case(
        {
            "parameters": {
                "right_source": ["def", "zip", ["right_a", "right_b"], 2],
                "solver": ["exe", "zip", ["skeleton_cpu", "skeleton_gpu"], 2],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "right_source": ["def", "zip", ["right_a", "right_b"], "right_group"],
                "executable": ["exe", "zip", ["skeleton_cpu", "skeleton_gpu"], "right_group"],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_executable_alias_without_profile():
    case = make_test_case(
        {
            "parameters": {
                "executable": ["exe", "discrete", ["skeleton_cpu"]],
            },
        },
        profile=None,
    )
    result = tool_result(
        {
            "parameters": {
                "skeleton_executable": ["exe", "discrete", ["skeleton_cpu"]],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_accepts_deck_file_path_with_parameter_runs_profile():
    case = make_test_case(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/grid_problem",
            "input_deck_entrypoint": "input.deck",
        }
    )
    result = tool_result(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/grid_problem/input.deck",
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_deck_file_path_with_null_entrypoint_with_profile():
    case = make_test_case(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/blast",
            "input_deck_entrypoint": "main.deck",
        }
    )
    result = tool_result(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/blast/main.deck",
            "input_deck_entrypoint": None,
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_deck_file_path_with_matching_entrypoint_with_profile():
    case = make_test_case(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip",
            "input_deck_entrypoint": "multi.deck",
        }
    )
    result = tool_result(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip/multi.deck",
            "input_deck_entrypoint": "multi.deck",
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_deck_file_path_with_conflicting_entrypoint_with_profile():
    case = make_test_case(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip",
            "input_deck_entrypoint": "multi.deck",
        }
    )
    result = tool_result(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip/multi.deck",
            "input_deck_entrypoint": "other.deck",
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_accepts_absolute_dependency_paths_under_deck_path_with_profile():
    case = make_test_case(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/source_case",
            "dependency_paths": ["Materials", "Tables/table_a.dat"],
        }
    )
    result = tool_result(
        {
            "input_deck_path": "/tmp/mada_skeleton_eval/decks/source_case",
            "dependency_paths": [
                "/tmp/mada_skeleton_eval/decks/source_case/Materials",
                "/tmp/mada_skeleton_eval/decks/source_case/Tables/table_a.dat",
            ],
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_same_key_cli_expected_string_actual_tokens_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "restart_args": ["cli", "discrete", ["-restart old.chk"]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "restart_args": ["cli", "discrete", [["-restart", "old.chk"]]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_same_key_cli_expected_tokens_actual_string_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "log_args": ["cli", "discrete", [["--log", "debug"]]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "log_args": ["cli", "discrete", ["--log debug"]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_combined_cli_parameter_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "restart_flag": ["cli", "discrete", ["-r"]],
                "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "cli_args": ["cli", "discrete", [["-r", "-dm", "last", "-v", "-visit"]]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_combined_cli_string_parameter_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "restart_flag": ["cli", "discrete", ["-r"]],
                "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "cli_args": ["cli", "discrete", ["-r -dm last -v -visit"]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_missing_cli_tokens_with_parameter_runs_profile():
    case = make_test_case(
        {
            "parameters": {
                "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "cli_args": ["cli", "discrete", [["-dm", "last"]]],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_rejects_scalar_non_cli_parameter_values_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], "source_group"],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "source_file": ["def", "zip", "src/a.deck", "source_group"],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_strict_mode_rejects_parameter_runs_normalization():
    case = make_test_case(
        {
            "parameters": {
                "restart_flag": ["cli", "discrete", ["-r"]],
                "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "cli_args": ["cli", "discrete", [["-r", "-dm", "last", "-v", "-visit"]]],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=True)

    assert not passed
    assert error_type == "arg_mismatch"


def test_evaluate_result_accepts_discrete_def_numeric_string_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "INCLUDE_EXTRA": ["def", "discrete", [1]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "INCLUDE_EXTRA": ["def", "discrete", ["1"]],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_accepts_json_string_values_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "material": ["def", "discrete", ["Aluminum", "Steel"]],
                "plate_loc": ["def", "discrete", [5.0, 10.0]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "material": ["def", "discrete", '["Aluminum", "Steel"]'],
                "plate_loc": ["def", "discrete", "[5.0, 10.0]"],
            },
        }
    )

    assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)


def test_evaluate_result_rejects_json_string_non_list_values_with_profile():
    case = make_test_case(
        {
            "parameters": {
                "material": ["def", "discrete", ["Aluminum", "Steel"]],
            },
        }
    )
    result = tool_result(
        {
            "parameters": {
                "material": ["def", "discrete", '"Aluminum"'],
            },
        }
    )

    passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

    assert not passed
    assert error_type == "arg_mismatch"
