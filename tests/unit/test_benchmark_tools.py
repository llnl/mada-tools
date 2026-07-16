import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "benchmark"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))


def load_benchmark_module(module_name: str, filename: str):
    script_path = BENCHMARK_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eval_io = load_benchmark_module("eval_io", "eval_io.py")
populate_eval_models = load_benchmark_module("populate_eval_models", "populate_eval_models.py")
mcp_tool_call_eval = load_benchmark_module("mcp_tool_call_eval", "mcp_tool_call_eval.py")
run_tool_call_eval = load_benchmark_module("run_tool_call_eval", "run_tool_call_eval.py")
merge_tool_call_eval_results = load_benchmark_module("merge_tool_call_eval_results", "merge_tool_call_eval_results.py")


# eval_io


class TestEvalIo:
    def test_load_models_file_filters_tsv_by_inclusive_level(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text(
            "# Level Model\n2 model-two\n0 model-zero\n1 model-one\n",
            encoding="utf-8",
        )

        assert eval_io.load_models_file(models_file, level=1) == ["model-zero", "model-one"]

    def test_load_models_file_defaults_tsv_to_level_zero(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("1 model-one\n0 model-zero\n", encoding="utf-8")

        assert eval_io.load_models_file(models_file) == ["model-zero"]

    def test_load_models_file_preserves_plain_text_behavior(self, tmp_path: Path):
        models_file = tmp_path / "models.txt"
        models_file.write_text("# comment\nmodel-a\n\nmodel-b\n", encoding="utf-8")

        assert eval_io.load_models_file(models_file, level=0) == ["model-a", "model-b"]

    def test_load_models_file_rejects_malformed_tsv_rows(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-a extra\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected '<level> <model>'"):
            eval_io.load_models_file(models_file)

    def test_load_models_file_rejects_negative_level(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("-1 model-a\n", encoding="utf-8")

        with pytest.raises(ValueError, match="must be at least 0"):
            eval_io.load_models_file(models_file)


# populate_eval_models


class TestPopulateEvalModels:
    def test_extract_model_ids_dedupes_and_sorts(self):
        payload = {
            "data": [
                {"id": "model-b"},
                {"id": "model-a"},
                {"id": "model-b"},
                {"id": ""},
                {"name": "missing-id"},
            ]
        }

        assert populate_eval_models.extract_model_ids(payload) == ["model-a", "model-b"]

    def test_write_model_file_uses_level_aware_tsv_header(self, tmp_path: Path):
        output = tmp_path / "models.tsv"

        populate_eval_models.write_model_file(output, ["model-a", "model-b"], {"model-b": 2})

        assert output.read_text(encoding="utf-8") == (
            "# Shared eval model list that may be used in LLM testing.\n"
            "# One model per line with corresponding run level.\n"
            "# Set appropriate levels.\n"
            "# Comment out any model you may want to omit entirely from eval runs.\n"
            "# Level\tModel\n"
            "0\tmodel-a\n"
            "2\tmodel-b\n"
        )

    def test_refresh_model_files_initializes_missing_curated_file(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"

        initialized = populate_eval_models.refresh_model_files(["model-a"], all_output, enabled_output)

        assert initialized is True
        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")
        assert enabled_output.read_text(encoding="utf-8") == all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_does_not_overwrite_existing_curated_file(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        curated_content = "# custom curated header\n1\tmodel-b\n"
        enabled_output.write_text(curated_content, encoding="utf-8")

        initialized = populate_eval_models.refresh_model_files(["model-a"], all_output, enabled_output)

        assert initialized is False
        assert enabled_output.read_text(encoding="utf-8") == curated_content
        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_preserves_known_curated_levels(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        enabled_output.write_text(
            "# Level Model\n2 model-b\n1 model-c\n",
            encoding="utf-8",
        )

        populate_eval_models.refresh_model_files(["model-a", "model-b"], all_output, enabled_output)

        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")
        assert "2\tmodel-b\n" in all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_falls_back_to_existing_discovery_levels(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        all_output.write_text(
            "# Level Model\n3 model-a\n",
            encoding="utf-8",
        )

        populate_eval_models.refresh_model_files(["model-a", "model-b"], all_output, enabled_output)

        contents = enabled_output.read_text(encoding="utf-8")
        assert "3\tmodel-a\n" in contents
        assert "0\tmodel-b\n" in contents

    def test_load_existing_model_levels_rejects_malformed_rows(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("1 model-a extra\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected '<level> <model>'"):
            populate_eval_models.load_existing_model_levels(models_file)


# mcp_tool_call_eval


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


class TestMcpToolCallEval:
    def test_parse_args_loads_default_models_from_level_file(self, tmp_path: Path, monkeypatch):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n1 model-one\n", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mcp_tool_call_eval.py",
                "--cases",
                "cases.json",
                "--models-file",
                str(models_file),
                "--level",
                "1",
            ],
        )

        args = mcp_tool_call_eval.parse_args()

        assert args.models == ["model-zero", "model-one"]

    def test_parse_args_explicit_models_bypass_level_file(self, tmp_path: Path, monkeypatch):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mcp_tool_call_eval.py",
                "--cases",
                "cases.json",
                "--models",
                "model-explicit",
                "--models-file",
                str(models_file),
                "--level",
                "0",
            ],
        )

        args = mcp_tool_call_eval.parse_args()

        assert args.models == ["model-explicit"]

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
    def test_validate_fixture_rejects_invalid_expected_call(self, mutator, message):
        case = make_test_case({})
        mutator(case)

        with pytest.raises(ValueError, match=message):
            mcp_tool_call_eval.validate_fixture(fixture_with(case))

    def test_load_json_rejects_legacy_expected_tool_schema(self, tmp_path: Path):
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

    def test_exception_messages_formats_plain_exception(self):
        assert mcp_tool_call_eval.exception_messages(ValueError("bad value")) == ["ValueError: bad value"]

    def test_exception_messages_flattens_exception_group_shape(self):
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

    def test_load_model_prices_extracts_token_prices(self, tmp_path: Path):
        prices_path = tmp_path / "prices.json"
        prices_path.write_text(
            json.dumps(
                {
                    "sample_spec": {"input_cost_per_token": 0},
                    "gpt-test": {
                        "input_cost_per_token": 0.001,
                        "output_cost_per_token": 0.002,
                        "mode": "chat",
                    },
                    "image-test": {"output_cost_per_image": 0.01},
                }
            ),
            encoding="utf-8",
        )

        prices = mcp_tool_call_eval.load_model_prices(prices_path)

        assert set(prices) == {"gpt-test"}
        assert prices["gpt-test"].input_cost_per_token == 0.001
        assert prices["gpt-test"].output_cost_per_token == 0.002

    def test_build_row_adds_actual_cost_fields(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        prompt = {"id": "direct", "text": "test"}
        result = mcp_tool_call_eval.ToolCallResult(
            tool_name="submit_job",
            tool_arguments={"command": "hostname"},
            tool_arguments_raw=None,
            assistant_text=None,
            raw_message=None,
            raw_tool_calls=[],
            raw_response=None,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            latency_ms=15,
        )
        prices = {"gpt-test": mcp_tool_call_eval.ModelPricing(0.001, 0.002)}

        row = mcp_tool_call_eval.build_row("gpt-test", case, prompt, 1, result, True, None, None, prices)

        assert row["input_token_price_usd"] == 0.001
        assert row["output_token_price_usd"] == 0.002
        assert row["input_cost_usd"] == 0.1
        assert row["output_cost_usd"] == 0.04
        assert row["total_cost_usd"] == 0.14

    def test_build_row_leaves_costs_empty_without_tokens_or_price(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        prompt = {"id": "direct", "text": "test"}
        result = mcp_tool_call_eval.ToolCallResult(
            tool_name="submit_job",
            tool_arguments={"command": "hostname"},
            tool_arguments_raw=None,
            assistant_text=None,
            raw_message=None,
            raw_tool_calls=[],
            raw_response=None,
            usage={"prompt_tokens": None, "completion_tokens": 20, "total_tokens": None},
            latency_ms=15,
        )

        row = mcp_tool_call_eval.build_row("unknown", case, prompt, 1, result, True, None, None, {})

        assert row["input_token_price_usd"] is None
        assert row["output_token_price_usd"] is None
        assert row["input_cost_usd"] is None
        assert row["output_cost_usd"] is None
        assert row["total_cost_usd"] is None

    def test_summarize_adds_total_tokens_and_costs(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        fixture = fixture_with(case)
        rows = [
            {
                "model": "gpt-test",
                "server": "server",
                "case_id": "case",
                "prompt_id": "direct",
                "sample_index": 1,
                "passed": True,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "input_cost_usd": 0.1,
                "output_cost_usd": 0.04,
                "total_cost_usd": 0.14,
                "latency_ms": 10,
            },
            {
                "model": "gpt-test",
                "server": "server",
                "case_id": "case",
                "prompt_id": "direct",
                "sample_index": 2,
                "passed": False,
                "prompt_tokens": 110,
                "completion_tokens": 25,
                "total_tokens": 135,
                "input_cost_usd": 0.11,
                "output_cost_usd": 0.05,
                "total_cost_usd": 0.16,
                "latency_ms": 20,
            },
        ]

        summary = mcp_tool_call_eval.summarize(fixture, rows, num_samples=2)[0]

        assert summary["total_prompt_tokens"] == 210
        assert summary["total_completion_tokens"] == 45
        assert summary["total_tokens"] == 255
        assert summary["input_cost_usd"] == 0.21
        assert summary["output_cost_usd"] == 0.09
        assert summary["total_cost_usd"] == 0.3

    def test_evaluate_result_accepts_generic_subset_extra_arguments(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_generic_exact_extra_arguments(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", mode="exact", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_strict_overrides_subset_mode(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", mode="subset", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=True)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_no_argument_tool(self):
        case = make_test_case({}, tool="clear_model", profile=None)
        result = tool_result({}, tool_name="clear_model")

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_wrong_tool(self):
        case = make_test_case({}, tool="clear_model", profile=None)
        result = tool_result({}, tool_name="start_cubit")

        passed, error_type, error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "wrong_tool"
        assert "clear_model" in error

    def test_evaluate_result_accepts_executable_parameter_alias_with_parameter_runs_profile(self):
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

    def test_evaluate_result_accepts_zip_group_identifier_aliases_with_parameter_runs_profile(self):
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

    def test_evaluate_result_rejects_collapsed_zip_groups_with_parameter_runs_profile(self):
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

    def test_evaluate_result_accepts_executable_zip_alias_with_group_identifier_alias(self):
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

    def test_evaluate_result_rejects_executable_alias_without_profile(self):
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

    def test_evaluate_result_accepts_deck_file_path_with_parameter_runs_profile(self):
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

    def test_evaluate_result_accepts_deck_file_path_with_null_entrypoint_with_profile(self):
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

    def test_evaluate_result_accepts_deck_file_path_with_matching_entrypoint_with_profile(self):
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

    def test_evaluate_result_rejects_deck_file_path_with_conflicting_entrypoint_with_profile(self):
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

    def test_evaluate_result_accepts_absolute_dependency_paths_under_deck_path_with_profile(self):
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

    def test_evaluate_result_accepts_same_key_cli_expected_string_actual_tokens_with_profile(self):
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

    def test_evaluate_result_accepts_same_key_cli_expected_tokens_actual_string_with_profile(self):
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

    def test_evaluate_result_accepts_combined_cli_parameter_with_parameter_runs_profile(self):
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

    def test_evaluate_result_accepts_combined_cli_string_parameter_with_parameter_runs_profile(self):
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

    def test_evaluate_result_rejects_missing_cli_tokens_with_parameter_runs_profile(self):
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

    def test_evaluate_result_rejects_scalar_non_cli_parameter_values_with_profile(self):
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

    def test_evaluate_result_strict_mode_rejects_parameter_runs_normalization(self):
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

    def test_evaluate_result_accepts_discrete_def_numeric_string_with_profile(self):
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

    def test_evaluate_result_accepts_json_string_values_with_profile(self):
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

    def test_evaluate_result_rejects_json_string_non_list_values_with_profile(self):
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


# run_tool_call_eval


def cli_overrides(**overrides):
    defaults = {
        "models_file": None,
        "level": None,
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


class TestRunToolCallEval:
    def test_load_run_config_expands_env_vars(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MODEL_ID", "gpt-test")
        config_path = tmp_path / "run.json"
        config_path.write_text(json.dumps({"models": ["${MODEL_ID}"]}), encoding="utf-8")

        assert run_tool_call_eval.load_run_config(config_path) == {"models": ["gpt-test"]}

    def test_build_eval_args_resolves_paths_and_outputs(self, tmp_path: Path):
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
        assert eval_args.model_prices == run_tool_call_eval.DEFAULT_MODEL_PRICES_PATH
        assert eval_args.num_samples == 2
        assert eval_args.max_concurrency == 3
        assert eval_args.shard_count == 4
        assert eval_args.shard_index == 1
        assert eval_args.capture_raw_response is True

    def test_cli_overrides_replace_config_values(self, tmp_path: Path):
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

    def test_build_eval_args_allows_model_prices_override(self, tmp_path: Path):
        prices = tmp_path / "prices.json"
        prices.write_text("{}", encoding="utf-8")
        config = {
            "cases": "cases.json",
            "models": ["gpt-test"],
            "model_prices": "prices.json",
            "output": {"directory": "results", "timestamped": False},
        }

        output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, None)
        eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, cli_overrides(), output_dir, ["gpt-test"])

        assert eval_args.model_prices == prices.resolve()

    def test_models_from_config_filters_level_aware_file(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n1 model-one\n2 model-two\n", encoding="utf-8")
        config = {"models_file": "models.tsv"}

        assert run_tool_call_eval.models_from_config(config, tmp_path, None, level=1) == ["model-zero", "model-one"]

    def test_models_from_config_explicit_models_bypass_level_filtering(self, tmp_path: Path):
        config = {"models": ["model-two"]}

        assert run_tool_call_eval.models_from_config(config, tmp_path, None, level=0) == ["model-two"]

    def test_models_from_config_override_file_uses_level_filtering(self, tmp_path: Path):
        override_models_file = tmp_path / "override.tsv"
        override_models_file.write_text("0 model-zero\n1 model-one\n", encoding="utf-8")
        config = {"models": ["model-explicit"]}

        assert run_tool_call_eval.models_from_config(config, tmp_path, override_models_file, level=0) == ["model-zero"]

    def test_level_from_config_defaults_to_zero(self):
        assert run_tool_call_eval.level_from_config({}, cli_overrides()) == 0

    def test_level_from_config_cli_overrides_config(self):
        assert run_tool_call_eval.level_from_config({"level": 1}, cli_overrides(level=2)) == 2

    def test_missing_cost_annotations_marks_models_with_no_cost_data(self):
        rows = [
            {"model": "gpt-test", "case_id": "case-a", "total_cost_usd": ""},
            {"model": "gpt-test", "case_id": "case-b", "total_cost_usd": "n/a"},
            {"model": "gpt-test-2", "case_id": "case-a", "total_cost_usd": ""},
            {"model": "gpt-test-2", "case_id": "case-b", "total_cost_usd": 0.2},
        ]

        assert run_tool_call_eval.missing_cost_annotations(rows, "total_cost_usd") == {
            "gpt-test": "Missing Pricing",
        }

    def test_generate_plots_writes_cost_plot_when_cost_values_exist(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [
            {
                "model": "gpt-test",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.1,
            },
            {
                "model": "gpt-test-2",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.2,
            },
        ]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert [call["value_field"] for call in calls] == ["score_passed", "avg_total_tokens", "total_cost_usd"]
        assert calls[-1]["output_path"] == tmp_path / "flux_tool_call_cost.png"
        assert calls[-1]["title"] == "MCP Tool-Call Evaluation Cost By Model (Total: $0.300000)"
        assert calls[-1]["legend_title"] == "Test case"
        assert calls[-1]["show_legend_values"] is False
        assert calls[-1]["row_annotations"] == {}

    def test_generate_plots_marks_models_with_missing_pricing(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [
            {"model": "gpt-test", "case_id": "case-a", "score_passed": 1, "avg_total_tokens": 10, "total_cost_usd": ""},
            {"model": "gpt-test", "case_id": "case-b", "score_passed": 1, "avg_total_tokens": 10, "total_cost_usd": ""},
            {
                "model": "gpt-test-2",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.2,
            },
            {
                "model": "gpt-test-2",
                "case_id": "case-b",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": "n/a",
            },
        ]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert calls[-1]["value_field"] == "total_cost_usd"
        assert calls[-1]["row_annotations"] == {
            "gpt-test": "Missing Pricing",
        }

    def test_generate_plots_skips_cost_plot_without_cost_values(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [{"model": "gpt-test", "case_id": "case-a", "score_passed": 1, "avg_total_tokens": 10}]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert [call["value_field"] for call in calls] == ["score_passed", "avg_total_tokens"]


# merge_tool_call_eval_results


class TestMergeToolCallEvalResults:
    def test_normalize_base_row_accepts_legacy_rows_without_cost_fields(self, tmp_path: Path):
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

    def test_normalize_base_row_parses_cost_fields(self, tmp_path: Path):
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


# tool_call_eval_fixtures


class TestToolCallEvalFixtures:
    @pytest.mark.parametrize(
        "fixture_name",
        [
            "flux_tool_call_eval_cases.json",
            "slurm_tool_call_eval_cases.json",
        ],
    )
    def test_tool_call_eval_fixture_schema(self, fixture_name: str):
        fixture = mcp_tool_call_eval.load_json(BENCHMARK_DIR / fixture_name)

        assert fixture["mcp_servers"]
        assert fixture["tests"]
